"""Проверить подключение к LLM с настройками сервиса и подсказать, что исправить.

На сервере (из папки проекта):

    docker compose exec backend python scripts/check_llm.py
    docker compose exec backend python scripts/check_llm.py --models     # какие модели доступны по ключу

Проверяет основную модель и каждую запасную (LLM_FALLBACKS) одним маленьким запросом в том же режиме,
что и разбор (JSON, без рассуждений), мимо кеша и дневного лимита, и показывает последние ошибки из
журнала запросов (var/llm.sqlite3).
"""
import argparse
import sqlite3
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel  # noqa: E402

from app.llm.client import LLMClient, LLMError  # noqa: E402
from app.llm.config import LLMConfigError, get_settings  # noqa: E402
from app.llm.store import LLMStore  # noqa: E402

HINTS = (
    (("api key not valid", "valid api key", "api_key_invalid", "invalid api key", "incorrect api key", "401", "unauthorized"),
     "Ключ не принят: проверьте ключ в .env (LLM_API_KEY для основного, GEMINI_/GROQ_/OPENROUTER_/MISTRAL_/DEEPSEEK_API_KEY "
     "для запасных) — без пробелов и кавычек, от нужного провайдера."),
    (("location is not supported", "user location", "failed_precondition", "unsupported_country"),
     "Провайдер не работает в стране сервера: выберите другой регион VPS или другого провайдера."),
    (("permission_denied", "403", "forbidden"),
     "Доступ запрещён: у ключа нет прав на эту модель или API не включён в проекте (Google AI Studio → ключ)."),
    (("thinking budget", "unknown name", "invalid json payload", "unrecognized", "extra_forbidden", "reasoning",
      "enable_thinking", "invalid argument"),
     "Модель не принимает один из параметров запроса: сервис повторяет такой запрос без него; если ошибка "
     "осталась — поставьте LLM_THINK_STYLE=none или выберите другую модель."),
    (("503", "unavailable", "high demand", "overloaded"),
     "Модель перегружена у провайдера (временно): сервис переключится на запасную, позже основная заработает."),
    (("not found", "404", "is not supported for", "does not exist", "model_not_found"),
     "Модель не найдена: посмотрите доступные (--models) и укажите одну в LLM_MODEL."),
    (("response_format", "json_object", "json mode"),
     "Модель не поддерживает JSON-режим: поставьте LLM_JSON_MODE=0."),
    (("429", "rate limit", "quota", "resource_exhausted"),
     "Лимит бесплатного тарифа исчерпан: подождите (минутный лимит) или до завтра (дневной); "
     "либо уменьшите PREANALYZE_PER_COMPANY / PREANALYZE_DAILY_LIMIT."),
    (("timed out", "timeout", "connection", "name or service not known", "temporary failure"),
     "Сервер не достучался до провайдера: проверьте сеть VPS (curl до адреса из LLM_BASE_URL)."),
)


def hint_for(message: str) -> str:
    text = message.lower()
    for markers, hint in HINTS:
        if any(marker in text for marker in markers):
            return hint
    return "Неизвестная ошибка: пришлите её текст (ключ в нём скрыт)."


def masked(key: str) -> str:
    return f"{key[:4]}…{key[-2:]} ({len(key)} симв.)" if len(key) > 8 else "(короткий — похоже, не ключ)"


def recent_errors(db_path: Path, limit: int = 5) -> None:
    if not db_path.exists():
        print("\nЖурнал запросов пока пуст.")
        return
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT created_at, task, model, status, substr(error, 1, 400) FROM llm_calls "
            "WHERE status NOT IN ('ok') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    if not rows:
        print("\nОшибок в журнале запросов нет.")
        return
    print(f"\nПоследние ошибки из журнала ({len(rows)}):")
    for created_at, task, model, status, error in rows:
        print(f"- {created_at[:19]} {task} [{model}] {status}: {error}")


class Ok(BaseModel):
    ok: bool


def check_route(route, settings) -> bool:
    """Один маленький запрос к маршруту через тот же клиент, что и разбор: JSON-режим, без кеша и запасных,
    с теми же автоматическими поправками (без параметра рассуждений, без JSON-режима, без системной
    инструкции, если модель их не принимает). Журнал — во временной базе, дневной лимит не тратится."""
    print(f"\n[{route.provider}] {route.base_url} — модель {route.model}, ключ {masked(route.api_key)}")
    with tempfile.TemporaryDirectory() as temp_dir:
        single = replace(
            settings,
            provider=route.provider,
            base_url=route.base_url,
            default_model=route.model,
            role_models={},
            think_style=route.think_style,
            api_key=route.api_key,
            fallbacks=(),
            daily_request_limit=None,
            daily_cost_limit=None,
            state_db=Path(temp_dir) / "check.sqlite3",
        )
        client = LLMClient(settings=single, client=route.client, store=LLMStore(single.state_db))
        client._sleep = lambda _: None  # проверка не ждёт минутного лимита
        started = time.perf_counter()
        try:
            client.chat_json(
                [
                    {"role": "system", "content": "Отвечай только JSON-объектом."},
                    {"role": "user", "content": 'Верни {"ok": true}.'},
                ],
                Ok,
                task="check_llm",
                use_cache=False,
                max_repairs=0,
                max_tokens=200,
            )
        except LLMError as exc:
            message = str(exc).replace(route.api_key, "[ключ скрыт]")
            print(f"  ОШИБКА: {message[:1200]}")
            content = getattr(exc, "content", "")
            if content or getattr(exc, "errors", None):
                # Модель ответила, но не по формату: показать, что именно пришло.
                print(f"  Замечания к ответу: {'; '.join(exc.errors)[:500]}")
                print(f"  Ответ модели: {content[:300]!r}")
                print("  Подсказка: модель отвечает не в формате JSON — выберите другую (--models).")
            else:
                print(f"  Подсказка: {hint_for(message)}")
            return False
    notes = [
        text
        for flag, text in (
            (route.key in client._no_think, "без параметра рассуждений"),
            (route.key in client._no_json, "без JSON-режима"),
            (route.key in client._no_system, "без системной инструкции"),
        )
        if flag
    ]
    extra = f" ({', '.join(notes)} — сервис делает так же автоматически)" if notes else ""
    print(f"  Работает: ответ за {time.perf_counter() - started:.1f} с{extra}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models", action="store_true", help="показать модели, доступные по ключу у каждого провайдера")
    args = parser.parse_args()

    try:
        settings = get_settings()
    except LLMConfigError as exc:
        print(f"Настройки LLM неполные: {exc}")
        return 1

    routes = LLMClient(settings=settings).routes()
    print(f"Основной провайдер: {settings.provider}; запасных: {len(routes) - 1} (LLM_FALLBACKS)")
    print(f"Отключение рассуждений: {settings.think_style}; JSON-режим: {'да' if settings.json_mode else 'нет'}")

    if args.models:
        # По одному списку на провайдера: у запасных (Groq, OpenRouter…) свои модели.
        seen: set[str] = set()
        for route in routes:
            if route.provider in seen:
                continue
            seen.add(route.provider)
            try:
                names = sorted(model.id for model in route.client.models.list())
            except Exception as exc:  # noqa: BLE001
                message = str(exc).replace(route.api_key, "[ключ скрыт]")
                print(f"\n[{route.provider}] список моделей не получен: {type(exc).__name__}: {message[:300]}")
                continue
            if route.provider == "openrouter":
                names = [name for name in names if name.endswith(":free")]  # платные не нужны
            print(f"\n[{route.provider}] доступно моделей: {len(names)}")
            for name in names:
                print(f"- {name}")
        return 0

    results = [check_route(route, settings) for route in routes]
    working = sum(results)
    print()
    if results[0]:
        print("Основная модель работает.")
    elif working:
        print(f"Основная модель не работает, но запросы будут уходить запасной ({working} из {len(routes)} работают).")
    else:
        print("Ни одна модель не работает: исправьте настройки по подсказкам выше.")
    recent_errors(settings.state_db)
    return 0 if working else 1


if __name__ == "__main__":
    raise SystemExit(main())
