"""Helpers to pull JSON out of model output and describe it to the model."""
import json
import re
from typing import Any

from pydantic import BaseModel, ValidationError


def extract_json_text(content: str) -> str:
    """Strip <think> blocks, ```json fences and text around the outermost JSON object."""
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start == -1:
        return text
    # Первый целый JSON-объект: модель иногда дописывает после него пояснение или второй объект
    # («trailing characters») — из-за этого не стоит переспрашивать её и тратить лимит.
    try:
        _, end = json.JSONDecoder().raw_decode(text, start)
        return text[start:end]
    except json.JSONDecodeError:
        end = text.rfind("}")
        return text[start : end + 1] if end > start else text[start:]


def drop_extra_fields(data: Any, exc: ValidationError) -> bool:
    """Убрать поля, которых нет в схеме («Extra inputs are not permitted»), если других ошибок нет.

    Лишнее поле (например, basis у сценария) смысла ответа не меняет, а повторный запрос к модели
    тратит дневной лимит бесплатного тарифа. Возвращает True, если что-то убрано.
    """
    errors = exc.errors(include_url=False)
    if not errors or any(error["type"] != "extra_forbidden" for error in errors):
        return False
    for error in errors:
        *parents, key = error["loc"]
        node = data
        for part in parents:
            node = node[part]
        if isinstance(node, dict):
            node.pop(key, None)
    return True


def format_validation_error(exc: ValidationError) -> list[str]:
    messages: list[str] = []
    for error in exc.errors(include_url=False):
        path = ".".join(str(part) for part in error["loc"]) or "$"
        messages.append(f"{path}: {error['msg']}")
    return messages


def _strip_titles(node: Any) -> Any:
    """Убрать автоматические "title" из JSON Schema: pydantic дублирует в них имя каждого поля.

    Строковый title — аннотация схемы; поле модели с именем title (словарь в properties) остаётся.
    """
    if isinstance(node, dict):
        return {
            key: _strip_titles(value)
            for key, value in node.items()
            if not (key == "title" and isinstance(value, str))
        }
    if isinstance(node, list):
        return [_strip_titles(item) for item in node]
    return node


def schema_for_prompt(model: type[BaseModel]) -> str:
    """Compact JSON Schema of the expected answer for the system prompt."""
    schema: dict[str, Any] = _strip_titles(model.model_json_schema())
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
