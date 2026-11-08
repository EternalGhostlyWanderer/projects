"""Send small requests to the configured model and find how to switch thinking off.

Примеры:
    python backend\\scripts\\test_connection.py                 # один запрос, настройки по умолчанию
    python backend\\scripts\\test_connection.py --think-style openrouter
    python backend\\scripts\\test_connection.py --try-all       # 5 маленьких запросов: baseline + 4 стиля
"""
from __future__ import annotations

import argparse
import json
import time

from common import (
    THINK_OFF_STYLES,
    THINK_STYLE_CHOICES,
    make_client,
    safe_error,
    think_off_body,
    usage_summary,
)

# Задача, на которой thinking-модель обычно рассуждает, чтобы разница была видна.
DEFAULT_PROMPT = "Сколько будет 17 * 23? Ответь одним числом, без пояснений."


def run_once(client, model: str, style: str, prompt: str, max_tokens: int):
    kwargs: dict = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
    }
    body = think_off_body(style)
    if body:
        kwargs["extra_body"] = body
    started = time.perf_counter()
    response = client.chat.completions.create(**kwargs)
    return response, time.perf_counter() - started


def describe(style: str, response, elapsed: float) -> dict:
    choice = response.choices[0]
    summary = usage_summary(response)
    reasoning = summary.get("reasoning_tokens")
    if reasoning is None:
        verdict = "шлюз не вернул reasoning_tokens (смотрите completion_tokens)"
    elif reasoning == 0:
        verdict = "рассуждения ВЫКЛЮЧЕНЫ"
    else:
        verdict = "рассуждения работают"
    print(f"\n--- стиль: {style} ---")
    print("Ответ:", repr(choice.message.content))
    print("finish_reason:", choice.finish_reason)
    print(f"Время: {elapsed:.2f} с")
    print("usage:", json.dumps(summary, ensure_ascii=False))
    print("Вывод:", verdict)
    return {"style": style, "ok": True, "seconds": round(elapsed, 2), **summary}


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка соединения и режима рассуждений.")
    parser.add_argument("--think-style", choices=THINK_STYLE_CHOICES, default="none",
                        help="Как отключать рассуждения (none = параметр не передаётся).")
    parser.add_argument("--try-all", action="store_true",
                        help="Прогнать baseline и все стили отключения (5 коротких запросов).")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--max-tokens", type=int, default=1000)
    args = parser.parse_args()

    try:
        client, model = make_client()
    except Exception as exc:
        print(safe_error(exc))
        return 1

    styles = ["none", *THINK_OFF_STYLES] if args.try_all else [args.think_style]
    print("Запрошенная модель:", model)
    rows: list[dict] = []
    for style in styles:
        try:
            response, elapsed = run_once(client, model, style, args.prompt, args.max_tokens)
            print("Модель в ответе:", response.model)
            rows.append(describe(style, response, elapsed))
        except Exception as exc:
            print(f"\n--- стиль: {style} ---")
            print("Ошибка:", safe_error(exc))
            rows.append({"style": style, "ok": False})

    if args.try_all:
        print("\n=== ИТОГ ===")
        print(f"{'стиль':<12}{'ok':<7}{'reasoning':<11}{'completion':<12}{'сек':<7}")
        for row in rows:
            print(
                f"{row['style']:<12}{str(row['ok']):<7}"
                f"{str(row.get('reasoning_tokens')):<11}"
                f"{str(row.get('completion_tokens')):<12}"
                f"{str(row.get('seconds')):<7}"
            )
        print("\nИщите стиль, у которого ok=True и reasoning близко к 0, и используйте его как --think-style.")
    return 0 if any(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
