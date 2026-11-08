import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.role_view import RoleViewDraft, build_role_view, check_role_view, rules_view
from app.api.deps import store_dependency
from app.db.store import AppStore
from app.llm.client import LLMClient
from app.llm.config import LLMConfigError, LLMSettings
from app.llm.store import LLMStore
from app.main import app
from app.modules.companies import position
from app.modules.companies.position import describe_position, industry_position
from app.schemas.company import Company
from tests.test_chat import make_insight


class ScriptedLLM:
    def __init__(self, temp_dir: str, answers: list) -> None:
        self.answers, self.requests = list(answers), []
        settings = LLMSettings(api_key="k", state_db=Path(temp_dir) / "llm.sqlite3")
        self.client = LLMClient(
            settings=settings, client=SimpleNamespace(chat=SimpleNamespace(completions=self)), store=LLMStore(settings.state_db)
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content = json.dumps(self.answers.pop(0), ensure_ascii=False)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")], usage=None)


def answer(text="Дорогое финансирование сохраняется — пересмотрите график заимствований", number=""):
    return {
        "headline": f"Для финансового директора: кредиты не подешевеют{number}",
        "points": [{"text": text, "basis": "AI_INFERENCE", "evidence_ids": ["event.main"], "confidence": "medium"}],
        "risk_order": ["Дорогое финансирование"],
        "next_steps": [{"action": "Сверить даты пересмотра ставок по кредитам", "priority": "high"}],
    }


class RoleViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.insight = make_insight()

    def test_llm_view_for_role(self) -> None:
        llm = ScriptedLLM(self.temp_dir.name, [answer()])
        view = build_role_view(self.insight, "cfo", llm=llm.client)

        self.assertEqual((view.role, view.method), ("cfo", "llm"))
        self.assertIn("финансовый директор", llm.requests[0]["messages"][0]["content"])
        self.assertEqual(view.risk_order, ["Дорогое финансирование"])

    def test_invented_numbers_and_unknown_risks_are_rejected(self) -> None:
        draft = RoleViewDraft.model_validate({**answer(number=" ещё 3 года на 17,5%"), "risk_order": ["Новый риск"]})
        errors = check_role_view(draft, self.insight)
        self.assertTrue(any("17.5" in error for error in errors))
        self.assertTrue(any("risk_order" in error for error in errors))
        # Исправленный ответ после повтора принимается.
        llm = ScriptedLLM(self.temp_dir.name, [answer(number=" на 17,5%"), answer()])
        self.assertEqual(build_role_view(self.insight, "cfo", llm=llm.client).method, "llm")
        self.assertEqual(len(llm.requests), 2)

    def test_rules_view_with_long_effect(self) -> None:
        effect = self.insight.primary_effect.model_copy(update={"text": "Длинный эффект " * 40})
        insight = self.insight.model_copy(update={"primary_effect": effect})

        draft = rules_view(insight, "cfo")

        self.assertLessEqual(len(draft.headline), 300)

    def test_rules_without_llm(self) -> None:
        with patch("app.agents.role_view.get_llm_client", side_effect=LLMConfigError("нет ключа")):
            view = build_role_view(self.insight, "accountant")
        self.assertEqual(view.method, "rules")
        self.assertTrue(view.headline.startswith("Главный бухгалтер"))
        self.assertTrue(view.points)
        draft = rules_view(self.insight, "cfo")
        self.assertEqual(check_role_view(draft, self.insight), [])

    def test_api_caches_per_role(self) -> None:
        store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        with patch.object(store, "get_insight", return_value=self.insight):
            app.dependency_overrides[store_dependency] = lambda: store
            self.addCleanup(app.dependency_overrides.clear)
            client = TestClient(app)
            with patch("app.api.v1.insights.build_role_view", wraps=lambda insight, role: rules_view_view(insight, role)) as build:
                first = client.get("/api/v1/insights/i1/role-view", headers={"X-User-Role": "accountant"}).json()
                client.get("/api/v1/insights/i1/role-view", headers={"X-User-Role": "accountant"})
                other = client.get("/api/v1/insights/i1/role-view", params={"role": "owner"}).json()
        self.assertEqual(first["role"], "accountant")
        self.assertEqual(other["role"], "owner")
        self.assertEqual(build.call_count, 2)


def rules_view_view(insight, role):
    with patch("app.agents.role_view.get_llm_client", side_effect=LLMConfigError("нет ключа")):
        return build_role_view(insight, role)


def company(index: int, revenue: float, code="46.71", group=None) -> Company:
    return Company.model_validate(
        {"SYNTHETIC_U": f"U_{index}", "MAINOKVED_CODE": code, "REVENUE_COMPANY": revenue, "GROUP_ID": group}
    )


class IndustryPositionTests(unittest.TestCase):
    def setUp(self) -> None:
        position.clear_position_cache()
        self.addCleanup(position.clear_position_cache)
        self.companies = tuple(
            [company(i, revenue) for i, revenue in enumerate([50e9, 30e9, 10e9, 5e9, 2e9, 1e9, 1000], start=1)]
            + [company(8, 8e9, group="g1"), company(9, 7e9, group="g1"), company(10, 99e9, code="01.11")]
        )

    def position(self, item: Company) -> dict:
        with patch.object(position, "get_all_companies", return_value=self.companies):
            return industry_position(item)

    def test_rank_share_and_group(self) -> None:
        leader = self.position(self.companies[0])
        self.assertEqual((leader["rank"], leader["peers"], leader["tier"]), (1, 8, "leader"))
        self.assertAlmostEqual(leader["share_of_sample"], 50 / 113, places=3)

        member = self.position(self.companies[7])
        self.assertEqual(member["rank"], 4)
        self.assertEqual(member["group"]["rank"], 3)  # группа 8+7=15 млрд — третья после 50 и 30
        self.assertIn("группа компаний — 3-е место", describe_position(member))

    def test_unreliable_cases(self) -> None:
        self.assertEqual(self.position(self.companies[9])["status"], "too_few_peers")
        self.assertEqual(self.position(self.companies[6])["status"], "no_revenue")  # заглушка 1000 руб.
        self.assertIsNone(describe_position({"status": "too_few_peers"}))


if __name__ == "__main__":
    unittest.main()
