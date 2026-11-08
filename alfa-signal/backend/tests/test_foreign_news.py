import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.agents.orchestrator import Agent, persist_enriched_event
from app.agents.verify import _known_numbers
from app.ai.evidence import event_evidence
from app.ai.textcheck import extract_numbers, extract_source_numbers
from app.db.store import AppStore
from app.modules.news import foreign, service
from app.modules.news.extraction import classify_by_keywords
from app.modules.news.quality import source_trust
from app.modules.news.sources.article import Article
from app.modules.news.sources.base import RawNewsItem
from app.schemas.event import NewsEvent
from tests import test_agent
from tests.test_agent import EVENT, FULL_PLAN, draft
from tests.test_llm_client import make_client
from tests.test_source_health import Source


def english(title: str, summary: str = "", **extra) -> NewsEvent:
    return NewsEvent(
        event_id=extra.pop("event_id", "evt_en"), title=title, summary=summary or None, source="BBC",
        url="https://www.bbc.co.uk/news/1", language="en", **extra,
    )


class EnglishKeywordTests(unittest.TestCase):
    def test_foreign_rate_decision_is_currency_not_credit_cost(self) -> None:
        result = classify_by_keywords(english("Federal Reserve cuts interest rates", "The Fed lowered borrowing costs."))
        self.assertEqual(result.event_type, "currency")
        self.assertEqual(result.impact_channels, ["currency"])
        self.assertIn("США", result.entities.countries)

    def test_russian_rate_decision_in_english(self) -> None:
        result = classify_by_keywords(english("Bank of Russia holds key rate at 14%", "Inflation is slowing."))
        self.assertEqual(result.event_type, "monetary_policy")
        self.assertIn("interest_rate", result.impact_channels)

    def test_trade_countries_and_industry(self) -> None:
        result = classify_by_keywords(english("China imposes tariffs on steel imports from Turkey"))
        self.assertIn("international_trade", result.impact_channels)
        self.assertEqual(set(result.entities.countries), {"КИТАЙ", "ТУРЦИЯ"})
        self.assertIn("металлургия", result.entities.industries)
        self.assertIn("24", result.entities.okved_codes)

    def test_offtopic_english_news(self) -> None:
        self.assertEqual(classify_by_keywords(english("Pop star announces world tour dates")).impact_channels, [])

    def test_language_detection(self) -> None:
        self.assertTrue(foreign.is_english("Oil prices rise as OPEC agrees to cut output"))
        self.assertFalse(foreign.is_english("Нефть дорожает после решения ОПЕК+ по добыче"))
        self.assertFalse(foreign.is_english("Акции Apple и Microsoft подешевели"))


class SourcesConfigTests(unittest.TestCase):
    def test_foreign_feeds_added_and_can_be_disabled(self) -> None:
        with patch.dict("os.environ", {"NEWS_RSS_URLS": "https://a.ru/rss"}, clear=False):
            with patch.dict("os.environ", {"NEWS_RSS_URLS_FOREIGN": ""}):
                urls = service.configured_rss_urls()
            self.assertEqual(urls[0], "https://a.ru/rss")
            self.assertTrue(set(foreign.DEFAULT_FOREIGN_RSS_URLS) <= set(urls))
            with patch.dict("os.environ", {"NEWS_RSS_URLS_FOREIGN": "-"}):
                self.assertEqual(service.configured_rss_urls(), ["https://a.ru/rss"])

    def test_paywall_trust_only_slightly_lower(self) -> None:
        self.assertEqual(source_trust("https://www.bloomberg.com/news/x"), 0.95)
        self.assertEqual(source_trust("https://www.ft.com/content/x"), 0.95)
        self.assertEqual(source_trust("https://www.bbc.co.uk/news/x"), 1.0)
        self.assertEqual(source_trust("https://www.federalreserve.gov/newsevents/x"), 1.0)


class NumberTests(unittest.TestCase):
    def test_english_thousands_known_in_russian_forms(self) -> None:
        known = extract_source_numbers("Exports reached 12,500 tonnes, up 4.5%")
        self.assertTrue(extract_numbers("12 500 т, рост на 4,5%") <= known)
        self.assertTrue(extract_numbers("12500 т") <= known)


def translation(items: list[dict]) -> str:
    return json.dumps({"items": items}, ensure_ascii=False)


class TranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")

    def llm(self, answers: list[str]):
        client, completions, temp_dir = make_client(answers)
        self.addCleanup(temp_dir.cleanup)
        return client, completions

    def test_batch_translation_keeps_original(self) -> None:
        events = [
            english("Wheat exports from Russia rise 12%", "Shipments reached 12,500 tonnes.", event_id="a"),
            english("China cuts tariffs on steel", event_id="b"),
        ]
        llm, completions = self.llm([translation([
            {"id": "1", "title": "Экспорт пшеницы из России вырос на 12%", "summary": "Отгрузки достигли 12 500 тонн."},
            {"id": "2", "title": "Китай снизил пошлины на сталь", "summary": ""},
        ])])

        result = foreign.translate_events(events, llm=llm)

        self.assertEqual(len(completions.requests), 1)  # одна пачка — один запрос
        self.assertEqual(result[0].title, "Экспорт пшеницы из России вырос на 12%")
        self.assertEqual(result[0].original_title, "Wheat exports from Russia rise 12%")
        self.assertEqual(result[0].original_summary, "Shipments reached 12,500 tonnes.")
        self.assertFalse(foreign.needs_translation(result[1]))

    def test_translation_with_invented_number_rejected(self) -> None:
        event = english("Fed cuts rates by a quarter point")
        llm, _ = self.llm([translation([{"id": "1", "title": "ФРС снизила ставку на 0,25 п.п.", "summary": ""}])])

        result = foreign.translate_events([event], llm=llm)[0]

        self.assertEqual(result.title, "Fed cuts rates by a quarter point")
        self.assertFalse(foreign.needs_translation(result))  # повторно не переводим

    def test_collect_marks_language_and_translates(self) -> None:
        source = Source("bbc.co.uk", [
            RawNewsItem(
                title="China imposes new tariffs on steel imports",
                url="https://www.bbc.co.uk/news/2", source="BBC", published_at=datetime.now(timezone.utc),
                summary="Beijing raised duties on steel products from several countries.",
            ),
            RawNewsItem(
                title="Pop star announces world tour dates",
                url="https://www.bbc.co.uk/news/3", source="BBC", published_at=datetime.now(timezone.utc),
            ),
        ])
        llm, _ = self.llm([translation([
            {"id": "1", "title": "Китай ввёл новые пошлины на импорт стали",
             "summary": "Пекин повысил пошлины на стальную продукцию из ряда стран."},
        ])])

        with patch("app.modules.news.foreign.get_llm_client", return_value=llm):
            result = service.collect_rss(self.store, [], extra_sources=[source])

        self.assertEqual(result["skipped_offtopic"], 1)
        self.assertEqual(result["translated"], 1)
        stored = self.store.list_events()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].title, "Китай ввёл новые пошлины на импорт стали")
        self.assertEqual(stored[0].language, "en")
        self.assertEqual(stored[0].original_title, "China imposes new tariffs on steel imports")
        self.assertIn("international_trade", stored[0].impact_channels)

    def test_no_llm_key_leaves_english_for_next_run(self) -> None:
        self.store.save_event(english("China cuts tariffs on steel"))
        with patch.dict("os.environ", {"LLM_API_KEY": "", "LLM_PROVIDER": "gemini"}):
            self.assertEqual(foreign.translate_pending(self.store), 0)
        self.assertTrue(foreign.needs_translation(self.store.list_events()[0]))


class FullArticleTests(unittest.TestCase):
    # Настройка как в тестах агента: профиль, аналитика банка и прогнозы без сети.
    setUp = test_agent.AgentTests.setUp
    agent = test_agent.AgentTests.agent

    ARTICLE = Article(
        url="https://example.com/rate", title="t", source="example.com",
        text="Совет директоров Банка России сохранил ключевую ставку. " * 30,
    )

    def test_agent_fetches_article_when_feed_has_only_announcement(self) -> None:
        agent, _ = self.agent(plans=[FULL_PLAN], drafts=[draft(bank=True)])
        with patch.dict("os.environ", {"NEWS_FETCH_FULL_TEXT": "1"}), patch(
            "app.agents.tools.fetch_article", return_value=self.ARTICLE
        ):
            result = agent.run("U_TEST", EVENT)

        step = next(step for step in result.trace.steps if step.name == "get_full_article")
        self.assertEqual(step.status, "ok")
        self.assertIn("event.text", {item.id for item in result.insight.evidence})
        self.assertIsNotNone(result.enriched_event)

        store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        store.save_event(EVENT)
        persist_enriched_event(store, result)
        self.assertTrue(store.get_event(EVENT.event_id).text.startswith("Совет директоров"))

    def test_fetch_failure_does_not_stop_analysis(self) -> None:
        from app.modules.news.sources.article import ArticleFetchError

        agent, _ = self.agent(plans=[FULL_PLAN], drafts=[draft(bank=True)])
        with patch.dict("os.environ", {"NEWS_FETCH_FULL_TEXT": "1"}), patch(
            "app.agents.tools.fetch_article", side_effect=ArticleFetchError("402")
        ):
            result = agent.run("U_TEST", EVENT)

        step = next(step for step in result.trace.steps if step.name == "get_full_article")
        self.assertEqual(step.status, "error")
        self.assertIsNotNone(result.insight)
        self.assertIsNone(result.enriched_event)


class ArticleEvidenceTests(unittest.TestCase):
    def test_article_text_becomes_evidence(self) -> None:
        event = english("China cuts tariffs", "Short announcement.", text="Full article text. " * 40).model_dump(mode="json")
        ids = {item.id for item in event_evidence(event)}
        self.assertIn("event.text", ids)

    def test_known_numbers_accept_english_format(self) -> None:
        from types import SimpleNamespace

        insight = SimpleNamespace(evidence=[SimpleNamespace(text="Exports reached 12,500 tonnes")])
        self.assertIn("12500", _known_numbers(insight, {}))


if __name__ == "__main__":
    unittest.main()
