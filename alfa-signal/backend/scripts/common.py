"""Shared configuration helpers for the local model-test scripts."""
from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
ENV_FILE = BACKEND_DIR / ".env"
SCHEMA_PATH = PROJECT_ROOT / "docs" / "contracts" / "business_analysis.schema.json"

# Read backend/.env explicitly so commands work from the project root or backend.
load_dotenv(ENV_FILE, override=False)

DEFAULT_BASE_URL = "https://changellenge.up.railway.app/v1"
DEFAULT_MODEL = "qwen/qwen3.6-35b-a3b"

# Разные шлюзы по-разному выключают рассуждения. Какой стиль работает у вас,
# показывает `python backend\scripts\test_connection.py --try-all`.
THINK_OFF_STYLES: dict[str, dict] = {
    "openrouter": {"reasoning": {"enabled": False}},
    "effort": {"reasoning": {"effort": "none"}},
    "qwen": {"chat_template_kwargs": {"enable_thinking": False}},
    "flat": {"enable_thinking": False},
}
THINK_STYLE_CHOICES = ["none", *THINK_OFF_STYLES]


def get_config() -> tuple[str, str, str]:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    base_url = os.getenv("LLM_BASE_URL", DEFAULT_BASE_URL).strip()
    model = os.getenv("LLM_MODEL", DEFAULT_MODEL).strip()

    if not api_key or api_key == "PASTE_TEAM_KEY_HERE":
        raise RuntimeError(
            "API-ключ не настроен. Скопируйте backend/.env.example "
            "в backend/.env и задайте LLM_API_KEY."
        )
    if not base_url:
        raise RuntimeError("LLM_BASE_URL пустой.")
    if not model:
        raise RuntimeError("LLM_MODEL пустой.")

    return api_key, base_url, model


def make_client() -> tuple[OpenAI, str]:
    api_key, base_url, model = get_config()
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=120.0,  # запросы с рассуждениями идут 30-60 с
        max_retries=0,
    )
    return client, model


def safe_error(exc: Exception) -> str:
    """Return a readable error while redacting the configured API key."""
    message = f"{type(exc).__name__}: {exc}"
    key = os.getenv("LLM_API_KEY", "")
    if key:
        message = message.replace(key, "[REDACTED_API_KEY]")
    return message


def think_off_body(style: str | None) -> dict | None:
    """extra_body для отключения рассуждений; None, если стиль 'none'."""
    if not style or style == "none":
        return None
    return copy.deepcopy(THINK_OFF_STYLES[style])


def usage_summary(response) -> dict:
    """Компактная сводка usage: токены, рассуждения, стоимость (если шлюз вернул)."""
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    data = usage.model_dump()
    details = data.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": data.get("prompt_tokens"),
        "completion_tokens": data.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": data.get("cost"),
    }


# ---------- JSON Schema ----------

def load_schema(path: Path = SCHEMA_PATH) -> dict:
    from jsonschema import Draft202012Validator

    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return schema


def format_validation_errors(validator, payload: object) -> list[str]:
    errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
    messages: list[str] = []
    for error in errors:
        path = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{path}: {error.message}")
    return messages


def extract_json_text(content: str) -> str:
    """Strip <think> blocks, ```json fences and text around the outermost JSON object."""
    text = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        text = text[start : end + 1]
    return text


def build_example(schema: dict) -> object:
    """Собирает пример формы ответа из схемы: только обязательные поля, enum -> первое значение."""

    def resolve(node: dict) -> dict:
        ref = node.get("$ref")
        if ref and ref.startswith("#/"):
            target: object = schema
            for part in ref[2:].split("/"):
                target = target[part]  # type: ignore[index]
            return resolve(target)  # type: ignore[arg-type]
        return node

    def build(node: dict, depth: int = 0) -> object:
        node = resolve(node)
        if depth > 8:
            return None
        if "const" in node:
            return node["const"]
        if "enum" in node:
            return node["enum"][0]
        for key in ("oneOf", "anyOf", "allOf"):
            if node.get(key):
                return build(node[key][0], depth + 1)
        node_type = node.get("type")
        if isinstance(node_type, list):
            node_type = next((t for t in node_type if t != "null"), node_type[0])
        if node_type == "object" or "properties" in node:
            props = node.get("properties", {})
            required = node.get("required", list(props))
            return {k: build(v, depth + 1) for k, v in props.items() if k in required}
        if node_type == "array":
            items = node.get("items")
            return [build(items, depth + 1)] if isinstance(items, dict) else []
        if node_type == "string":
            return "<текст>"
        if node_type in ("integer", "number"):
            return node.get("minimum", 0)
        if node_type == "boolean":
            return False
        return None

    return build(schema)


ANALYST_PROMPT = """
Ты — аналитик бизнес-рисков. Верни только один JSON-объект без Markdown.
Используй исключительно сведения из входных данных, не выдумывай показатели.
Все пояснения пиши по-русски. Значения enum и schema_version оставляй строго
в том виде, в котором они заданы JSON Schema. Отделяй факты от предположений,
а недостаток данных отражай в unknowns и confidence.
Нельзя возвращать заглушки вроде "..." или пустой объект: заполни все
обязательные поля реальным содержанием.
""".strip()


def build_analyst_prompt(schema: dict, with_example: bool = True) -> str:
    if not with_example:
        return ANALYST_PROMPT
    example = json.dumps(build_example(schema), ensure_ascii=False)
    return (
        f"{ANALYST_PROMPT}\n\n"
        "Форма ответа (значения-заглушки <текст>, 0, enum и пустые списки замени "
        f"реальным содержанием, добавляй элементы в списки по смыслу):\n{example}"
    )
