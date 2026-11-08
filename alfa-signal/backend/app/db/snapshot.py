"""Demo snapshot: events, saved analyses, traces and role views — to show the demo without an LLM key.

Ключ LLM нужен только для нового анализа. Чтобы демо работало и без него (ключ отключён, шлюз недоступен
без VPN), готовые разборы выгружаются из рабочей базы в JSON (scripts/export_demo.py) и загружаются
в чистую базу при запуске (scripts/seed_demo.py). Живой анализ по кнопке работает, если ключ есть.
"""
import json
from pathlib import Path
from typing import Any, Iterable

from app.agents.trace import AgentTrace
from app.ai.schemas import Insight
from app.db.store import AppStore
from app.schemas.event import NewsEvent

SNAPSHOT_VERSION = 1


def export_snapshot(store: AppStore, company_ids: Iterable[str], *, roles: Iterable[str] = ()) -> dict[str, Any]:
    company_ids = list(company_ids)
    insights = [insight for company_id in company_ids for insight in store.list_insights(company_id, limit=200)]
    event_ids = {insight.event_id for insight in insights}
    # Новости, присланные другими компаниями, в снимок не попадают.
    events = [
        event
        for event in store.list_events(limit=1000)
        if event.submitted_by is None or event.submitted_by in company_ids or event.event_id in event_ids
    ]
    traces = [store.get_trace(insight.trace_id) for insight in insights if insight.trace_id]
    role_views = [
        {"insight_id": insight.insight_id, "role": role, "data": view}
        for insight in insights
        for role in roles
        if (view := store.get_role_view(insight.insight_id, role))
    ]
    return {
        "version": SNAPSHOT_VERSION,
        "companies": company_ids,
        "events": [event.model_dump(mode="json") for event in events],
        "analyzed_events": sorted(event_ids),
        "insights": [insight.model_dump(mode="json") for insight in insights],
        "traces": [trace.model_dump(mode="json") for trace in traces if trace],
        "role_views": role_views,
        "user_data": {company_id: store.get_user_data(company_id) for company_id in company_ids},
    }


def import_snapshot(store: AppStore, snapshot: dict[str, Any]) -> dict[str, int]:
    for raw in snapshot.get("events", []):
        store.save_event(NewsEvent.model_validate(raw))
    traces = {raw["trace_id"]: AgentTrace.model_validate(raw) for raw in snapshot.get("traces", [])}
    for raw in snapshot.get("insights", []):
        insight = Insight.model_validate(raw)
        trace = traces.get(insight.trace_id or "")
        if trace is None:
            continue
        store.save_analysis(insight, trace)
    for item in snapshot.get("role_views", []):
        store.save_role_view(item["insight_id"], item["role"], item["data"])
    for company_id, data in (snapshot.get("user_data") or {}).items():
        if data:
            store.save_user_data(company_id, {key: value for key, value in data.items() if key != "updated_at"})
    return {
        "events": len(snapshot.get("events", [])),
        "insights": len(snapshot.get("insights", [])),
        "role_views": len(snapshot.get("role_views", [])),
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
