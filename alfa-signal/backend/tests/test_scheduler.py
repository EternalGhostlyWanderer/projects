import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api.deps import store_dependency
from app.api.deps import UserContext
from app.api.v1.feed import _request_preanalysis
from app.db.store import AppStore
from app.llm import BudgetExceededError
from app.llm.config import LLMConfigError
from app.main import app
from app.modules.companies import links, relationships, repository
from dataclasses import replace

from app.modules.news import activity
from app.modules.news import scheduler as scheduler_module
from app.modules.news import service
from app.modules.news.scheduler import NewsScheduler, SchedulerConfig, preanalyze
from tests.test_api import keywords_only
from tests.test_chat import make_insight

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"


class FakeAgent:
    """Вместо LLM: возвращает готовый инсайт для пары «компания × событие» и считает вызовы."""

    def __init__(self, fail_after: int | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_after = fail_after

    def __call__(self, company_id, event, *, user_data=None):
        if self.fail_after is not None and len(self.calls) >= self.fail_after:
            raise BudgetExceededError("Дневной лимит")
        self.calls.append((company_id, event.event_id))
        insight = make_insight().model_copy(
            update={"insight_id": f"i{len(self.calls)}", "company_id": company_id, "event_id": event.event_id}
        )
        return SimpleNamespace(insight=insight, trace=SimpleNamespace(trace_id=f"t{len(self.calls)}"))


class SchedulerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patches = [
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
            patch.object(service, "extract_event", keywords_only),
        ]
        for item in cls.patches:
            item.start()
        repository.clear_company_cache()
        relationships.clear_relationship_cache()
        links.clear_links_cache()

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls.patches:
            item.stop()
        repository.clear_company_cache()
        relationships.clear_relationship_cache()
        links.clear_links_cache()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        service.load_events_file(self.store, SYNTHETIC / "news.json", use_llm=False)
        # save_analysis ожидает настоящий журнал — подменяем сохранением одного инсайта.
        self.saved: list = []
        patcher = patch.object(self.store, "save_analysis", side_effect=lambda insight, trace: self.saved.append(insight))
        patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, **overrides) -> SchedulerConfig:
        return SchedulerConfig(company_ids=["SYN_001", "SYN_002"], per_company=2, min_score=30, **overrides)

    def test_preanalyzes_top_events_above_threshold(self) -> None:
        agent = FakeAgent()

        result = preanalyze(self.store, self.config(), budget_left=10, run_agent=agent)

        # SYN_001: два события с баллом ≥ 30; SYN_002 (розница): ни одного ≥ 30 — по клику.
        self.assertEqual([company for company, _ in agent.calls], ["SYN_001", "SYN_001"])
        self.assertTrue(all(item["score"] >= 30 for item in result["analyzed"]))
        self.assertIsNone(result["stopped"])

    def test_skips_analyzed_and_hidden_events(self) -> None:
        first = preanalyze(self.store, self.config(), budget_left=10, run_agent=FakeAgent())
        top_event = first["analyzed"][0]["event_id"]
        self.store.hide_event("SYN_001", first["analyzed"][1]["event_id"])

        with patch.object(self.store, "find_insight", side_effect=lambda c, e: object() if e == top_event else None):
            agent = FakeAgent()
            preanalyze(self.store, self.config(), budget_left=10, run_agent=agent)

        analyzed_again = {event for _, event in agent.calls}
        self.assertNotIn(top_event, analyzed_again)
        self.assertNotIn(first["analyzed"][1]["event_id"], analyzed_again)

    def test_daily_limit_and_budget_stop(self) -> None:
        limited = preanalyze(self.store, self.config(), budget_left=1, run_agent=FakeAgent())
        self.assertEqual(len(limited["analyzed"]), 1)

        stopped = preanalyze(self.store, self.config(), budget_left=10, run_agent=FakeAgent(fail_after=1))
        self.assertEqual(len(stopped["analyzed"]), 1)
        self.assertIn("лимит", stopped["stopped"])

    def test_feed_does_not_start_preanalysis_without_llm_key(self) -> None:
        scheduler = NewsScheduler(self.config(), store_factory=lambda: self.store)
        event = self.store.list_events(limit=1)[0]
        items = [{"event": event, "insight": None, "relevance": {"score": 100}}]

        with patch("app.api.v1.feed.get_scheduler", return_value=scheduler), patch(
            "app.api.v1.feed.get_settings", side_effect=LLMConfigError("missing")
        ), patch.object(scheduler, "request_preanalysis") as request:
            result = _request_preanalysis("SYN_001", items, UserContext(role="cfo"))

        request.assert_not_called()
        self.assertEqual(result["reason"], "llm_not_configured")
        self.assertFalse(result["running"])

    def test_run_once_counts_daily_usage_and_reports_missing_rss(self) -> None:
        scheduler = NewsScheduler(self.config(daily_limit=3), store_factory=lambda: self.store)
        with patch("app.agents.orchestrator.run_agent", FakeAgent()), patch.object(
            scheduler_module, "configured_rss_urls", return_value=[]
        ):
            first = scheduler.run_once()
            scheduler.run_once()
            third = scheduler.run_once()

        self.assertIn("NEWS_RSS_URLS", first["collected"]["skipped"])
        # Суточный лимит 3: два разбора в первом цикле, один во втором, дальше — стоп.
        self.assertEqual(scheduler.status.preanalyzed_today, 3)
        self.assertEqual(third["preanalyzed"]["analyzed"], [])
        self.assertIn("лимит", third["preanalyzed"]["stopped"])
        self.assertFalse(scheduler.status.running)
        self.assertIsNotNone(scheduler.status.last_run_at)

    def test_defaults_every_30_minutes_while_active(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            config = SchedulerConfig.from_env()
        self.assertEqual((config.interval_min, config.mode, config.refresh_on_login_min), (30, "active", 30))
        with patch.dict("os.environ", {"NEWS_COLLECT_INTERVAL_MIN": "0"}, clear=True):
            self.assertFalse(NewsScheduler(SchedulerConfig.from_env()).status.enabled)

    def test_tick_skips_without_active_sessions(self) -> None:
        activity.clear()
        self.addCleanup(activity.clear)
        scheduler = NewsScheduler(self.config(), store_factory=lambda: self.store)
        with patch.object(scheduler, "run_once", return_value={"ok": True}) as run:
            self.assertEqual(scheduler.tick(), {"skipped": "нет активных сессий"})
            activity.touch("SYN_001", "demo")
            scheduler.tick()
        run.assert_called_once_with(trigger="schedule")
        always = NewsScheduler(replace(self.config(), mode="always"), store_factory=lambda: self.store)
        activity.clear()
        with patch.object(always, "run_once", return_value={}) as run:
            always.tick()
        run.assert_called_once()

    def test_refresh_on_login_only_when_stale(self) -> None:
        scheduler = NewsScheduler(replace(self.config(), refresh_on_login_min=30), store_factory=lambda: self.store)
        with patch.object(scheduler, "run_in_background", return_value=True) as background:
            self.assertEqual(scheduler.refresh_if_stale(), "started")  # ещё ни разу не собирали
            scheduler.status.last_run_at = datetime.now(timezone.utc).isoformat()
            self.assertEqual(scheduler.refresh_if_stale(), "fresh")
            scheduler.status.last_run_at = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
            self.assertEqual(scheduler.refresh_if_stale(), "started")
        self.assertEqual(background.call_count, 2)
        self.assertEqual(scheduler.refresh_if_stale(max_age_min=0), "disabled")

    def test_active_users_companies_are_preanalyzed(self) -> None:
        activity.clear()
        self.addCleanup(activity.clear)
        activity.touch("SYN_001", "demo")
        idle = NewsScheduler(
            replace(self.config(), company_ids=[], preanalyze_active=False), store_factory=lambda: self.store
        )
        with patch("app.agents.orchestrator.run_agent", FakeAgent()) as nobody, patch.object(
            scheduler_module, "configured_rss_urls", return_value=[]
        ):
            idle.run_once()
        self.assertEqual(nobody.calls, [])  # PREANALYZE_ACTIVE=0 — платный разбор не запускается
        scheduler = NewsScheduler(
            replace(self.config(), company_ids=[], preanalyze_active=True), store_factory=lambda: self.store
        )
        agent = FakeAgent()
        with patch("app.agents.orchestrator.run_agent", agent), patch.object(
            scheduler_module, "configured_rss_urls", return_value=[]
        ):
            scheduler.run_once()
        self.assertTrue(agent.calls)
        self.assertEqual({company for company, _ in agent.calls}, {"SYN_001"})


class DigestApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        app.dependency_overrides[store_dependency] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        for patcher in (
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
            patch.object(service, "extract_event", keywords_only),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        repository.clear_company_cache()
        relationships.clear_relationship_cache()
        links.clear_links_cache()
        self.addCleanup(repository.clear_company_cache)

    def ingest(self, title: str, text: str, hours_ago: int) -> None:
        service.ingest_text(
            self.store,
            title=title,
            text=text,
            url=f"https://example.com/{abs(hash(title))}",
            published_at=datetime.now(timezone.utc) - timedelta(hours=hours_ago),
            use_llm=False,
        )

    def test_digest_keeps_period_and_order(self) -> None:
        self.ingest("Банк России сохранил ключевую ставку на уровне 14%", "Ставка 14% годовых.", hours_ago=2)
        self.ingest("Правительство ввело экспортные пошлины на металлопрокат", "Пошлина на прокат.", hours_ago=5)
        self.ingest("ЦБ снизил ключевую ставку до 15%", "Решение по ставке.", hours_ago=24 * 5)

        day = self.client.get("/api/v1/feed/digest", params={"company_id": "SYN_001", "hours": 24}).json()
        week = self.client.get("/api/v1/feed/digest", params={"company_id": "SYN_001", "hours": 24 * 7}).json()

        self.assertEqual(day["total"], 2)
        scores = [item["relevance"]["score"] for item in day["items"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(week["total"], 3)

    def test_refresh_endpoint_reports_scheduler(self) -> None:
        with patch.object(scheduler_module.NewsScheduler, "run_in_background", return_value=True):
            response = self.client.post("/api/v1/events/refresh")

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.json()["started"])
        self.assertIn("scheduler", self.client.get("/api/v1/system/status").json())


if __name__ == "__main__":
    unittest.main()


class DemoLoginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)

    def test_default_demo_user(self) -> None:
        with patch.dict("os.environ", {"DEMO_USERS": ""}):
            ok = self.client.post("/api/v1/auth/login", json={"login": "demo", "password": "alfa-signal"})
            bad = self.client.post("/api/v1/auth/login", json={"login": "demo", "password": "wrong"})

        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["companies"], [])
        self.assertEqual(bad.status_code, 401)

    def test_configured_users_with_companies(self) -> None:
        env = {"DEMO_USERS": "cfo:secret:U_1|U_2;owner:pw:"}
        with patch.dict("os.environ", env):
            response = self.client.post("/api/v1/auth/login", json={"login": "cfo", "password": "secret"})
            unknown = self.client.post("/api/v1/auth/login", json={"login": "demo", "password": "alfa-signal"})

        self.assertEqual(response.json()["companies"], ["U_1", "U_2"])
        self.assertEqual(unknown.status_code, 401)


class FeedPreanalysisTests(unittest.TestCase):
    """Фоновый разбор верхних событий ленты при открытии: быстро, параллельно, без повторов."""

    def setUp(self) -> None:
        import threading
        import time

        self.time = time
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        self.saved: list = []
        patcher = patch.object(self.store, "save_analysis", side_effect=lambda insight, trace: self.saved.append(insight))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.running, self.peak = 0, 0
        self.lock = threading.Lock()

    def events(self, count: int):
        return [SimpleNamespace(event_id=f"e{index}") for index in range(count)]

    def agent(self, company_id, event, *, user_data=None):
        with self.lock:
            self.running += 1
            self.peak = max(self.peak, self.running)
        self.time.sleep(0.05)
        with self.lock:
            self.running -= 1
        insight = make_insight().model_copy(update={"insight_id": f"i-{event.event_id}", "event_id": event.event_id})
        return SimpleNamespace(insight=insight, trace=SimpleNamespace(trace_id="t"))

    def wait(self, scheduler, company_id="SYN_001"):
        for _ in range(200):
            if not scheduler.preanalysis_state(company_id)["running"]:
                return
            self.time.sleep(0.02)
        self.fail("фоновый разбор не завершился")

    def scheduler(self, **overrides):
        options = {"preanalyze_active": True, "per_company": 5, "workers": 2, "daily_limit": 40, **overrides}
        config = SchedulerConfig(**options)
        return NewsScheduler(config, store_factory=lambda: self.store)

    def test_top_five_in_two_threads_with_role_view(self) -> None:
        scheduler = self.scheduler()
        role_views = []
        with patch("app.agents.orchestrator.run_agent", self.agent), patch(
            "app.agents.role_view.build_role_view", side_effect=lambda insight, role: role_views.append(role) or SimpleNamespace(model_dump=lambda mode: {})
        ):
            state = scheduler.request_preanalysis("SYN_001", self.events(8), role="cfo")
            again = scheduler.request_preanalysis("SYN_001", self.events(8), role="cfo")
            self.wait(scheduler)

        self.assertEqual(state["pending"], ["e0", "e1", "e2", "e3", "e4"])
        self.assertTrue(again["running"])  # второй запрос не запускает разбор заново
        self.assertEqual(len(self.saved), 5)
        self.assertEqual(self.peak, 2)
        self.assertEqual(role_views, ["cfo"] * 5)
        self.assertEqual(scheduler.status.preanalyzed_today, 5)
        self.assertEqual(scheduler.preanalysis_state("SYN_001")["pending"], [])

    def test_disabled_limit_and_budget(self) -> None:
        self.assertFalse(self.scheduler(preanalyze_active=False).request_preanalysis("SYN_001", self.events(3))["running"])

        limited = self.scheduler(daily_limit=2)
        with patch("app.agents.orchestrator.run_agent", self.agent):
            state = limited.request_preanalysis("SYN_001", self.events(5))
            self.wait(limited)
        self.assertEqual(len(state["pending"]), 2)

        def broke(*args, **kwargs):
            raise BudgetExceededError("Дневной лимит")

        broken = self.scheduler()
        with patch("app.agents.orchestrator.run_agent", broke):
            broken.request_preanalysis("SYN_002", self.events(5))
            self.wait(broken, "SYN_002")
        self.assertEqual(broken.status.preanalyzed_today, 0)
