import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.db.store import AppStore
from app.modules.news import service
from app.modules.news.quality import is_clickbait, source_trust
from app.modules.news.sources.base import RawNewsItem
from app.modules.personalization.scoring import score_event
from tests.test_api import keywords_only
from tests.test_scoring import RATE, context


class ClickbaitTests(unittest.TestCase):
    def test_headlines_from_the_labeling_table(self) -> None:
        for title in (
            "Россиянам рассказали о средневековом параллельном импорте",
            "Постсоветской стране предрекли самое высокое повышение налогов в истории",
            "Россиянам дали неочевидные советы сохранить деньги на распродажах",
            "Россиянам назвали вероятный курс рубля к концу года",
        ):
            self.assertTrue(is_clickbait(title), title)

    def test_business_news_pass(self) -> None:
        for title in (
            "Банк России сохранил ключевую ставку на уровне 14%",
            "Аналитики предрекли рост ставок по вкладам",
            "Правительство ввело экспортные пошлины на металлопрокат",
            "Названы главные проинфляционные риски для российской экономики",
        ):
            self.assertFalse(is_clickbait(title), title)


class TrustTests(unittest.TestCase):
    def test_trust_by_domain_and_override(self) -> None:
        self.assertEqual(source_trust("https://lenta.ru/news/1"), 0.6)
        self.assertEqual(source_trust("https://www.interfax.ru/business/1"), 1.0)
        self.assertEqual(source_trust("https://www.cbr.ru/hd_base/", "Банк России"), 1.0)
        self.assertEqual(source_trust("https://example.com/x"), 1.0)
        with patch.dict("os.environ", {"NEWS_SOURCE_TRUST": "lenta.ru:0.3"}):
            self.assertEqual(source_trust("https://lenta.ru/news/1"), 0.3)

    def test_low_trust_source_scores_less_and_says_why(self) -> None:
        trusted = score_event(context(), {**RATE, "url": "https://www.interfax.ru/1"})
        low = score_event(context(), {**RATE, "url": "https://lenta.ru/news/1"})
        self.assertLess(low["score"], trusted["score"])
        self.assertIn("надёжность источника ×0.6", low["explanation"])
        self.assertNotIn("надёжность", trusted["explanation"])


class FeedSource:
    kind = "news"
    last_error = None

    def __init__(self, name: str, url: str, max_items: int = 50) -> None:
        self.name, self.url = name, url

    def fetch(self):
        now = datetime.now(timezone.utc)
        return [
            RawNewsItem(title="Россиянам рассказали о средневековом параллельном импорте", url="https://lenta.ru/1", source="lenta.ru", published_at=now),
            RawNewsItem(title="Банк России сохранил ключевую ставку на уровне 14% годовых", url="https://lenta.ru/2", source="lenta.ru", published_at=now),
        ]


class CollectTests(unittest.TestCase):
    def test_clickbait_is_skipped_at_collection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            store = AppStore(Path(folder) / "app.sqlite3")
            with patch.object(service, "RSSNewsSource", FeedSource), patch.object(service, "extract_event", side_effect=keywords_only):
                result = service.collect_rss(store, ["https://lenta.ru/rss"])
            self.assertEqual(result["skipped_clickbait"], 1)
            self.assertEqual([event.title for event in result["added"]], ["Банк России сохранил ключевую ставку на уровне 14% годовых"])
            self.assertEqual(result["sources"][0]["last_clickbait"], 1)


if __name__ == "__main__":
    unittest.main()
