import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.db.store import AppStore
from app.modules.news import clustering, service
from app.modules.news.clustering import SameEvent, conflicts, find_duplicate, similarity
from app.modules.news.service import ingest_text, register_event
from app.schemas.event import NewsEvent

PAIRS = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "dedup_pairs.json"


def keywords_only(event, *, use_llm=True, llm=None):
    from app.modules.news.extraction import extract_event

    return extract_event(event, use_llm=False)


def event(data: dict, event_id: str) -> NewsEvent:
    return NewsEvent(event_id=event_id, url=f"https://{data['source']}/{event_id}", **data)


class ControlPairsTests(unittest.TestCase):
    """Контрольные пары: одна новость в разных изданиях склеивается, похожие разные события — нет."""

    def test_control_pairs(self) -> None:
        pairs = json.loads(PAIRS.read_text(encoding="utf-8"))["pairs"]
        for index, pair in enumerate(pairs):
            with self.subTest(pair["note"]):
                first, second = event(pair["a"], f"a{index}"), event(pair["b"], f"b{index}")
                merged = find_duplicate(second, [first]).event is not None
                self.assertEqual(merged, pair["same"])

    def test_conflicting_percent_blocks_even_identical_wording(self) -> None:
        a = event({"title": "Инфляция ускорилась до 6,8%", "source": "x.ru"}, "a")
        b = event({"title": "Инфляция ускорилась до 6,3%", "source": "y.ru"}, "b")

        self.assertGreater(similarity(a, b), 0.5)
        self.assertTrue(conflicts(a, b))
        self.assertIsNone(find_duplicate(b, [a]).event)

    def test_borderline_pair_asks_llm_only_when_allowed(self) -> None:
        a = event({"title": "Банки ужесточили проверку платежей в Китай", "source": "x.ru"}, "a")
        b = event({"title": "Проверки платежей в Китай стали строже для импортёров", "source": "y.ru"}, "b")
        score = similarity(a, b)
        self.assertTrue(clustering.ASK_LLM_THRESHOLD <= score < clustering.MERGE_THRESHOLD, score)

        self.assertIsNone(find_duplicate(b, [a], use_llm=False).event)
        with patch.object(clustering, "_ask_llm", return_value=SameEvent(same_event=True, reason="одно событие")):
            decision = find_duplicate(b, [a], use_llm=True)
        self.assertEqual(decision.method, "llm")


class StoreDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        patcher = patch.object(service, "extract_event", keywords_only)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.pair = json.loads(PAIRS.read_text(encoding="utf-8"))["pairs"][0]

    def ingest(self, data: dict, url: str) -> NewsEvent:
        return ingest_text(
            self.store,
            title=data["title"],
            text=data["summary"],
            url=url,
            source=data["source"],
            use_llm=False,
        )

    def test_second_outlet_becomes_source_of_first_event(self) -> None:
        first = self.ingest(self.pair["a"], "https://rbc.ru/cb-rate")
        second = self.ingest(self.pair["b"], "https://interfax.ru/cb-rate")

        self.assertEqual(second.event_id, first.event_id)
        self.assertEqual(self.store.count_events(), 1)
        self.assertEqual(self.store.count_event_aliases(), 1)
        stored = self.store.get_event(first.event_id)
        self.assertEqual([source.source for source in stored.sources], ["rbc.ru", "interfax.ru"])
        self.assertEqual(stored.sources[1].method, "similarity")

    def test_recollecting_the_same_url_does_not_duplicate(self) -> None:
        self.ingest(self.pair["a"], "https://rbc.ru/cb-rate")
        second = self.ingest(self.pair["b"], "https://interfax.ru/cb-rate")
        again = self.ingest(self.pair["b"], "https://interfax.ru/cb-rate?utm_source=tg")

        self.assertEqual(again.event_id, second.event_id)
        self.assertEqual(self.store.count_events(), 1)
        self.assertEqual(len(self.store.get_event(second.event_id).sources), 2)

    def test_alias_id_resolves_to_canonical_event(self) -> None:
        first = self.ingest(self.pair["a"], "https://rbc.ru/cb-rate")
        duplicate = NewsEvent(
            event_id="dup",
            url="https://tass.ru/cb-rate",
            title=self.pair["b"]["title"],
            summary=self.pair["b"]["summary"],
            source="tass.ru",
        )
        register_event(self.store, duplicate, use_llm=False)

        # Анализ и ссылки по id дубля ведут к каноническому событию — результаты не теряются.
        self.assertEqual(self.store.get_event("dup").event_id, first.event_id)

    def test_different_events_stay_separate(self) -> None:
        pairs = json.loads(PAIRS.read_text(encoding="utf-8"))["pairs"]
        different = next(pair for pair in pairs if pair["note"].startswith("одинаковый шаблон"))
        self.ingest(different["a"], "https://metaltorg.ru/severstal")
        self.ingest(different["b"], "https://metaltorg.ru/nlmk")

        self.assertEqual(self.store.count_events(), 2)
        self.assertEqual(self.store.count_event_aliases(), 0)


if __name__ == "__main__":
    unittest.main()
