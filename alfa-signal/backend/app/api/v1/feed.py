from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field

from app.api.deps import UserContext, check_user_company, current_user, require_company, store_dependency
from app.db.store import AppStore
from app.llm.config import LLMConfigError, get_settings
from app.modules.news.scheduler import get_scheduler
from app.modules.personalization.context import build_personalization_context
from app.modules.personalization.relevance import assess_relevance
from app.modules.news.clustering import similarity
from app.modules.personalization.scoring import MIN_FEED_SCORE, feed_freshness
from app.schemas.event import NewsEvent

router = APIRouter(prefix="/feed", tags=["Feed"])

FEED_SCAN_LIMIT = 300
# Сюжет: публикации об одном событии, которые не дубли (решение ЦБ, комментарий Набиуллиной,
# реакция Минфина). В ленте — одна карточка сюжета, остальные под ней, чтобы топ не состоял
# из пяти публикаций об одном заседании.
STORY_WINDOW = timedelta(hours=72)
STORY_SIMILARITY = 0.3
MAX_RELATED = 5


def _same_story(leader: NewsEvent, item: NewsEvent) -> bool:
    if not leader.event_type or leader.event_type == "other" or leader.event_type != item.event_type:
        return False
    if abs(_event_time(leader) - _event_time(item)) > STORY_WINDOW:
        return False
    # Решение по ставке — одно на всех: всё про ключевую ставку Банка России за 72 часа — один сюжет.
    if leader.event_type == "monetary_policy":
        return not leader.entities.countries and not item.entities.countries
    return similarity(leader, item) >= STORY_SIMILARITY


def group_stories(items: list[dict]) -> list[dict]:
    """Оставить первую (самую важную) карточку сюжета, остальные — в related."""
    leaders: list[dict] = []
    for item in items:
        leader = next((lead for lead in leaders if _same_story(lead["event"], item["event"])), None)
        if leader is None:
            leaders.append({**item, "related": [], "related_count": 0})
            continue
        leader["related_count"] += 1
        if len(leader["related"]) < MAX_RELATED:
            event = item["event"]
            leader["related"].append(
                {
                    "event_id": event.event_id,
                    "title": event.title,
                    "source": event.source,
                    "url": event.url,
                    "published_at": event.published_at,
                    "score": item["relevance"]["score"],
                }
            )
    return leaders


def _newest_publication(events: list[NewsEvent]) -> datetime:
    """От этой даты лента считает возраст: самая новая публикация, но не позже «сейчас»."""
    now = datetime.now(timezone.utc)
    dates = [
        (event.published_at if event.published_at.tzinfo else event.published_at.replace(tzinfo=timezone.utc))
        for event in events
        if event.published_at
    ]
    return min(now, max(dates)) if dates else now


def _ranked_items(
    store: AppStore,
    company_id: str,
    *,
    only_relevant: bool,
    include_hidden: bool,
    user: Optional[UserContext] = None,
) -> list[dict]:
    """Лента компании глазами пользователя: его роль меняет порядок, скрытое — только его."""
    user = user or UserContext()
    context = build_personalization_context(company_id, store.get_user_data(company_id)) or {}
    insights = store.insight_ids_by_event(company_id)
    hidden = store.hidden_event_ids(company_id, user.user_id)

    events = store.list_events(limit=FEED_SCAN_LIMIT)
    reference = _newest_publication(events)
    items = []
    for event in events:
        if not event.visible_to(company_id) and event.event_id not in insights:
            continue  # новость, присланная другой компанией
        if event.event_id in hidden and not include_hidden:
            continue
        relevance = assess_relevance(context, event.model_dump(mode="json"), role=user.role)
        fresh = feed_freshness(relevance["score"], event.published_at, reference)
        relevance["freshness"], relevance["rank"] = fresh, round(relevance["score"] * fresh["factor"], 2)
        # Ниже порога остаются общие события роли и уже разобранные: готовый разбор не должен пропадать.
        below = relevance["score"] < MIN_FEED_SCORE and not relevance.get("role_universal")
        if only_relevant and below and event.event_id not in insights:
            continue
        insight = insights.get(event.event_id)
        items.append(
            {
                "event": event,
                "relevance": relevance,
                "hidden": event.event_id in hidden,
                "insight": (
                    {
                        "insight_id": insight.insight_id,
                        "kind": insight.kind,
                        "score": insight.relevance.score,
                        "level": insight.relevance.level,
                        "primary_effect": insight.primary_effect.text,
                        "quality_status": insight.quality_status,
                        "risk_count": len(insight.risks),
                        "opportunity_count": len(insight.opportunities),
                    }
                    if insight
                    else None
                ),
            }
        )

    # Балл релевантности с учётом свежести: вчерашнее важное выше месячного; при равенстве — свежее.
    items.sort(
        key=lambda item: (
            item["relevance"]["rank"],
            item["relevance"]["score"],
            item["event"].published_at.isoformat() if item["event"].published_at else "",
        ),
        reverse=True,
    )
    return items


@router.get("")
def company_feed(
    company_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    only_relevant: bool = True,
    include_hidden: bool = False,
    group: bool = Query(default=True, description="Публикации одного сюжета — под одной карточкой"),
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    """Personal ranking of stored events by the explainable 0–100 score (no LLM); attaches saved insights."""
    require_company(company_id, x_company_id)
    check_user_company(company_id, user)
    # Открытие страницы и периодический перезапрос ленты: если новости старше
    # NEWS_REFRESH_ON_OPEN_MIN (30) минут, сбор запускается в фоне, ответ его не ждёт.
    refresh = get_scheduler().refresh_if_stale(get_scheduler().config.refresh_on_open_min, trigger="open")
    items = _ranked_items(store, company_id, only_relevant=only_relevant, include_hidden=include_hidden, user=user)
    if group:
        items = group_stories(items)
    preanalysis = _request_preanalysis(company_id, items, user)
    pending = set(preanalysis["pending"])
    for item in items[:limit]:
        item["preparing"] = item["event"].event_id in pending
    return {
        "company_id": company_id,
        "user_id": user.user_id or None,
        "role": user.role,
        "items": items[:limit],
        "total": len(items),
        "preanalysis": preanalysis,
        "refresh": refresh,
    }


def _request_preanalysis(company_id: str, items: list[dict], user: UserContext) -> dict[str, Any]:
    """Верхние события ленты без разбора — в фоновый разбор (scheduler.request_preanalysis); ответ не ждёт."""
    scheduler = get_scheduler()
    if scheduler.config.preanalyze_active:
        try:
            get_settings()
        except LLMConfigError:
            return {
                "running": False,
                "pending": [],
                "done": [],
                "enabled": False,
                "reason": "llm_not_configured",
            }
    top = items[: scheduler.config.per_company]
    events = [
        item["event"]
        for item in top
        if item.get("insight") is None and item["relevance"]["score"] >= scheduler.config.min_score
    ]
    return scheduler.request_preanalysis(company_id, events, user.role)


@router.get("/digest")
def company_digest(
    company_id: str,
    hours: int = Query(default=24, ge=1, le=24 * 31),
    limit: int = Query(default=3, ge=1, le=10),
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    """Сводка: главные события за период (вебинар, вопрос 60 — дневная или недельная сводка)."""
    require_company(company_id, x_company_id)
    check_user_company(company_id, user)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    items = group_stories(
        [
            item
            for item in _ranked_items(store, company_id, only_relevant=True, include_hidden=False, user=user)
            if _event_time(item["event"]) >= since
        ]
    )
    return {
        "company_id": company_id,
        "role": user.role,
        "since": since.isoformat(),
        "hours": hours,
        "total": len(items),
        "items": items[:limit],
    }


def _event_time(event) -> datetime:
    moment = event.published_at or datetime.now(timezone.utc)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class HideRequest(BaseModel):
    company_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    hidden: bool = True


@router.post("/hidden", status_code=204)
def hide_event(
    body: HideRequest,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> None:
    """Скрыть событие из своей ленты (или вернуть: hidden=false). Коллеги по компании его видят.

    Это тоже сигнал качества ленты.
    """
    require_company(body.company_id, x_company_id)
    check_user_company(body.company_id, user)
    if body.hidden:
        store.hide_event(body.company_id, body.event_id, user.user_id)
    else:
        store.unhide_event(body.company_id, body.event_id, user.user_id)
