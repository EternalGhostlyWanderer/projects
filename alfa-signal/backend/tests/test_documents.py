import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.ai.evidence import company_evidence
from app.api.deps import store_dependency
from app.db.store import AppStore
from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from app.main import app
from app.modules.companies import links, relationships, repository
from app.modules.companies.documents import (
    DocumentError,
    DocumentExtraction,
    check_extraction,
    extract_from_document,
    merge_with_sources,
    read_document,
)
from app.modules.companies.user_data import user_data_evidence
from app.modules.personalization.scoring import score_event
from tests.test_scoring import context, event

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"
DOCUMENT = (
    "Годовой отчёт ООО «Пример» за 2025 год. Доля экспорта в выручке составила 35%. Основные покупатели — "
    "металлургические комбинаты. Расчёты с поставщиками из Китая ведутся в юанях (CNY). "
    "В 2026 году планируется привлечь кредит 500 млн руб. на модернизацию цеха. "
    "Нас особенно беспокоят пошлины на металл и курс юаня."
)
EXTRACTION = {
    "document_type": "годовой отчёт",
    "fields": [
        {"field": "export_share_pct", "value": 35, "quote": "Доля экспорта в выручке составила 35%"},
        {"field": "customer_industries", "value": ["металлургия"], "quote": "Основные покупатели — металлургические комбинаты"},
        {"field": "contract_currencies", "value": ["CNY"], "quote": "ведутся в юанях (CNY)"},
        {"field": "borrowing_plans", "value": "кредит 500 млн руб. на модернизацию цеха", "quote": "планируется привлечь кредит 500 млн руб. на модернизацию цеха"},
        {"field": "interests", "value": ["пошлины на металл", "курс юаня"], "quote": "беспокоят пошлины на металл и курс юаня"},
        {"field": "export_share_pct", "value": 250, "quote": "Доля экспорта в выручке составила 35%"},
    ],
}


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


class ReadDocumentTests(unittest.TestCase):
    def test_text_file_and_pdf(self) -> None:
        self.assertEqual(read_document(text="  текст  "), "текст")
        encoded = base64.b64encode("отчёт".encode()).decode()
        self.assertEqual(read_document(file_base64=encoded, filename="report.txt"), "отчёт")

        import pymupdf

        pdf = pymupdf.open()
        pdf.new_page().insert_text((72, 72), "Export share 35%")
        data = base64.b64encode(pdf.tobytes()).decode()
        self.assertIn("Export share 35%", read_document(file_base64=data, filename="r.pdf"))

    def test_errors(self) -> None:
        for kwargs in ({}, {"file_base64": "###", "filename": "a.txt"}, {"file_base64": "YQ==", "filename": "a.docx"}):
            with self.assertRaises(DocumentError):
                read_document(**kwargs)


class ExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def test_quote_must_be_in_document(self) -> None:
        invented = DocumentExtraction.model_validate(
            {"fields": [{"field": "export_share_pct", "value": 80, "quote": "экспорт 80% выручки"}, {"field": "note", "value": "x", "quote": "Годовой отчёт"}]}
        )
        errors = check_extraction(invented, DOCUMENT)
        self.assertTrue(any("не найдена" in error for error in errors))
        self.assertTrue(any("не из списка" in error for error in errors))
        self.assertEqual(check_extraction(DocumentExtraction.model_validate(EXTRACTION), DOCUMENT), [])

    def test_preview_with_quotes_and_rejected_values(self) -> None:
        llm = ScriptedLLM(self.temp_dir.name, [EXTRACTION])
        preview = extract_from_document(DOCUMENT, document="отчёт.pdf", llm=llm.client)

        fields = {item["field"]: item for item in preview["fields"]}
        self.assertEqual(fields["export_share_pct"]["value"], 35)
        self.assertEqual(fields["contract_currencies"]["value"], ["CNY"])
        self.assertEqual(preview["rejected"][0]["field"], "export_share_pct")  # 250% не прошло проверку
        self.assertIn("игнорируй", llm.requests[0]["messages"][0]["content"])
        self.assertEqual(llm.requests[0]["model"], LLMSettings(api_key="k").model_for("extract"))

    def test_merge_keeps_sources_and_evidence_names_document(self) -> None:
        merged = merge_with_sources(
            {"floating_debt_rub": 1e9, "updated_at": "x"},
            [{"field": "export_share_pct", "value": 35, "quote": "Доля экспорта 35%"}],
            document="отчёт.pdf",
            user_id="demo",
            now="2026-10-26T10:00:00+00:00",
        )
        self.assertEqual(merged["field_sources"]["export_share_pct"]["source"], "document")
        evidence = {item.id: item for item in user_data_evidence(merged)}
        self.assertIn("Из документа пользователя «отчёт.pdf»", evidence["company.user.export"].text)
        self.assertTrue(evidence["company.user.debt"].text.startswith("Со слов пользователя"))


class ScoringFromUserDataTests(unittest.TestCase):
    def test_interests_export_and_customers_raise_score(self) -> None:
        plain = context(profile={"products": {}, "risk_indicators": {}, "industry": {"code": "47.11", "name": "Розница"}})
        duty = {**event("trade", ["international_trade", "industry"], codes=["24", "25"]), "title": "Введены экспортные пошлины на металлопрокат"}
        self.assertEqual(score_event(plain, duty)["score"], 0)

        user = {"interests": ["пошлины на металл"], "export_share_pct": 35, "customer_industries": ["металлургия"]}
        scored = score_event({**plain, "user_data": user}, duty)
        groups = {part["group"] for part in scored["components"]}
        self.assertTrue({"interests", "channels", "supply_chain"} <= groups)
        self.assertIn("пошлины на металл", scored["explanation"])

        yuan = {**event("currency", ["currency"]), "title": "Курс юаня вырос до 12 рублей"}
        groups = {part["group"] for part in score_event({**plain, "user_data": {"interests": ["курс юаня"]}}, yuan)["components"]}
        self.assertEqual(groups, {"interests"})
        other = {**event("currency", ["currency"]), "title": "Курс доллара снизился"}
        self.assertEqual(score_event({**plain, "user_data": {"interests": ["курс юаня"]}}, other)["score"], 0)


class UserDataApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        app.dependency_overrides[store_dependency] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        for patcher in (
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        repository.clear_company_cache()
        self.addCleanup(repository.clear_company_cache)
        self.client = TestClient(app)

    def test_extract_apply_edit_history(self) -> None:
        with patch("app.api.v1.companies.extract_from_document", return_value={"fields": [], "rejected": []}) as extract:
            response = self.client.post("/api/v1/companies/SYN_001/user-data/extract", json={"text": DOCUMENT, "filename": "отчёт"})
        self.assertEqual(response.status_code, 200)
        extract.assert_called_once()
        self.assertEqual(self.client.post("/api/v1/companies/SYN_001/user-data/extract", json={}).status_code, 400)

        applied = self.client.post(
            "/api/v1/companies/SYN_001/user-data/apply-document",
            json={"document": "отчёт.pdf", "fields": [{"field": "export_share_pct", "value": 35, "quote": "Доля экспорта 35%"}]},
            headers={"X-User-Id": "demo"},
        ).json()["data"]
        self.assertEqual(applied["field_sources"]["export_share_pct"]["source"], "document")

        # Ручная правка другого поля: источник документа у доли экспорта сохраняется.
        body = {key: value for key, value in applied.items() if key != "updated_at"}
        edited = self.client.put(
            "/api/v1/companies/SYN_001/user-data", json={**body, "floating_debt_rub": 1e9}, headers={"X-User-Id": "buh"}
        ).json()["data"]
        self.assertEqual(edited["field_sources"]["export_share_pct"]["source"], "document")
        self.assertEqual(edited["field_sources"]["floating_debt_rub"]["source"], "manual")

        history = self.client.get("/api/v1/companies/SYN_001/user-data/history").json()["items"]
        self.assertEqual([(item["source"], item["user_id"]) for item in history], [("manual", "buh"), ("document", "demo")])
        self.assertEqual(history[0]["fields"], ["floating_debt_rub"])

        bad = self.client.post(
            "/api/v1/companies/SYN_001/user-data/apply-document",
            json={"fields": [{"field": "field_sources", "value": {}}]},
        )
        self.assertEqual(bad.status_code, 422)


if __name__ == "__main__":
    unittest.main()
