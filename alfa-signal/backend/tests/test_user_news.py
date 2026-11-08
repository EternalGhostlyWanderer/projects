"""Новость, которую пользователь прислал сам: ссылка или текст."""
import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from fastapi.testclient import TestClient

from app.agents.orchestrator import Agent
from app.agents.verify import final_status, verify_insight
from app.api.deps import store_dependency
from app.db.snapshot import export_snapshot
from app.db.store import AppStore
from app.main import app
from app.modules.companies import relationships, repository
from app.modules.news import service
from app.modules.news.sources import article
from app.modules.news.sources.article import Article, ArticleFetchError
from tests.test_agent import FULL_PLAN, ScriptedLLM, claim, draft

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC = PROJECT_ROOT / "data" / "synthetic"
LONG_TEXT = "Банк России сохранил ключевую ставку на уровне 14% годовых. " * 12


def keywords_only(event, *, use_llm=True, llm=None):
    from app.modules.news.extraction import extract_event

    return extract_event(event, use_llm=False)


class _Response:
    def __init__(self, html: str) -> None:
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self._body = html.encode("utf-8")

    def read(self, _limit: int) -> bytes:
        return self._body

    def geturl(self) -> str:
        return "https://news.example.com/a"

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class _Opener:
    def __init__(self, result) -> None:
        self.result = result

    def open(self, request, timeout):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def fetch_with(result):
    """fetch_article без сети: адрес считается публичным, ответ задан тестом."""
    return [
        patch.object(article, "validate_public_url", lambda url: url),
        patch.object(article, "build_opener", lambda *handlers: _Opener(result)),
    ]


class FetchArticleTests(unittest.TestCase):
    def fetch(self, result):
        patches = fetch_with(result)
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        return article.fetch_article("https://news.example.com/a")

    def test_http_errors_explain_what_to_do(self) -> None:
        for code, words in ((402, "подписке"), (403, "закрыл доступ"), (404, "не найдена")):
            error = HTTPError("https://news.example.com/a", code, "x", Message(), io.BytesIO())
            with self.subTest(code=code), self.assertRaisesRegex(ArticleFetchError, words):
                self.fetch(error)

    def test_timeout_is_named(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, "не ответил"):
            self.fetch(URLError(TimeoutError("timed out")))

    def test_paywall_teaser_is_kept_and_flagged(self) -> None:
        html = (
            "<title>Пошлины на прокат</title><p>Правительство ввело пошлины на экспорт металлопроката.</p>"
            "<p>Материал доступен только для подписчиков. Оформите подписку, чтобы продолжить чтение.</p>"
        )

        result = self.fetch(_Response(html))

        self.assertTrue(result.paywalled)
        self.assertIn("пошлины", result.text)

    def test_page_with_title_only(self) -> None:
        result = self.fetch(_Response("<title>Пошлины на прокат</title><p>коротко</p>"))

        self.assertEqual(result.title, "Пошлины на прокат")
        self.assertEqual(result.text, "")

    def test_page_without_title_is_an_error(self) -> None:
        with self.assertRaisesRegex(ArticleFetchError, "вручную"):
            self.fetch(_Response("<p>" + "текст " * 50 + "</p>"))


class UserNewsTests(unittest.TestCase):
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

    def analyze(self, body: dict):
        data = draft()
        data["event_summary"] = [claim("Ставка сохранена", "FACT", ["event.main"], "high")]
        llm = ScriptedLLM(self.temp_dir.name, plans=[FULL_PLAN] * 3, drafts=[data] * 3)
        runner = lambda company_id, event, **kwargs: Agent(llm.client).run(company_id, event, **kwargs)  # noqa: E731
        with patch("app.api.v1.insights.run_agent", runner):
            return self.client.post("/api/v1/insights/analyze", json={"company_id": "SYN_001", **body})

    def feed_titles(self, company_id: str) -> set[str]:
        feed = self.client.get("/api/v1/feed", params={"company_id": company_id, "only_relevant": False}).json()
        return {item["event"]["title"] for item in feed["items"]}

    def test_user_news_skips_collection_filters(self) -> None:
        # Кликбейт-заголовок и тема «не про бизнес» при сборе отсеялись бы; присланную новость разбираем.
        response = self.analyze({"title": "Россиянам рассказали о пошлинах на металлопрокат", "text": LONG_TEXT})

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.store.count_events(), 1)

    def test_title_only_is_partial_with_explanation(self) -> None:
        response = self.analyze({"title": "Банк России сохранил ключевую ставку"})

        insight = response.json()
        self.assertEqual(insight["quality_status"], "partial")
        self.assertTrue(any("одному заголовку" in issue for issue in insight["quality_issues"]))
        event = self.store.get_event(insight["event_id"])
        self.assertEqual((event.content, event.submitted_by), ("title_only", "SYN_001"))

    def test_full_text_stays_verified(self) -> None:
        response = self.analyze({"title": "Банк России сохранил ключевую ставку", "text": LONG_TEXT})

        insight = response.json()
        self.assertEqual(self.store.get_event(insight["event_id"]).content, "full")
        self.assertFalse(any("заголовку" in issue or "фрагменту" in issue for issue in insight["quality_issues"]))

    def test_paywalled_url_is_partial(self) -> None:
        fetched = Article(url="https://news.example.com/a", title="Пошлины на прокат", text=LONG_TEXT, source="news.example.com", paywalled=True)
        with patch.object(service, "fetch_article", return_value=fetched):
            response = self.analyze({"url": "https://news.example.com/a"})

        self.assertEqual(response.json()["quality_status"], "partial")
        self.assertEqual(self.store.get_event(response.json()["event_id"]).content, "partial")

    def test_known_url_is_not_fetched_again(self) -> None:
        fetched = Article(url="https://news.example.com/a", title="Ставка ЦБ", text=LONG_TEXT, source="news.example.com")
        with patch.object(service, "fetch_article", return_value=fetched) as fetch:
            first = self.analyze({"url": "https://news.example.com/a?utm_source=tg"})
            second = self.analyze({"url": "https://news.example.com/a"})

        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(first.json()["insight_id"], second.json()["insight_id"])

    def test_fetch_error_is_400_with_message(self) -> None:
        with patch.object(service, "fetch_article", side_effect=ArticleFetchError("Статья доступна только по платной подписке")):
            response = self.analyze({"url": "https://news.example.com/paid"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("подписке", response.json()["detail"])

    def test_internal_address_is_refused(self) -> None:
        response = self.analyze({"url": "http://127.0.0.1:8000/api/v1/system/status"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.store.count_events(), 0)

    def test_pasted_news_is_private_to_the_company(self) -> None:
        self.analyze({"title": "Наш поставщик металла поднял цены на 12%", "text": LONG_TEXT})

        self.assertIn("Наш поставщик металла поднял цены на 12%", self.feed_titles("SYN_001"))
        self.assertNotIn("Наш поставщик металла поднял цены на 12%", self.feed_titles("SYN_002"))
        snapshot = export_snapshot(self.store, ["SYN_002"])
        self.assertEqual(snapshot["events"], [])

    def test_same_publication_from_feeds_becomes_public(self) -> None:
        url = "https://news.example.com/rate"
        fetched = Article(url=url, title="Банк России сохранил ключевую ставку", text=LONG_TEXT, source="news.example.com")
        with patch.object(service, "fetch_article", return_value=fetched):
            self.analyze({"url": url})
        public = service.ingest_text(self.store, title="Банк России сохранил ключевую ставку на уровне 14%", text=LONG_TEXT, source="РБК", url="https://rbc.ru/rate", use_llm=False)

        self.assertIsNone(public.submitted_by)
        self.assertIn("Банк России сохранил ключевую ставку", self.feed_titles("SYN_002"))

    def test_analyzed_event_stays_in_feed_below_threshold(self) -> None:
        self.analyze({"title": "Футбольный клуб из Казани выиграл кубок", "text": LONG_TEXT})

        feed = self.client.get("/api/v1/feed", params={"company_id": "SYN_001"}).json()
        titles = {item["event"]["title"] for item in feed["items"]}
        self.assertIn("Футбольный клуб из Казани выиграл кубок", titles)

    def test_repeat_with_shorter_text_keeps_known_event(self) -> None:
        first = service.ingest_text(self.store, title="Ставка ЦБ", text=LONG_TEXT, url="https://news.example.com/x", use_llm=False)
        with patch.object(service, "extract_event") as extract:
            again = service.ingest_text(self.store, title="Ставка ЦБ", text="коротко", url="https://news.example.com/x", use_llm=False)

        extract.assert_not_called()
        self.assertEqual(again.text, first.text)


class LimitedContentStatusTests(unittest.TestCase):
    def test_limited_text_makes_status_partial(self) -> None:
        from tests.test_agent import EVENT, VerifyTests

        insight = VerifyTests().insight(draft(bank=True))
        report = verify_insight(insight, event={**EVENT.model_dump(mode="json"), "content": "partial"})

        self.assertIn("source_text_limited", {issue.code for issue in report.issues})
        self.assertEqual(final_status(report), "partial")


if __name__ == "__main__":
    unittest.main()
