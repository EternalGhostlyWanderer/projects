"""Periodic news collection and pre-analysis of the most important events.

Раз в NEWS_COLLECT_INTERVAL_MIN минут: собрать RSS (склейка дублей — clustering.py) и пересчитать ленты.
Предварительный анализ: когда пользователь открывает ленту, верхние PREANALYZE_PER_COMPANY (10) ещё не
разобранных событий разбираются агентом в фоне — по PREANALYZE_WORKERS (2) одновременно, сразу с блоком
«Что это значит для вас» для его роли. Лента отвечает сразу, карточки заполняются по мере готовности.
Ограничены суточным лимитом (PREANALYZE_DAILY_LIMIT) и бюджетом LLM.
"""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from app.db.store import AppStore, get_store
from app.modules.news import activity
from app.llm import BudgetExceededError
from app.llm.config import LLMConfigError
from app.modules.news.service import collect_rss, configured_official_sources, configured_rss_urls, official_sources
from app.modules.personalization.context import build_personalization_context
from app.modules.personalization.relevance import assess_relevance
from app.modules.personalization.scoring import MIN_FEED_SCORE

logger = logging.getLogger(__name__)

# Без PREANALYZE_COMPANY_IDS заранее разбираем важное для компаний активных пользователей.
MAX_ACTIVE_PREANALYZE = 5


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


@dataclass
class SchedulerConfig:
    # Сценарии обновления (docs/news-collection.md):
    # 1) по расписанию каждые interval_min минут — пока в сервисе есть активные сессии (mode=active)
    #    или всегда (mode=always); 0 — только вручную;
    # 2) при входе — если с последнего сбора прошло больше refresh_on_login_min минут;
    # 3) при открытии ленты и её перезапросе с открытой страницы (раз в 5 минут) — если с последнего
    #    сбора прошло больше refresh_on_open_min минут: данные не старше получаса, пока страница открыта;
    # 4) вручную — кнопка «Обновить ленту» (POST /events/refresh).
    interval_min: int = 30
    mode: str = "active"
    refresh_on_login_min: int = 30
    refresh_on_open_min: int = 30
    # Предварительный анализ верхних событий ленты для тех, кто её открыл (PREANALYZE_ACTIVE=0 — выключить).
    preanalyze_active: bool = True
    workers: int = 2
    use_llm: bool = False  # извлекать события через LLM (иначе — ключевые слова, бесплатно)
    company_ids: list[str] = field(default_factory=list)
    per_company: int = 10
    # Порог предварительного разбора = порог ленты: попало в выдачу — разбирается заранее.
    min_score: int = MIN_FEED_SCORE
    daily_limit: int = 150

    @classmethod
    def from_env(cls) -> "SchedulerConfig":
        return cls(
            interval_min=_int_env("NEWS_COLLECT_INTERVAL_MIN", 30),
            mode="always" if os.getenv("NEWS_COLLECT_MODE", "active").strip() == "always" else "active",
            refresh_on_login_min=_int_env("NEWS_REFRESH_ON_LOGIN_MIN", 30),
            refresh_on_open_min=_int_env("NEWS_REFRESH_ON_OPEN_MIN", 30),
            preanalyze_active=os.getenv("PREANALYZE_ACTIVE", "1") == "1",
            workers=max(1, min(4, _int_env("PREANALYZE_WORKERS", 2))),
            use_llm=os.getenv("NEWS_COLLECT_USE_LLM", "0") == "1",
            company_ids=[item.strip() for item in os.getenv("PREANALYZE_COMPANY_IDS", "").split(",") if item.strip()],
            per_company=_int_env("PREANALYZE_PER_COMPANY", 10),
            min_score=_int_env("PREANALYZE_MIN_SCORE", MIN_FEED_SCORE),
            daily_limit=_int_env("PREANALYZE_DAILY_LIMIT", 150),
        )


@dataclass
class SchedulerStatus:
    enabled: bool = False
    interval_min: int = 0
    running: bool = False
    last_run_at: Optional[str] = None
    last_result: dict[str, Any] = field(default_factory=dict)
    preanalyzed_today: int = 0
    day: str = ""
    mode: str = "active"
    last_trigger: Optional[str] = None
    last_skipped_at: Optional[str] = None
    last_skip_reason: Optional[str] = None


def _persist_article(store: AppStore, result: Any) -> None:
    """Текст статьи, загруженный агентом, — в событие (импорт здесь: orchestrator импортирует scheduler)."""
    from app.agents.orchestrator import persist_enriched_event

    persist_enriched_event(store, result)


def preanalyze(
    store: AppStore,
    config: SchedulerConfig,
    *,
    budget_left: int,
    run_agent: Callable[..., Any],
) -> dict[str, Any]:
    """Разобрать агентом самые важные ещё не разобранные события демо-компаний."""
    analyzed: list[dict[str, Any]] = []
    stopped: Optional[str] = None
    events = store.list_events(limit=200)
    for company_id in config.company_ids:
        if len(analyzed) >= budget_left or stopped:
            break
        user_data = store.get_user_data(company_id)
        context = build_personalization_context(company_id, user_data)
        if context is None:
            continue
        hidden = store.hidden_event_ids(company_id)
        scored = [
            (assess_relevance(context, event.model_dump(mode="json")), event)
            for event in events
            if event.visible_to(company_id)
            and event.event_id not in hidden
            and store.find_insight(company_id, event.event_id) is None
        ]
        # Заранее разбираем самое важное из свежего: порядок как в ленте (балл × свежесть).
        candidates = [
            (relevance["score"], event)
            for relevance, event in sorted(scored, key=lambda item: item[0]["rank"], reverse=True)
            if relevance["score"] >= config.min_score
        ]
        for score, event in candidates[: config.per_company]:
            if len(analyzed) >= budget_left:
                break
            try:
                result = run_agent(company_id, event, user_data=user_data)
            except (BudgetExceededError, LLMConfigError) as exc:
                stopped = str(exc)
                break
            _persist_article(store, result)
            if result.insight is not None:
                store.save_analysis(result.insight, result.trace)
                analyzed.append({"company_id": company_id, "event_id": event.event_id, "score": score})
    return {"analyzed": analyzed, "stopped": stopped}


class NewsScheduler:
    def __init__(
        self,
        config: Optional[SchedulerConfig] = None,
        store_factory: Callable[[], AppStore] = get_store,
    ) -> None:
        self.config = config or SchedulerConfig.from_env()
        self.store_factory = store_factory
        self.status = SchedulerStatus(
            enabled=self.config.interval_min > 0, interval_min=self.config.interval_min, mode=self.config.mode
        )
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Фоновые разборы ленты: компания → {"running", "pending": event_id}.
        self._jobs: dict[str, dict[str, Any]] = {}
        self._jobs_lock = threading.Lock()

    def _roll_day(self) -> None:
        today = date.today().isoformat()
        if self.status.day != today:
            self.status.day, self.status.preanalyzed_today = today, 0

    def preanalysis_state(self, company_id: str) -> dict[str, Any]:
        with self._jobs_lock:
            job = self._jobs.get(company_id)
            return {
                "running": bool(job and job["running"]),
                "pending": sorted(job["pending"]) if job else [],
                "done": list(job["done"]) if job else [],
            }

    def request_preanalysis(self, company_id: str, events: list, role: Optional[str] = None) -> dict[str, Any]:
        """Разобрать в фоне верхние события ленты, ещё не разобранные (порядок — как в ленте).

        Не ждёт результата: лента отвечает сразу. Повторный вызов, пока разбор идёт, ничего не запускает.
        """
        if not self.config.preanalyze_active:
            return {"running": False, "pending": [], "done": [], "enabled": False}
        with self._jobs_lock:
            job = self._jobs.get(company_id)
            if job and job["running"]:
                return {"running": True, "pending": sorted(job["pending"]), "done": list(job["done"]), "enabled": True}
            self._roll_day()
            budget = max(0, self.config.daily_limit - self.status.preanalyzed_today)
            todo = list(events[: self.config.per_company])[:budget]
            if not todo:
                return {"running": False, "pending": [], "done": [], "enabled": True}
            job = {"running": True, "pending": {event.event_id for event in todo}, "done": []}
            self._jobs[company_id] = job
        threading.Thread(
            target=self._run_job, args=(company_id, todo, role, job), name=f"preanalyze-{company_id}", daemon=True
        ).start()
        return {"running": True, "pending": sorted(job["pending"]), "done": [], "enabled": True}

    def _run_job(self, company_id: str, events: list, role: Optional[str], job: dict[str, Any]) -> None:
        from app.agents.orchestrator import run_agent
        from app.agents.role_view import build_role_view

        stop = threading.Event()
        store = self.store_factory()
        user_data = store.get_user_data(company_id)
        insights = []

        def analyze(event) -> None:
            try:
                if stop.is_set() or store.find_insight(company_id, event.event_id) is not None:
                    return
                result = run_agent(company_id, event, user_data=user_data)
                _persist_article(store, result)
                if result.insight is not None:
                    store.save_analysis(result.insight, result.trace)
                    insights.append(result.insight)
                    with self._jobs_lock:
                        self.status.preanalyzed_today += 1
                        job["done"].append(event.event_id)
            except (BudgetExceededError, LLMConfigError) as exc:
                stop.set()
                logger.warning("Предварительный анализ остановлен: %s", exc)
            except Exception:  # noqa: BLE001 — сбой одного разбора не останавливает остальные
                logger.exception("Предварительный анализ события %s не удался", event.event_id)
            finally:
                with self._jobs_lock:
                    job["pending"].discard(event.event_id)

        try:
            # Самые важные — первыми: с двумя потоками верхние две карточки готовы раньше остальных.
            with ThreadPoolExecutor(max_workers=self.config.workers) as pool:
                list(pool.map(analyze, events))
            # Ролевой блок — после разборов, чтобы не задерживать сами карточки.
            for insight in insights:
                if stop.is_set() or not role or store.get_role_view(insight.insight_id, role):
                    continue
                try:
                    view = build_role_view(insight, role)
                    store.save_role_view(insight.insight_id, role, view.model_dump(mode="json"))
                except Exception:  # noqa: BLE001
                    logger.exception("Ролевой блок для %s не подготовлен", insight.insight_id)
        finally:
            with self._jobs_lock:
                job["running"] = False

    def run_once(self, *, collect: bool = True, trigger: str = "manual") -> dict[str, Any]:
        """Один цикл: сбор RSS (если ленты заданы) и предварительный анализ в пределах лимита."""
        if not self._lock.acquire(blocking=False):
            return {"skipped": "уже выполняется"}
        self.status.running = True
        self.status.last_trigger = trigger
        try:
            from app.agents.orchestrator import run_agent

            store = self.store_factory()
            result: dict[str, Any] = {}
            urls, official = configured_rss_urls(), configured_official_sources()
            if collect and (urls or official):
                collected = collect_rss(
                    store, urls, use_llm=self.config.use_llm, extra_sources=official_sources(official)
                )
                result["collected"] = {
                    "added": len(collected["added"]),
                    "merged": len(collected["merged"]),
                    "skipped": "NEWS_RSS_URLS не заданы" if not urls else None,
                    "skipped_known_urls": collected["skipped_known_urls"],
                    "skipped_old": collected["skipped_old"],
                    "skipped_offtopic": collected["skipped_offtopic"],
                    "skipped_clickbait": collected["skipped_clickbait"],
                    "sources": {item["name"]: item["status"] for item in collected["sources"]},
                }
            elif collect:
                result["collected"] = {"skipped": "не заданы NEWS_RSS_URLS и NEWS_OFFICIAL_SOURCES"}

            today = date.today().isoformat()
            if self.status.day != today:
                self.status.day, self.status.preanalyzed_today = today, 0
            budget_left = max(0, self.config.daily_limit - self.status.preanalyzed_today)
            # Заранее разбираем важное для заданных компаний, а если они не заданы — для компаний,
            # чьи пользователи сейчас в сервисе: им лента нужна прямо сейчас.
            companies = self.config.company_ids or (
                activity.active_companies()[:MAX_ACTIVE_PREANALYZE] if self.config.preanalyze_active else []
            )
            config = replace(self.config, company_ids=companies)
            if companies and budget_left:
                pre = preanalyze(store, config, budget_left=budget_left, run_agent=run_agent)
                self.status.preanalyzed_today += len(pre["analyzed"])
                result["preanalyzed"] = pre
            else:
                result["preanalyzed"] = {
                    "analyzed": [],
                    "stopped": "лимит на сегодня исчерпан"
                    if companies
                    else "нет компаний для разбора: PREANALYZE_COMPANY_IDS не заданы (PREANALYZE_ACTIVE=1 — разбирать для активных пользователей)",
                }
            self.status.last_result = result
            return result
        except Exception as exc:  # noqa: BLE001 — сбой источника не должен останавливать сервер
            logger.exception("Обновление ленты не удалось")
            self.status.last_result = {"error": str(exc)}
            return self.status.last_result
        finally:
            self.status.last_run_at = datetime.now(timezone.utc).isoformat()
            self.status.running = False
            self._lock.release()

    def run_in_background(self, trigger: str = "manual") -> bool:
        if self.status.running:
            return False
        threading.Thread(
            target=self.run_once, kwargs={"trigger": trigger}, name="news-refresh", daemon=True
        ).start()
        return True

    def minutes_since_last_run(self) -> Optional[float]:
        if not self.status.last_run_at:
            return None
        last = datetime.fromisoformat(self.status.last_run_at)
        return (datetime.now(timezone.utc) - last).total_seconds() / 60

    def refresh_if_stale(self, max_age_min: Optional[int] = None, trigger: str = "login") -> str:
        """Сценарий «при входе»: обновить ленту, если данные старше max_age_min минут."""
        max_age = self.config.refresh_on_login_min if max_age_min is None else max_age_min
        if max_age <= 0:
            return "disabled"
        age = self.minutes_since_last_run()
        if age is not None and age < max_age:
            return "fresh"
        return "started" if self.run_in_background(trigger=trigger) else "running"

    def tick(self) -> dict[str, Any]:
        """Плановый запуск: в режиме active — только если кто-то пользуется сервисом."""
        if self.config.mode == "active" and not activity.active():
            self.status.last_skipped_at = datetime.now(timezone.utc).isoformat()
            self.status.last_skip_reason = "нет активных сессий"
            return {"skipped": self.status.last_skip_reason}
        return self.run_once(trigger="schedule")

    def start(self) -> None:
        if self.config.interval_min <= 0 or self._thread is not None:
            return

        def loop() -> None:
            while not self._stop.is_set():
                self.tick()
                self._stop.wait(self.config.interval_min * 60)

        self._thread = threading.Thread(target=loop, name="news-scheduler", daemon=True)
        self._thread.start()
        logger.info("Сбор новостей по расписанию: каждые %s мин", self.config.interval_min)

    def stop(self) -> None:
        self._stop.set()

    def describe(self) -> dict[str, Any]:
        return {
            **asdict(self.status),
            "active_sessions": len(activity.active()),
            "rss_sources": len(configured_rss_urls()),
            "official_sources": configured_official_sources(),
            "preanalyze_companies": len(self.config.company_ids),
            "daily_limit": self.config.daily_limit,
            # Предварительный разбор при открытии ленты (PREANALYZE_ACTIVE, по умолчанию включён).
            "preanalyze_active": self.config.preanalyze_active,
            "preanalyze_per_company": self.config.per_company,
            "preanalyze_min_score": self.config.min_score,
        }


_scheduler: Optional[NewsScheduler] = None


def get_scheduler() -> NewsScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = NewsScheduler()
    return _scheduler
