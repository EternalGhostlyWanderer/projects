import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.db.store import AppStore
from app.modules.news import service
from app.modules.news.extraction import extract_event
from app.modules.news.sources.base import RawNewsItem
from app.schemas.event import NewsEvent
from tests.test_api import keywords_only


def item(title: str, number: int) -> RawNewsItem:
    return RawNewsItem(
        title=title,
        source="rbc.ru",
        url=f"https://www.rbc.ru/news/{number}",
        published_at=datetime.now(timezone.utc),
    )


class FeedSource:
    """Вместо сети: RSS-лента с заранее заданными записями."""

    kind = "news"
    last_error = None

    def __init__(self, name: str, url: str, max_items: int = 50) -> None:
        self.name, self.url = name, url

    def fetch(self) -> list[RawNewsItem]:
        return list(FEED)


FEED = [
    item("Банк России сохранил ключевую ставку на уровне 14% годовых", 1),
    item("«Зенит» обыграл «Динамо» и вернулся на первое место в РПЛ", 2),
    item("Более половины американцев заявили, что стали жить хуже", 3),
    item("Рубль ослаб к юаню на фоне снижения экспортной выручки", 4),
]


def keyword_channels(title: str) -> list[str]:
    event = NewsEvent(event_id="x", title=title, source="s", url="https://example.com/x")
    return extract_event(event, use_llm=False).impact_channels


class OfftopicCollectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        for patcher in (
            patch.object(service, "RSSNewsSource", FeedSource),
            patch.object(service, "extract_event", side_effect=keywords_only),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_news_without_impact_channels_are_not_stored(self) -> None:
        result = service.collect_rss(self.store, ["https://www.rbc.ru/rss"])

        self.assertEqual(
            {event.title for event in result["added"]},
            {FEED[0].title, FEED[3].title},
        )
        self.assertEqual(result["skipped_offtopic"], 2)
        self.assertEqual(self.store.count_events(), 2)

    def test_offtopic_urls_are_not_classified_again(self) -> None:
        service.collect_rss(self.store, ["https://www.rbc.ru/rss"])
        with patch.object(service, "extract_event", side_effect=keywords_only) as extract:
            again = service.collect_rss(self.store, ["https://www.rbc.ru/rss"])

        self.assertEqual(again["skipped_known_urls"], 4)
        extract.assert_not_called()

    def test_can_keep_everything(self) -> None:
        with patch.dict("os.environ", {"NEWS_KEEP_OFFTOPIC": "1"}):
            result = service.collect_rss(self.store, ["https://www.rbc.ru/rss"])

        self.assertEqual(len(result["added"]), 4)
        self.assertEqual(result["skipped_offtopic"], 0)


class KeywordRuleTests(unittest.TestCase):
    def test_currency_in_both_word_orders(self) -> None:
        self.assertIn("currency", keyword_channels("Рубль ослаб к юаню"))
        self.assertIn("currency", keyword_channels("Доллар подорожал до 95 рублей"))
        self.assertIn("currency", keyword_channels("Ослабление рубля ускорилось"))

    def test_verb_stali_is_not_steel(self) -> None:
        self.assertEqual(keyword_channels("Американцы заявили, что стали жить хуже"), [])
        self.assertIn("industry", keyword_channels("Выплавка стали в России снизилась на 5%"))
        self.assertIn("industry", keyword_channels("Правительство ввело экспортные пошлины на металлопрокат"))


if __name__ == "__main__":
    unittest.main()
