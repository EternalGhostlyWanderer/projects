import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.chat import ChatResult
from app.agents.orchestrator import Agent
from app.api.deps import store_dependency
from app.db.store import AppStore
from app.main import app
from app.modules.companies import relationships, repository
from app.modules.news import service
from app.modules.news.sources.article import ArticleFetchError, parse_article_html, validate_public_url
from tests.test_agent import FULL_PLAN, ScriptedLLM, claim, draft

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"


def keywords_only(event, *, use_llm=True, llm=None):
    from app.modules.news.extraction import extract_event

    return extract_event(event, use_llm=False)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patches = [
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(service, "extract_event", keywords_only),
            patch("app.agents.tools.search_bank_research", return_value=[]),
        ]
        for item in cls.patches:
            item.start()
        repository.clear_company_cache()
        relationships.clear_relationship_cache()

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls.patches:
            item.stop()
        repository.clear_company_cache()
        relationships.clear_relationship_cache()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        app.dependency_overrides[store_dependency] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def load_news(self) -> None:
        service.load_events_file(self.store, SYNTHETIC / "news.json", use_llm=False)

    def run_agent_with(self, *drafts):
        llm = ScriptedLLM(self.temp_dir.name, plans=[FULL_PLAN] * 3, drafts=list(drafts))
        return lambda company_id, event, **kwargs: Agent(llm.client).run(company_id, event, **kwargs)

    def test_companies_come_from_synthetic_csv(self) -> None:
        response = self.client.get("/api/v1/companies", params={"q": "SYN_001"})

        self.assertEqual(response.headers["content-type"], "application/json; charset=utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["id"], "SYN_001")

    def test_protected_routes_require_demo_session_when_enabled(self) -> None:
        with patch.dict("os.environ", {"DEMO_AUTH_REQUIRED": "1"}):
            self.assertEqual(self.client.get("/api/v1/companies/SYN_001/profile").status_code, 401)
            self.assertEqual(self.client.get("/api/v1/research/documents").status_code, 401)
            self.assertEqual(self.client.get("/api/v1/system/status").status_code, 401)
            self.assertEqual(self.client.post("/api/v1/events/refresh").status_code, 401)

    def test_feed_differs_between_companies(self) -> None:
        self.load_news()

        borrower = self.client.get("/api/v1/feed", params={"company_id": "SYN_001"}).json()
        retailer = self.client.get("/api/v1/feed", params={"company_id": "SYN_002"}).json()

        borrower_titles = {item["event"]["title"] for item in borrower["items"]}
        retailer_titles = {item["event"]["title"] for item in retailer["items"]}
        self.assertIn("Банки ужесточили проверку платежей в Китай", borrower_titles)
        self.assertNotIn("Банки ужесточили проверку платежей в Китай", retailer_titles)
        self.assertNotIn("Футбольный клуб из Казани выиграл кубок", borrower_titles | retailer_titles)

    def test_analyze_stores_insight_trace_and_reuses_it(self) -> None:
        self.load_news()
        event = self.store.list_events(limit=100)[-1]
        data = draft(company_ids=("company.product.loa", "company.product.lea"))
        data["event_summary"] = [claim(event.title, "FACT", ["event.main"], "high")]

        with patch("app.api.v1.insights.run_agent", self.run_agent_with(data)):
            first = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "event_id": event.event_id},
            )
            second = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "event_id": event.event_id},
            )

        self.assertEqual(first.status_code, 200, first.text)
        insight = first.json()
        self.assertEqual(second.json()["insight_id"], insight["insight_id"])

        trace = self.client.get(f"/api/v1/insights/{insight['insight_id']}/trace").json()
        self.assertEqual(trace["insight_id"], insight["insight_id"])
        self.assertEqual(trace["steps"][0]["phase"], "plan")

        feed = self.client.get("/api/v1/feed", params={"company_id": "SYN_001", "only_relevant": False}).json()
        analyzed = [item for item in feed["items"] if item["insight"]]
        self.assertEqual(analyzed[0]["insight"]["insight_id"], insight["insight_id"])

    def test_analyze_pasted_text(self) -> None:
        data = draft()
        data["event_summary"] = [claim("Ставка сохранена", "FACT", ["event.main"], "high")]

        with patch("app.api.v1.insights.run_agent", self.run_agent_with(data)):
            response = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ключевую ставку", "text": "Ставка 14%."},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.count_events(), 1)

    def test_failed_analysis_reports_real_cause(self) -> None:
        # Дневной лимит исчерпан: сайт должен показать это, а не общее «Анализ не получен».
        from app.llm.client import BudgetExceededError

        def exhausted(company_id, event, **kwargs):
            llm = ScriptedLLM(self.temp_dir.name, plans=[FULL_PLAN], drafts=[])
            llm.client.check_budget = lambda: (_ for _ in ()).throw(
                BudgetExceededError("Дневной лимит запросов к LLM исчерпан: 400/400")
            )
            return Agent(llm.client).run(company_id, event, **kwargs)

        with patch("app.api.v1.insights.run_agent", exhausted):
            response = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ключевую ставку", "text": "Ставка 14%."},
            )

        self.assertEqual(response.status_code, 502)
        self.assertIn("Дневной лимит запросов к LLM исчерпан", response.json()["detail"]["message"])

    def test_analyze_validation_and_access(self) -> None:
        both = self.client.post(
            "/api/v1/insights/analyze",
            json={"company_id": "SYN_001", "event_id": "x", "title": "y"},
        )
        unknown = self.client.post("/api/v1/insights/analyze", json={"company_id": "NOPE", "title": "y"})
        foreign = self.client.post(
            "/api/v1/insights/analyze",
            json={"company_id": "SYN_001", "title": "y"},
            headers={"X-Company-Id": "SYN_002"},
        )

        self.assertEqual(both.status_code, 422)
        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(foreign.status_code, 403)

    def test_feedback_chat_and_foreign_access(self) -> None:
        data = draft()
        with patch("app.api.v1.insights.run_agent", self.run_agent_with(data)):
            insight = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ключевую ставку"},
            ).json()
        insight_id = insight["insight_id"]

        feedback = self.client.post(f"/api/v1/insights/{insight_id}/feedback", json={"useful": True})
        answer = ChatResult(
            answer=[claim("Расходы вырастут", "AI_INFERENCE", [])],
            follow_up_questions=[],
            evidence=[],
        )
        with patch("app.api.v1.insights.answer_question", return_value=answer):
            asked = self.client.post(f"/api/v1/insights/{insight_id}/ask", json={"question": "Что если ставка вырастет?"})
        history = self.client.get(f"/api/v1/insights/{insight_id}/chat").json()["items"]
        foreign = self.client.get(f"/api/v1/insights/{insight_id}", headers={"X-Company-Id": "SYN_002"})

        self.assertEqual(feedback.status_code, 204)
        self.assertEqual(asked.status_code, 200, asked.text)
        self.assertEqual([item["role"] for item in history], ["user", "assistant"])
        self.assertEqual(foreign.status_code, 403)
        status = self.client.get("/api/v1/system/status").json()
        self.assertEqual(status["feedback"]["useful"], 1)
        self.assertEqual(status["feedback"]["total"], 1)

    def test_budget_error_maps_to_429(self) -> None:
        from app.llm import BudgetExceededError

        def exhausted(*_, **__):
            raise BudgetExceededError("Дневной лимит")

        with patch("app.api.v1.insights.run_agent", exhausted):
            response = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ставку"},
            )

        self.assertEqual(response.status_code, 429)

    def test_missing_llm_key_maps_to_503(self) -> None:
        from app.llm.config import LLMConfigError

        def not_configured(*_, **__):
            raise LLMConfigError("LLM_API_KEY не настроен")

        with patch("app.api.v1.insights.run_agent", not_configured):
            response = self.client.post(
                "/api/v1/insights/analyze",
                json={"company_id": "SYN_001", "title": "ЦБ сохранил ставку"},
            )

        self.assertEqual(response.status_code, 503)

    def test_retailer_sees_retail_news_in_feed(self) -> None:
        self.load_news()

        feed = self.client.get("/api/v1/feed", params={"company_id": "SYN_002"}).json()

        titles = {item["event"]["title"] for item in feed["items"]}
        self.assertIn("Потребительский спрос в рознице начал охлаждаться", titles)

    def test_event_by_private_url_is_rejected(self) -> None:
        response = self.client.post("/api/v1/events", json={"url": "http://127.0.0.1/admin"})

        self.assertEqual(response.status_code, 400)


class ArticleTests(unittest.TestCase):
    def test_private_and_non_http_urls_are_rejected(self) -> None:
        for url in (
            "http://127.0.0.1/",
            "http://10.0.0.5/news",
            "http://169.254.169.254/latest/meta-data",
            "http://localhost:8000/",
            "file:///etc/passwd",
            "ftp://example.com/a",
            "http://user:pass@93.184.216.34/",
            "http://93.184.216.34:8080/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ArticleFetchError):
                    validate_public_url(url)

    def test_public_ip_is_allowed(self) -> None:
        self.assertEqual(validate_public_url("https://93.184.216.34/news"), "https://93.184.216.34/news")

    def test_parses_paragraphs_and_skips_navigation(self) -> None:
        html = """
        <html><head><title>Сайт</title><meta property="og:title" content="ЦБ сохранил ставку"></head>
        <body><nav><p>Меню сайта и ссылки на разделы, которые не относятся к статье</p></nav>
        <p>Банк России сохранил ключевую ставку на уровне 14% годовых, сообщил регулятор.</p>
        <script>var x = 1;</script>
        <p>Коротко</p></body></html>
        """

        title, text = parse_article_html(html)

        self.assertEqual(title, "ЦБ сохранил ставку")
        self.assertIn("14% годовых", text)
        self.assertNotIn("Меню", text)
        self.assertNotIn("var x", text)


if __name__ == "__main__":
    unittest.main()
