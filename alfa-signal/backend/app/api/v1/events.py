from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import UserContext, current_user, store_dependency
from app.db.store import AppStore
from app.modules.news.scheduler import get_scheduler
from app.modules.news.service import (
    OFFICIAL_SOURCES,
    collect_rss,
    configured_official_sources,
    configured_rss_urls,
    ingest_text,
    ingest_url,
    official_sources,
)
from app.modules.news.sources.article import ArticleFetchError, validate_public_url
from app.schemas.event import NewsEvent

router = APIRouter(prefix="/events", tags=["Events"])


class EventCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=500)
    text: str = Field(default="", max_length=50_000)
    url: Optional[str] = Field(default=None, max_length=2000)
    source: str = Field(default="manual", max_length=200)
    use_llm: bool = True
    # Компания, для которой прислана новость: тогда она видна только в её ленте.
    company_id: Optional[str] = Field(default=None, max_length=100)


class CollectRequest(BaseModel):
    rss_urls: list[str] = Field(default_factory=list, max_length=20)
    use_llm: bool = False
    limit_per_source: int = Field(default=30, ge=1, le=200)
    # Официальные источники (cbr, moex); не задано — из NEWS_OFFICIAL_SOURCES, [] — без них.
    official: list[str] | None = Field(default=None, max_length=len(OFFICIAL_SOURCES))


@router.get("")
def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    store: AppStore = Depends(store_dependency),
) -> dict:
    return {
        "items": store.list_events(limit=limit, offset=offset),
        "total": store.count_events(),
        "limit": limit,
        "offset": offset,
    }


@router.get("/{event_id}", response_model=NewsEvent)
def get_event(event_id: str, store: AppStore = Depends(store_dependency)) -> NewsEvent:
    event = store.get_event(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    return event


@router.post("", response_model=NewsEvent, status_code=201)
def create_event(
    body: EventCreate,
    store: AppStore = Depends(store_dependency),
    _: UserContext = Depends(current_user),
) -> NewsEvent:
    """Add a news item: by URL (the page is downloaded) or by pasted title and text."""
    try:
        if body.title:
            return ingest_text(
                store,
                title=body.title,
                text=body.text,
                url=body.url,
                source=body.source,
                use_llm=body.use_llm,
                submitted_by=body.company_id,
            )
        if body.url:
            return ingest_url(store, body.url, use_llm=body.use_llm, submitted_by=body.company_id)
    except ArticleFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise HTTPException(status_code=422, detail="Нужен url или title")


@router.post("/collect")
def collect_events(
    body: CollectRequest,
    store: AppStore = Depends(store_dependency),
    _: UserContext = Depends(current_user),
) -> dict:
    """Pull RSS feeds (from the body or NEWS_RSS_URLS) into the event store."""
    try:
        requested = [validate_public_url(url) for url in body.rss_urls]
    except ArticleFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    urls = requested or configured_rss_urls()
    official = configured_official_sources() if body.official is None else [
        name for name in body.official if name in OFFICIAL_SOURCES
    ]
    if not urls and not official:
        raise HTTPException(
            status_code=400, detail="Не заданы источники: rss_urls, NEWS_RSS_URLS или NEWS_OFFICIAL_SOURCES"
        )
    result = collect_rss(
        store,
        urls,
        use_llm=body.use_llm,
        limit_per_source=body.limit_per_source,
        extra_sources=official_sources(official, body.limit_per_source),
    )
    return {
        "added": len(result["added"]),
        "merged": len(result["merged"]),
        "skipped_known_urls": result["skipped_known_urls"],
        "skipped_old": result["skipped_old"],
        "skipped_offtopic": result["skipped_offtopic"],
        "skipped_clickbait": result["skipped_clickbait"],
        "sources": [{key: item.get(key) for key in ("name", "status", "last_items", "last_added", "last_error")} for item in result["sources"]],
        "items": result["added"],
    }


@router.post("/refresh", status_code=202)
def refresh_events(_: UserContext = Depends(current_user)) -> dict:
    """«Обновить ленту»: собрать RSS и заранее разобрать важное (в фоне, как плановый запуск)."""
    scheduler = get_scheduler()
    started = scheduler.run_in_background()
    return {"started": started, "scheduler": scheduler.describe()}
