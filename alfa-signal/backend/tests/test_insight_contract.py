import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from app.ai.analyzer import analyze_event, check_draft_evidence
from app.ai.evidence import company_evidence, event_evidence
from app.ai.schemas import Evidence, Insight, InsightDraft
from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from app.modules.companies.profiling import build_company_profile
from app.schemas.company import Company


def valid_draft() -> dict:
    return {
        "schema_version": "2.0",
        "kind": "risk",
        "relevance": {
            "score": 80,
            "level": "high",
            "reasons": [
                {
                    "text": "У компании есть кредитные продукты",
                    "basis": "FACT",
                    "evidence_ids": ["company.product.loa"],
                    "confidence": "high",
                }
            ],
        },
        "event_summary": [
            {
                "text": "Регулятор сохранил ключевую ставку",
                "basis": "FACT",
                "evidence_ids": ["event.main"],
                "confidence": "high",
            }
        ],
        "mechanism": ["Сохранение ставки", "Стоимость фондирования", "Цена новых кредитов"],
        "direction": "negative",
        "primary_effect": {
            "text": "Новое финансирование может дешеветь медленнее плана",
            "basis": "AI_INFERENCE",
            "evidence_ids": ["event.main", "company.product.loa"],
            "confidence": "medium",
        },
        "risks": [
            {
                "title": "Дорогие заимствования",
                "text": "Условия новых кредитов могут остаться выше плана",
                "basis": "HYPOTHESIS",
                "evidence_ids": [],
                "confidence": "medium",
                "severity": "medium",
            }
        ],
        "opportunities": [],
        "scenarios": [],
        "bank_view": {"status": "not_found", "claims": []},
        "next_steps": [{"action": "Проверить график пересмотра ставок", "priority": "high"}],
        "unknowns": ["Размер задолженности"],
        "decision_question": "Когда планируются новые заимствования?",
    }


def make_context() -> dict:
    company = Company.model_validate(
        {
            "SYNTHETIC_U": "U_TEST",
            "CL_TYPE": "CLIENT",
            "MAINOKVED_CODE": "25.11",
            "MAINOKVED_NAME": "Производство металлических конструкций",
            "REGION": "Москва",
            "CL_PRODUCT_LOA_MARK": 1,
            "CL_PRODUCT_DEP_MARK": 0,
            "FTS_FLAG": 1,
            "FTS_COUNTRY_NAME": "Китай",
        }
    )
    return {
        "company_id": "U_TEST",
        "company_profile": build_company_profile(company),
        "payment_exposures": {
            "status": "available",
            "outgoing": {
                "counterparty_count": 12,
                "top_5_amount_share": 0.83,
                "concentration": "high",
            },
        },
        "sensitivity_factors": [{"factor": "interest_rate"}],
        "data_quality": {"missing_fields": ["financials.revenue_rub"], "warnings": []},
    }


EVENT = {
    "event_id": "EVT_1",
    "title": "Регулятор сохранил ключевую ставку",
    "summary": "Синтетический сценарий.",
    "url": "https://example.com/news/1",
    "impact_channels": ["interest_rate"],
}


class InsightContractTests(unittest.TestCase):
    def test_valid_draft_parses(self) -> None:
        draft = InsightDraft.model_validate(valid_draft())

        self.assertEqual(
            draft.referenced_evidence_ids(),
            {"company.product.loa", "event.main"},
        )

    def test_fact_without_sources_is_rejected(self) -> None:
        data = valid_draft()
        data["relevance"]["reasons"][0]["evidence_ids"] = []

        with self.assertRaises(ValidationError):
            InsightDraft.model_validate(data)

    def test_event_summary_accepts_only_facts(self) -> None:
        data = valid_draft()
        data["event_summary"][0]["basis"] = "AI_INFERENCE"

        with self.assertRaises(ValidationError):
            InsightDraft.model_validate(data)

    def test_bank_view_status_must_match_claims(self) -> None:
        found_without_claims = valid_draft()
        found_without_claims["bank_view"] = {"status": "found", "claims": []}
        ai_claim_as_bank = valid_draft()
        ai_claim_as_bank["bank_view"] = {
            "status": "found",
            "claims": [copy.deepcopy(valid_draft()["primary_effect"])],
        }

        for data in (found_without_claims, ai_claim_as_bank):
            with self.subTest(bank_view=data["bank_view"]):
                with self.assertRaises(ValidationError):
                    InsightDraft.model_validate(data)

    def test_insight_rejects_links_to_missing_evidence(self) -> None:
        with self.assertRaises(ValidationError):
            Insight.model_validate(
                {
                    **valid_draft(),
                    "insight_id": "i1",
                    "company_id": "U_TEST",
                    "event_id": "EVT_1",
                    "evidence": [],
                    "model": "test-model",
                    "created_at": "2026-10-25T00:00:00+00:00",
                    "quality_status": "unverified",
                }
            )


class EvidenceTests(unittest.TestCase):
    def test_company_evidence_uses_only_present_features(self) -> None:
        ids = {item.id for item in company_evidence(make_context())}

        self.assertIn("company.product.loa", ids)
        self.assertIn("company.fts", ids)
        self.assertIn("company.payments.outgoing", ids)
        self.assertNotIn("company.product.dep", ids)
        self.assertNotIn("company.revenue", ids)

    def test_bank_claim_must_cite_bank_material(self) -> None:
        data = valid_draft()
        data["bank_view"] = {
            "status": "found",
            "claims": [
                {
                    "text": "Банк ожидает паузу",
                    "basis": "BANK_ANALYSIS",
                    "evidence_ids": ["company.product.loa"],
                    "confidence": "medium",
                }
            ],
        }
        evidence = [*event_evidence(EVENT), *company_evidence(make_context())]

        errors = check_draft_evidence(InsightDraft.model_validate(data), evidence)

        self.assertTrue(any("неподходящие источники" in error for error in errors))
        self.assertTrue(any("not_found" in error for error in errors))

    def test_unknown_evidence_ids_are_reported(self) -> None:
        data = valid_draft()
        data["primary_effect"]["evidence_ids"] = ["company.debt"]
        evidence = [Evidence(id="event.main", type="FACT", text="x", source_kind="news")]

        errors = check_draft_evidence(InsightDraft.model_validate(data), evidence)

        self.assertTrue(any("company.debt" in error for error in errors))


class AnalyzeEventTests(unittest.TestCase):
    def test_returns_insight_with_evidence_pool(self) -> None:
        requests: list[dict] = []

        def create(**kwargs):
            requests.append(kwargs)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=json.dumps(valid_draft())),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            settings = LLMSettings(api_key="k", state_db=Path(temp_dir) / "llm.sqlite3")
            llm = LLMClient(
                settings=settings,
                client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),
                store=LLMStore(settings.state_db),
            )

            insight = analyze_event(make_context(), EVENT, {"matched_factors": []}, llm=llm)

        self.assertEqual(insight.company_id, "U_TEST")
        self.assertEqual(insight.event_id, "EVT_1")
        self.assertEqual(insight.quality_status, "unverified")
        self.assertIn("event.main", {item.id for item in insight.evidence})
        payload = json.loads(requests[0]["messages"][1]["content"])
        self.assertIn("company.product.loa", [item["id"] for item in payload["evidence"]])
        self.assertEqual(payload["missing_data"], ["financials.revenue_rub"])


if __name__ == "__main__":
    unittest.main()
