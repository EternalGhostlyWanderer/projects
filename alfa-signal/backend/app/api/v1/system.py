from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import current_user, store_dependency
from app.db.store import ANALYSIS_VERSION, AppStore
from app.llm.config import get_settings
from app.llm.store import LLMStore
from app.modules.news import source_health
from app.modules.news.scheduler import get_scheduler
from app.research.index import load_chunks

router = APIRouter(prefix="/system", tags=["System"], dependencies=[Depends(current_user)])


@router.get("/status")
def status(store: AppStore = Depends(store_dependency)) -> dict[str, Any]:
    """Health of the moving parts and today's LLM usage — for the demo and quality monitoring."""
    try:
        settings = get_settings()
        llm: dict[str, Any] = {
            "configured": True,
            "models": {role: settings.model_for(role) for role in ("extract", "analyze", "verify", "vision")},
            "today": LLMStore(settings.state_db).daily_usage(),
            "daily_request_limit": settings.daily_request_limit,
            "daily_cost_limit": settings.daily_cost_limit,
        }
    except RuntimeError as exc:
        llm = {"configured": False, "error": str(exc)}

    return {
        "analysis_version": ANALYSIS_VERSION,
        "llm": llm,
        "events": store.count_events(),
        "merged_publications": store.count_event_aliases(),
        "client_requests": store.count_requests(),
        "hidden_events": store.count_hidden(),
        "bank_chunks": len(load_chunks()),
        "feedback": store.feedback_summary(),
        "scheduler": get_scheduler().describe(),
        "sources": {
            key: value
            for key, value in source_health.summarize(store.source_health()).items()
            if key != "items"
        },
    }


@router.get("/sources")
def sources(store: AppStore = Depends(store_dependency)) -> dict[str, Any]:
    """Здоровье источников новостей: последний запуск, успех, новые публикации, ошибка (критерий 08)."""
    return source_health.summarize(store.source_health())
