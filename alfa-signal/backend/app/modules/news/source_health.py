"""Health of news sources: last run, last success, last new publication, errors.

Каждый сбор записывает по источнику: сколько записей пришло, сколько из них новых, склеенных,
старых и не про бизнес, сколько длился запрос и какая была ошибка. Отсюда статус:
- ok — источник ответил, и новые публикации появлялись недавно;
- degraded — ответ есть, но битый (обрезанный XML, не JSON) или пустой у новостного источника;
- down — источник недоступен (таймаут, отказ соединения);
- stale — отвечает, но новых публикаций нет дольше NEWS_SOURCE_STALE_HOURS (по умолчанию 48 ч).
Источник данных (ставка и курсы ЦБ) без новых событий — норма: ставка меняется редко.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

STATUSES = ("ok", "degraded", "down", "stale", "unknown")
# Порядок в мониторинге: сначала то, что требует внимания.
SEVERITY = {"down": 0, "degraded": 1, "stale": 2, "unknown": 3, "ok": 4}


def stale_after() -> timedelta:
    try:
        return timedelta(hours=float(os.getenv("NEWS_SOURCE_STALE_HOURS", "") or 48))
    except ValueError:
        return timedelta(hours=48)


def source_key(source: Any) -> str:
    """Ключ источника: адрес ленты или имя официального источника."""
    return str(getattr(source, "url", None) or getattr(source, "name", "source"))


def run_status(*, error: Optional[str], items: int, kind: str) -> str:
    """Статус одного запуска (без учёта давности новых публикаций)."""
    if error:
        return "degraded" if error.startswith("format") or items else "down"
    if items == 0 and kind == "news":
        return "degraded"
    return "ok"


def _parse(moment: Optional[str]) -> Optional[datetime]:
    if not moment:
        return None
    try:
        value = datetime.fromisoformat(moment)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def current_status(record: dict[str, Any], now: Optional[datetime] = None) -> str:
    """Статус для мониторинга: результат последнего запуска плюс давность новых публикаций."""
    status = record.get("last_status") or "unknown"
    if status != "ok" or record.get("kind") != "news":
        return status
    now = now or datetime.now(timezone.utc)
    last_new = _parse(record.get("last_new_at")) or _parse(record.get("first_seen_at"))
    if last_new and now - last_new > stale_after():
        return "stale"
    return "ok"


def summarize(records: list[dict[str, Any]], now: Optional[datetime] = None) -> dict[str, Any]:
    items = [{**record, "status": current_status(record, now)} for record in records]
    counts = {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}
    return {
        "total": len(items),
        "counts": {status: count for status, count in counts.items() if count},
        "healthy": counts["ok"],
        "items": sorted(items, key=lambda item: (SEVERITY[item["status"]], item["name"])),
    }
