import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.deps import store_dependency
from app.db.store import AppStore
from app.main import app
from app.modules.news import service, source_health
from app.modules.news.sources.base import RawNewsItem
from tests.test_api import keywords_only


class Source:
    """Источник без сети: заданные записи и ошибка."""

    def __init__(self, name, items=(), error=None, kind="news", raises=False) -> None:
        self.name, self.url, self.kind = name, f"https://{name}/rss", kind
        self.items, self.error, self.raises = list(items), error, raises
        self.last_error = None

    def fetch(self):
        if self.raises:
            raise RuntimeError("connection reset")
        self.last_error = self.error
        return self.items


def news(title: str, number: int) -> RawNewsItem:
    return RawNewsItem(
        title=title, url=f"https://site.ru/{number}", source="site", published_at=datetime.now(timezone.utc)
    )


class SourceHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        patcher = patch.object(service, "extract_event", side_effect=keywords_only)
        patcher.start()
        self.addCleanup(patcher.stop)

    def collect(self, *sources):
        return {item["name"]: item for item in service.collect_rss(self.store, [], extra_sources=sources)["sources"]}

    def test_statuses_per_source(self) -> None:
        health = self.collect(
            Source("good.ru", [news("Банк России сохранил ключевую ставку на уровне 14%", 1)]),
            Source("moex.com", error="format: no element found: line 55542"),
            Source("government.ru", error="network: timed out"),
            Source("crash.ru", raises=True),
            Source("cbr", kind="data"),
        )

        self.assertEqual(health["good.ru"]["status"], "ok")
        self.assertEqual(health["good.ru"]["last_added"], 1)
        self.assertEqual(health["moex.com"]["status"], "degraded")
        self.assertEqual(health["government.ru"]["status"], "down")
        self.assertIn("connection reset", health["crash.ru"]["last_error"])
        # Источник данных без новых событий — норма.
        self.assertEqual(health["cbr"]["status"], "ok")

    def test_history_counts_runs_failures_and_last_success(self) -> None:
        flaky = Source("flaky.ru", [news("Рубль ослаб к юаню", 2)])
        self.collect(flaky)
        flaky.items, flaky.error = [], "network: timed out"
        record = self.collect(flaky)["flaky.ru"]

        self.assertEqual(record["runs"], 2)
        self.assertEqual(record["failures"], 1)
        self.assertEqual(record["status"], "down")
        self.assertIsNotNone(record["last_ok_at"])
        self.assertIsNotNone(record["last_new_at"])

    def test_stale_when_no_new_publications_for_long(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        record = {"name": "s", "kind": "news", "last_status": "ok", "last_new_at": old}
        self.assertEqual(source_health.current_status(record), "stale")
        self.assertEqual(source_health.current_status({**record, "kind": "data"}), "ok")
        with patch.dict("os.environ", {"NEWS_SOURCE_STALE_HOURS": "100"}):
            self.assertEqual(source_health.current_status(record), "ok")

    def test_api_lists_problems_first(self) -> None:
        self.collect(Source("good.ru", [news("Инфляция ускорилась до 6,1%", 3)]), Source("dead.ru", error="network: x"))
        app.dependency_overrides[store_dependency] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)

        body = client.get("/api/v1/system/sources").json()
        self.assertEqual([item["status"] for item in body["items"]], ["down", "ok"])
        self.assertEqual(client.get("/api/v1/system/status").json()["sources"]["counts"], {"ok": 1, "down": 1})


if __name__ == "__main__":
    unittest.main()


class ActivityTests(unittest.TestCase):
    def test_window_and_middleware(self) -> None:
        from app.modules.news import activity

        activity.clear()
        self.addCleanup(activity.clear)
        activity.touch("SYN_001", "demo", now=0)
        activity.touch("SYN_002", None, now=1000)
        with patch.dict("os.environ", {"NEWS_ACTIVE_WINDOW_MIN": "30"}):
            self.assertEqual(activity.active_companies(now=1500), ["SYN_001", "SYN_002"])
            self.assertEqual(activity.active_companies(now=1801 + 1000), [])
        TestClient(app).get("/api/v1/feed", params={"company_id": "SYN_404"}, headers={"X-User-Id": "u"})
        self.assertIn(("SYN_404", "u"), activity.active())
