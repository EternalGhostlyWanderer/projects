"""Компактная упаковка данных в запрос к LLM.

Бесплатные тарифы ограничивают и запросы, и токены. Здесь всё, что уходит в модель как JSON:
- без пустых значений (None, "", [], {}) — модель их не использует, а токены они тратят;
- без отступов и пробелов после разделителей;
- кириллица как есть, а не \\uXXXX (одна буква вместо шести символов);
- длинные тексты схлопнуты по пробелам и обрезаны по слову.
"""
import json
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

# Длина одного текстового фрагмента (доказательства, описания) в запросе, символов.
EVIDENCE_TEXT_LIMIT = 900

# Служебные поля инсайта: модели для ответа они не нужны.
INSIGHT_META_FIELDS = {
    "insight_id",
    "company_id",
    "event_id",
    "evidence",
    "trace_id",
    "model",
    "created_at",
    "schema_version",
    "quality_status",
    "quality_issues",
}


def clip(text: str, limit: Optional[int]) -> str:
    """Схлопнуть пробелы и обрезать по слову до limit символов."""
    text = " ".join(str(text).split())
    if not limit or len(text) <= limit:
        return text
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:")
    return f"{cut}…"


def prune(value: Any, max_text: Optional[int] = None) -> Any:
    """Рекурсивно убрать пустые значения и сократить строки."""
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            item = prune(item, max_text)
            if item is None or item == "" or item == [] or item == {}:
                continue
            result[key] = item
        return result
    if isinstance(value, (list, tuple, set)):
        items = [prune(item, max_text) for item in value]
        return [item for item in items if item is not None and item != "" and item != [] and item != {}]
    if isinstance(value, str):
        return clip(value, max_text)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def compact_json(value: Any, *, max_text: Optional[int] = None) -> str:
    """JSON для сообщения модели: без пустых полей и лишних пробелов."""
    return json.dumps(prune(value, max_text), ensure_ascii=False, separators=(",", ":"), default=str)


def insight_for_prompt(insight: BaseModel, *, exclude: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Содержательная часть инсайта без служебных полей."""
    return insight.model_dump(mode="json", exclude=INSIGHT_META_FIELDS | set(exclude))
