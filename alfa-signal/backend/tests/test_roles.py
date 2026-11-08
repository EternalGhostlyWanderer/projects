"""Пользователи и роли: одна компания, несколько сотрудников с разными задачами."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.chat import ChatResult
from app.db.store import AppStore
from app.modules.personalization.roles import ROLE_MAX
from app.modules.personalization.scoring import MIN_FEED_SCORE, score_event
from tests.test_agent import claim, draft
from tests import test_api
from tests.test_scoring import RATE, context, event

TAX = {**event("taxes", ["regulation"]), "title": "Правительство изменило порядок уплаты НДС"}
BUILDER_RULES = event("regulation", ["regulation"], codes=["41"])

CFO = {"X-User-Id": "anna", "X-User-Role": "cfo"}
ACCOUNTANT = {"X-User-Id": "olga", "X-User-Role": "accountant"}


class RoleScoringTests(unittest.TestCase):
    def test_without_role_score_is_unchanged(self) -> None:
        self.assertEqual(score_event(context(), RATE), score_event(context(), RATE, role=None))
        self.assertIsNone(score_event(context(), RATE)["role"])
        self.assertEqual(score_event(context(), RATE, role="other")["score"], score_event(context(), RATE)["score"])

    def test_cfo_ranks_rate_decision_higher_than_accountant(self) -> None:
        cfo = score_event(context(), RATE, role="cfo")
        accountant = score_event(context(), RATE, role="accountant")

        self.assertGreater(cfo["score"], accountant["score"])
        role_part = next(item for item in cfo["components"] if item["group"] == "role")
        self.assertLessEqual(role_part["points"], ROLE_MAX)
        self.assertIn("финансовый директор", role_part["reason"])
        # Сумма факторов по-прежнему равна баллу.
        self.assertEqual(sum(item["points"] for item in cfo["components"]), cfo["score"])

    def test_tax_news_reaches_accountant_of_any_company(self) -> None:
        plain = context(profile={"products": {}, "risk_indicators": {}})

        self.assertEqual(score_event(plain, TAX)["score"], 0)
        accountant = score_event(plain, TAX, role="accountant")
        self.assertGreater(accountant["score"], 0)
        self.assertTrue(accountant["role_universal"])  # в ленте бухгалтера и ниже порога
        # Собственнику не связанный с компанией налог в ленту не добавляется.
        self.assertEqual(score_event(plain, TAX, role="owner")["score"], 0)

    def test_sector_rules_do_not_reach_accountant_of_other_industry(self) -> None:
        retailer = context(profile={"industry": {"code": "47.11", "name": "Розница"}, "products": {}})

        self.assertEqual(score_event(retailer, BUILDER_RULES, role="accountant")["score"], 0)

    def test_unknown_role_is_ignored(self) -> None:
        self.assertIsNone(score_event(context(), RATE, role="pilot")["role"])


class RoleApiTests(unittest.TestCase):
    # Та же настройка, что в ApiTests: синтетические компании, временная база, без LLM.
    setUpClass = classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_api.ApiTests.tearDownClass.__func__)
    setUp = test_api.ApiTests.setUp
    load_news = test_api.ApiTests.load_news
    run_agent_with = test_api.ApiTests.run_agent_with

    def feed(self, company_id: str, headers: dict, **params) -> dict:
        response = self.client.get("/api/v1/feed", params={"company_id": company_id, **params}, headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_login_returns_user_and_role(self) -> None:
        with patch.dict("os.environ", {"DEMO_USERS": ""}):
            cfo = self.client.post("/api/v1/auth/login", json={"login": "demo", "password": "alfa-signal"}).json()
            accountant = self.client.post("/api/v1/auth/login", json={"login": "buh", "password": "alfa-signal"}).json()
        with patch.dict("os.environ", {"DEMO_USERS": "ivan:pw:SYN_001:treasury:Иван;old:pw:SYN_001"}):
            custom = self.client.post("/api/v1/auth/login", json={"login": "ivan", "password": "pw"}).json()
            legacy = self.client.post("/api/v1/auth/login", json={"login": "old", "password": "pw"}).json()

        self.assertEqual((cfo["user_id"], cfo["role"]), ("demo", "cfo"))
        self.assertEqual((accountant["user_id"], accountant["role"]), ("buh", "accountant"))
        self.assertEqual(cfo["companies"], accountant["companies"])
        self.assertEqual((custom["role"], custom["name"], custom["companies"]), ("treasury", "Иван", ["SYN_001"]))
        # Старый формат DEMO_USERS без роли работает: роль по умолчанию.
        self.assertEqual((legacy["role"], legacy["name"]), ("cfo", "old"))

    def test_roles_endpoint(self) -> None:
        roles = self.client.get("/api/v1/auth/roles").json()

        self.assertIn({"id": "accountant", "label": "Главный бухгалтер"}, roles["items"])

    def test_feed_order_depends_on_role(self) -> None:
        self.load_news()

        cfo = self.feed("SYN_001", CFO)
        accountant = self.feed("SYN_001", ACCOUNTANT)
        by_query = self.feed("SYN_001", {}, role="accountant")

        self.assertEqual((cfo["user_id"], cfo["role"]), ("anna", "cfo"))
        cfo_titles = [item["event"]["title"] for item in cfo["items"]]
        accountant_titles = [item["event"]["title"] for item in accountant["items"]]
        self.assertNotEqual(cfo_titles, accountant_titles)
        self.assertEqual(accountant_titles, [item["event"]["title"] for item in by_query["items"]])
        rate = next(item for item in cfo["items"] if item["event"]["event_type"] == "monetary_policy")
        self.assertIn("role", {part["group"] for part in rate["relevance"]["components"]})

    def test_invalid_role_is_rejected(self) -> None:
        response = self.client.get(
            "/api/v1/feed", params={"company_id": "SYN_001"}, headers={"X-User-Role": "pilot"}
        )

        self.assertEqual(response.status_code, 422)

    def test_hidden_events_are_per_user(self) -> None:
        self.load_news()
        first = self.feed("SYN_001", CFO)["items"][0]["event"]

        hidden = self.client.post(
            "/api/v1/feed/hidden", json={"company_id": "SYN_001", "event_id": first["event_id"]}, headers=CFO
        )

        self.assertEqual(hidden.status_code, 204)
        self.assertNotIn(first["title"], [item["event"]["title"] for item in self.feed("SYN_001", CFO)["items"]])
        self.assertIn(first["title"], [item["event"]["title"] for item in self.feed("SYN_001", ACCOUNTANT)["items"]])
        self.assertIn(first["title"], [item["event"]["title"] for item in self.feed("SYN_001", {})["items"]])

    def test_chat_feedback_and_requests_are_per_user(self) -> None:
        with patch("app.api.v1.insights.run_agent", self.run_agent_with(draft())):
            insight_id = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ключевую ставку"},
                headers=CFO,
            ).json()["insight_id"]
        answer = ChatResult(answer=[claim("Расходы вырастут", "AI_INFERENCE", [])], follow_up_questions=[], evidence=[])

        with patch("app.api.v1.insights.answer_question", return_value=answer) as ask:
            self.client.post(f"/api/v1/insights/{insight_id}/ask", json={"question": "Что с долгом?"}, headers=CFO)
        self.client.post(f"/api/v1/insights/{insight_id}/feedback", json={"useful": True}, headers=CFO)
        self.client.post(f"/api/v1/insights/{insight_id}/feedback", json={"useful": False}, headers=ACCOUNTANT)
        self.client.post(
            f"/api/v1/insights/{insight_id}/requests", json={"kind": "manager_callback"}, headers=ACCOUNTANT
        )

        # Роль из заголовка доходит до чата; разбор у обоих пользователей один.
        self.assertEqual(ask.call_args.kwargs["role"], "cfo")
        self.assertEqual(len(self.chat(insight_id, CFO)), 2)
        self.assertEqual(self.chat(insight_id, ACCOUNTANT), [])
        self.assertEqual(
            self.client.get(f"/api/v1/insights/{insight_id}", headers=ACCOUNTANT).json()["insight_id"], insight_id
        )
        feedback = self.client.get("/api/v1/system/status").json()["feedback"]
        self.assertEqual(feedback["by_role"]["cfo"], {"useful": 1, "total": 1})
        self.assertEqual(feedback["by_role"]["accountant"], {"useful": 0, "total": 1})
        request = self.client.get("/api/v1/companies/SYN_001/requests").json()["items"][0]
        self.assertEqual((request["user_id"], request["role"]), ("olga", "accountant"))

    def chat(self, insight_id: str, headers: dict) -> list:
        return self.client.get(f"/api/v1/insights/{insight_id}/chat", headers=headers).json()["items"]


class StoreMigrationTests(unittest.TestCase):
    def test_old_database_keeps_hidden_events_and_chat(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old.sqlite3"
            with sqlite3.connect(path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE hidden_events (company_id TEXT NOT NULL, event_id TEXT NOT NULL,
                        created_at TEXT NOT NULL, PRIMARY KEY (company_id, event_id));
                    INSERT INTO hidden_events VALUES ('SYN_001', 'evt_1', '2026-10-01');
                    CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, insight_id TEXT NOT NULL,
                        role TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
                    INSERT INTO chat_messages (insight_id, role, data, created_at)
                        VALUES ('i1', 'user', '{"text": "вопрос"}', '2026-10-01');
                    CREATE TABLE feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, insight_id TEXT NOT NULL,
                        useful INTEGER NOT NULL, comment TEXT, created_at TEXT NOT NULL);
                    """
                )
            connection.close()

            store = AppStore(path)
            AppStore(path)  # повторный запуск миграции ничего не ломает

            self.assertEqual(store.hidden_event_ids("SYN_001"), {"evt_1"})
            self.assertEqual(store.hidden_event_ids("SYN_001", "anna"), set())
            self.assertEqual([item["text"] for item in store.chat_history("i1")], ["вопрос"])
            store.save_feedback("i1", True, None, user_id="anna", role="cfo")
            self.assertEqual(store.feedback_summary()["by_role"], {"cfo": {"useful": 1, "total": 1}})


if __name__ == "__main__":
    unittest.main()
