import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.orchestrator import Agent
from app.agents.verify import verify_insight
from app.ai.evidence import bank_evidence, company_evidence, event_evidence
from app.ai.schemas import Insight
from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from app.modules.companies.profiling import build_company_profile
from app.schemas.company import Company
from app.schemas.event import NewsEvent

EVENT = NewsEvent(
    event_id="evt_rate",
    title="Банк России сохранил ключевую ставку на уровне 14%",
    source="test",
    url="https://example.com/rate",
    summary="Совет директоров взял паузу.",
    event_type="monetary_policy",
    impact_channels=["interest_rate", "deposit_yield", "leasing_cost"],
)

BANK_CHUNK = {
    "chunk_id": "policy_rate_2026_09_11-p1-01",
    "doc_id": "policy_rate_2026_09_11",
    "doc_title": "Ключевая ставка ЦБ РФ",
    "doc_date": "2026-09-11",
    "page": 1,
    "text": "Мы ожидаем сохранения паузы и ставки на уровне 14,0% до конца года.",
}


def _forecast(value, doc_id, date, page):
    return {"indicator": "key_rate_end", "period": "2026", "value": value, "doc_id": doc_id,
            "doc_title": doc_id, "doc_date": date, "page": page}


# Реальный случай из обзоров банка: 31.07 — 13,5% на конец 2026, 11.09 — 14,0%.
from app.research.forecasts import forecast_table  # noqa: E402

FORECASTS = forecast_table([
    _forecast(13.5, "macro_1h26_2026_07_31", "2026-07-31", 4),
    _forecast(14.0, "policy_rate_2026_09_11", "2026-09-11", 2),
])


def make_context() -> dict:
    company = Company.model_validate(
        {
            "SYNTHETIC_U": "U_TEST",
            "CL_TYPE": "CLIENT",
            "MAINOKVED_CODE": "41.20",
            "MAINOKVED_NAME": "Строительство жилых и нежилых зданий",
            "REGION": "Москва",
            "CL_PRODUCT_LOA_MARK": 1,
            "CL_PRODUCT_LEA_MARK": 1,
        }
    )
    return {
        "context_version": "1.0",
        "company_id": "U_TEST",
        "company_profile": build_company_profile(company),
        "payment_exposures": {"status": "unavailable"},
        "sensitivity_factors": [{"factor": "interest_rate"}, {"factor": "leasing_cost"}],
        "data_quality": {"missing_fields": ["financials.revenue_rub"], "warnings": []},
    }


def claim(text, basis, ids, confidence="medium"):
    return {"text": text, "basis": basis, "evidence_ids": ids, "confidence": confidence}


def draft(*, company_ids=("company.product.loa", "company.product.lea"), bank=False, risk_text=None) -> dict:
    data = {
        "schema_version": "2.0",
        "kind": "risk",
        "relevance": {
            "score": 75,
            "level": "high",
            "reasons": [claim("У компании есть кредитные продукты", "FACT", [company_ids[0]], "high")],
        },
        "event_summary": [claim("Банк России сохранил ключевую ставку на уровне 14%", "FACT", ["event.main"], "high")],
        "mechanism": ["Ставка сохранена", "Стоимость фондирования", "Условия кредитов и лизинга"],
        "direction": "negative",
        "primary_effect": claim(
            "Удешевление кредитов и лизинга откладывается",
            "AI_INFERENCE",
            ["event.main", *company_ids],
        ),
        "risks": [
            {
                **claim(risk_text or "Новое финансирование останется дорогим", "AI_INFERENCE", list(company_ids)),
                "title": "Дорогое финансирование",
                "severity": "medium",
            }
        ],
        "opportunities": [],
        "scenarios": [],
        "bank_view": {"status": "not_found", "claims": []},
        "next_steps": [{"action": "Проверить даты пересмотра ставок", "priority": "high"}],
        "unknowns": ["Размер задолженности"],
        "decision_question": "Когда привлекать новое финансирование?",
    }
    if bank:
        data["bank_view"] = {
            "status": "found",
            "claims": [
                claim(
                    "Аналитики банка ожидают сохранения паузы и ставки до конца года",
                    "BANK_ANALYSIS",
                    [f"bank.{BANK_CHUNK['chunk_id']}"],
                )
            ],
        }
    return data


class ScriptedLLM:
    """Routes chat requests by system prompt and replays queued answers."""

    def __init__(self, temp_dir: str, *, plans=(), drafts=(), revisions=()) -> None:
        self.queues = {"plan": list(plans), "analyze": list(drafts), "revise": list(revisions)}
        self.calls: list[str] = []
        settings = LLMSettings(api_key="k", state_db=Path(temp_dir) / "llm.sqlite3")
        self.client = LLMClient(
            settings=settings,
            client=SimpleNamespace(chat=SimpleNamespace(completions=self)),
            store=LLMStore(settings.state_db),
        )

    def create(self, **kwargs):
        system = kwargs["messages"][0]["content"]
        route = (
            "plan" if "планировщик" in system
            else "revise" if "Реши, что сделать дальше" in system
            else "analyze"
        )
        self.calls.append(route)
        answer = self.queues[route].pop(0)
        if isinstance(answer, Exception):
            raise answer
        content = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=None,
        )


FULL_PLAN = {
    "steps": [
        {"tool": "get_company_profile", "reason": "профиль"},
        {"tool": "assess_relevance", "reason": "совпадения"},
        {
            "tool": "search_bank_research",
            "args": {"query": "решение по ключевой ставке", "channels": ["interest_rate"]},
            "reason": "позиция банка",
        },
    ]
}


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patches = [
            patch("app.agents.tools.build_personalization_context", side_effect=lambda *_: make_context()),
            patch("app.agents.tools.search_bank_research", return_value=[BANK_CHUNK]),
            patch("app.agents.tools.bank_forecasts", return_value=FORECASTS),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def agent(self, **queues) -> tuple[Agent, ScriptedLLM]:
        llm = ScriptedLLM(self.temp_dir.name, **queues)
        return Agent(llm.client), llm

    def test_happy_path_is_verified_and_traced(self) -> None:
        agent, llm = self.agent(plans=[FULL_PLAN], drafts=[draft(bank=True)])

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(result.insight.quality_status, "verified")
        self.assertEqual(result.insight.trace_id, result.trace.trace_id)
        phases = [step.phase for step in result.trace.steps]
        self.assertEqual(phases, ["plan", "tool", "tool", "tool", "tool", "synthesize", "verify", "finalize"])
        self.assertEqual(result.trace.tool_calls, 4)
        # Сверка с прогнозами добавлена политикой: событие про ставку.
        forecast_step = next(step for step in result.trace.steps if step.name == "get_bank_forecasts")
        self.assertIn("13.5 → 14", forecast_step.output_summary)
        self.assertEqual(llm.calls, ["plan", "analyze"])
        self.assertIn(f"bank.{BANK_CHUNK['chunk_id']}", {item.id for item in result.insight.evidence})

    def test_agent_searches_bank_after_verification_warning(self) -> None:
        plan_without_bank = {"steps": [{"tool": "assess_relevance", "reason": "совпадения"}]}
        revision = {
            "action": "call_tools",
            "steps": [
                {
                    "tool": "search_bank_research",
                    "args": {"query": "прогноз ключевой ставки", "channels": ["interest_rate"]},
                    "reason": "нужна позиция банка",
                }
            ],
            "reason": "аналитика банка не запрашивалась",
        }
        agent, llm = self.agent(
            plans=[plan_without_bank],
            drafts=[draft(), draft(bank=True)],
            revisions=[revision],
        )

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(llm.calls, ["plan", "analyze", "revise", "analyze"])
        self.assertEqual(result.trace.rounds, 1)
        self.assertEqual(result.insight.bank_view.status, "found")
        self.assertEqual(result.insight.quality_status, "verified")
        self.assertIn("добавлено политикой: get_company_profile", result.trace.steps[0].output_summary)

    def test_planner_failure_falls_back_to_default_plan(self) -> None:
        agent, _ = self.agent(plans=[RuntimeError("gateway down")], drafts=[draft(bank=True)])

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(result.trace.steps[0].name, "default_plan")
        self.assertEqual(result.trace.steps[0].status, "error")
        self.assertEqual(result.insight.quality_status, "verified")

    def test_rule_plan_without_llm(self) -> None:
        agent, llm = self.agent(drafts=[draft(bank=True)])

        with patch.dict("os.environ", {"AGENT_LLM_PLAN": "0"}):
            result = agent.run("U_TEST", EVENT)

        self.assertEqual(llm.calls, ["analyze"])
        self.assertEqual(result.trace.steps[0].name, "default_plan")
        self.assertEqual(result.trace.steps[0].status, "ok")
        self.assertEqual(result.insight.quality_status, "verified")

    def test_plan_is_shared_between_companies(self) -> None:
        agent, llm = self.agent(plans=[FULL_PLAN], drafts=[draft(bank=True), draft(bank=True)])

        agent.run("U_TEST", EVENT)
        agent.run("U_OTHER", EVENT)

        # План зависит только от события: для второй компании он берётся из кеша.
        self.assertEqual(llm.calls.count("plan"), 1)

    def test_unfixable_error_ends_as_partial_after_revision_limit(self) -> None:
        bad = draft(bank=True, risk_text="Расходы вырастут на 25%")
        resynthesize = {"action": "resynthesize", "reason": "убрать число"}
        agent, llm = self.agent(
            plans=[FULL_PLAN],
            drafts=[bad, copy.deepcopy(bad), copy.deepcopy(bad)],
            revisions=[resynthesize, resynthesize],
        )

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(result.trace.rounds, 2)
        self.assertEqual(result.insight.quality_status, "partial")
        self.assertTrue(any("25" in issue for issue in result.insight.quality_issues))
        self.assertEqual(llm.calls.count("analyze"), 3)
        # Замечание к тексту: решение «переписать» принимает код, запрос к LLM не нужен.
        self.assertNotIn("revise", llm.calls)

    def test_fact_with_inference_is_relabeled_without_extra_round(self) -> None:
        data = draft(bank=True)
        data["relevance"]["reasons"][0]["text"] = "У компании есть кредиты, поэтому стоимость долга зависит от ставки"
        agent, llm = self.agent(plans=[FULL_PLAN], drafts=[data])

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(llm.calls, ["plan", "analyze"])
        self.assertEqual(result.trace.rounds, 0)
        self.assertEqual(result.insight.quality_status, "verified")
        self.assertEqual(result.insight.relevance.reasons[0].basis, "AI_INFERENCE")
        self.assertTrue(result.insight.relevance.reasons[0].evidence_ids)
        verify_step = next(step for step in result.trace.steps if step.phase == "verify")
        self.assertTrue(verify_step.output_summary.startswith("FACT → AI_INFERENCE: 1"))

    def test_invalid_tool_in_plan_is_repaired(self) -> None:
        bad_plan = {"steps": [{"tool": "transfer_money", "reason": "?"}]}
        agent, llm = self.agent(plans=[bad_plan, FULL_PLAN], drafts=[draft(bank=True)])

        result = agent.run("U_TEST", EVENT)

        self.assertEqual(llm.calls[:2], ["plan", "plan"])
        self.assertNotIn("transfer_money", [step.name for step in result.trace.steps])

    def test_missing_company_fails_gracefully(self) -> None:
        with patch("app.agents.tools.build_personalization_context", return_value=None):
            agent, _ = self.agent(plans=[FULL_PLAN])
            result = agent.run("U_MISSING", EVENT)

        self.assertIsNone(result.insight)
        self.assertEqual(result.trace.status, "failed")


class VerifyTests(unittest.TestCase):
    def insight(self, data: dict, chunks=(BANK_CHUNK,)) -> Insight:
        context = make_context()
        return Insight(
            **data,
            insight_id="i",
            company_id="U_TEST",
            event_id=EVENT.event_id,
            evidence=[
                *event_evidence(EVENT.model_dump(mode="json")),
                *company_evidence(context),
                *bank_evidence(chunks),
            ],
            model="m",
            created_at="2026-10-25T00:00:00+00:00",
            quality_status="unverified",
        )

    def codes(self, data: dict, **kwargs) -> set[str]:
        report = verify_insight(
            self.insight(data),
            event=EVENT.model_dump(mode="json"),
            missing_data=kwargs.get("missing", ["financials.revenue_rub"]),
            bank_searched=kwargs.get("bank_searched", True),
        )
        return {issue.code for issue in report.issues}

    def test_clean_insight_has_no_issues(self) -> None:
        self.assertEqual(self.codes(draft(bank=True)), set())

    def test_fact_with_inference_is_flagged(self) -> None:
        data = draft(bank=True)
        data["relevance"]["reasons"][0]["text"] = "Стоимость лизинга зависит от ставки"

        self.assertIn("fact_contains_inference", self.codes(data))

    def test_bank_claim_must_match_chunk_text(self) -> None:
        data = draft(bank=True)
        data["bank_view"]["claims"][0]["text"] = "Банк рекомендует срочно продавать валюту"

        self.assertIn("bank_claim_not_supported", self.codes(data))

    def test_single_factor_and_unused_bank_are_warnings(self) -> None:
        data = draft(company_ids=("company.product.loa",))

        codes = self.codes(data)

        self.assertIn("single_company_factor", codes)
        self.assertIn("bank_unused", codes)

    def test_relevance_must_use_company_data(self) -> None:
        data = draft(bank=True)
        data["relevance"]["reasons"] = [claim("Ставка важна", "AI_INFERENCE", ["event.main"])]

        self.assertIn("relevance_without_company_data", self.codes(data))

    def test_identifiers_are_not_numbers(self) -> None:
        data = draft(bank=True)
        data["mechanism"] = [*data["mechanism"], "Компания U_9250 зависит от стоимости заёмных средств"]

        self.assertNotIn("unsupported_number", self.codes(data))

    def test_okved_codes_are_not_numbers(self) -> None:
        data = draft(bank=True)
        data["mechanism"] = [*data["mechanism"], "Пошлины касаются металлургии (ОКВЭД 24, 25), а не розницы (ОКВЭД 47.11)"]

        self.assertNotIn("unsupported_number", self.codes(data))

    def test_okved_does_not_hide_amount(self) -> None:
        data = draft(bank=True)
        data["mechanism"] = [*data["mechanism"], "Отрасль ОКВЭД 25, потери 740 млн руб."]

        self.assertIn("unsupported_number", self.codes(data))

    def test_invented_number_is_error_and_year_is_warning(self) -> None:
        data = draft(bank=True)
        data["mechanism"] = [*data["mechanism"], "К 2031 году расходы вырастут на 37%"]

        codes = self.codes(data)

        self.assertIn("unsupported_number", codes)
        self.assertIn("unsupported_year", codes)

    def test_year_alone_does_not_block(self) -> None:
        data = draft(bank=True)
        data["mechanism"] = [*data["mechanism"], "Эффект проявится в 2031 году"]

        codes = self.codes(data)

        self.assertNotIn("unsupported_number", codes)
        self.assertIn("unsupported_year", codes)

    def test_empty_unknowns_with_missing_profile_fields(self) -> None:
        data = draft(bank=True)
        data["unknowns"] = []

        self.assertIn("unknowns_missing", self.codes(data))


if __name__ == "__main__":
    unittest.main()
