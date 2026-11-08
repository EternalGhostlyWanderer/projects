"""Request and validate one structured business analysis from an approved model."""
from __future__ import annotations

import argparse
import json
import time

from jsonschema import Draft202012Validator

from common import (
    THINK_OFF_STYLES,
    build_analyst_prompt,
    extract_json_text,
    format_validation_errors,
    load_schema,
    make_client,
    safe_error,
    think_off_body,
    usage_summary,
)

TEST_CASE = {
    "company_profile": {
        "company_id": "SYNTHETIC_MANUFACTURER",
        "industry": "manufacturing",
        "regions": ["Russia"],
        "loan_product": True,
        "deposit_product": False,
        "debt_amount_rub": None,
        "loan_rate_type": None,
        "revenue_currency": "RUB",
        "import_dependency": "unknown",
    },
    "event": {
        "title": "Регулятор сохранил ключевую ставку",
        "summary": "Синтетический тестовый сценарий без дополнительных числовых данных.",
    },
}


def print_diagnostics(response, elapsed: float) -> None:
    choice = response.choices[0]
    print("--- Диагностика ---")
    print("finish_reason:", choice.finish_reason)
    print(f"Время: {elapsed:.2f} с")
    print("usage:", json.dumps(usage_summary(response), ensure_ascii=False))
    print("message:", json.dumps(choice.message.model_dump(), ensure_ascii=False, default=str)[:2000])
    if choice.finish_reason == "length":
        print("Ответ оборван по лимиту токенов: увеличьте --max-tokens или отключите рассуждения (--no-think).")
    print("-------------------")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Делает один API-запрос и проверяет структурированный бизнес-анализ."
    )
    parser.add_argument("--model", help="Модель; по умолчанию LLM_MODEL.")
    parser.add_argument("--max-tokens", type=int, default=4000,
                        help="Лимит токенов ответа (по умолчанию 4000).")
    parser.add_argument("--no-think", action="store_true",
                        help="Отключить рассуждения (стиль задаётся --think-style).")
    parser.add_argument("--think-style", choices=list(THINK_OFF_STYLES), default="openrouter",
                        help="Как отключать рассуждения; найдите рабочий через test_connection.py --try-all.")
    parser.add_argument("--no-response-format", action="store_true",
                        help="Не передавать response_format=json_object.")
    parser.add_argument("--no-example", action="store_true",
                        help="Не добавлять в промпт пример формы ответа, собранный из схемы.")
    parser.add_argument("--show-prompt", action="store_true",
                        help="Напечатать системный промпт и выйти без запроса к API.")
    args = parser.parse_args()

    try:
        schema = load_schema()
        validator = Draft202012Validator(schema)
        system_prompt = build_analyst_prompt(schema, with_example=not args.no_example)
        if args.show_prompt:
            print(system_prompt)
            return 0

        client, configured_model = make_client()
        model = args.model or configured_model
        user_payload = {"input": TEST_CASE, "output_schema": schema}

        request_kwargs: dict = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "max_tokens": args.max_tokens,
        }
        if not args.no_response_format:
            request_kwargs["response_format"] = {"type": "json_object"}
        if args.no_think:
            request_kwargs["extra_body"] = think_off_body(args.think_style)

        started_at = time.perf_counter()
        response = client.chat.completions.create(**request_kwargs)
        elapsed = time.perf_counter() - started_at
        content = response.choices[0].message.content or ""

        if not content.strip():
            print("Модель вернула пустой content.")
            print_diagnostics(response, elapsed)
            return 4

        try:
            payload = json.loads(extract_json_text(content))
        except json.JSONDecodeError as exc:
            print("Ответ модели не является валидным JSON.")
            print(f"Ошибка: строка {exc.lineno}, столбец {exc.colno}: {exc.msg}")
            print("Начало ответа:", repr(content[:500]))
            print_diagnostics(response, elapsed)
            return 2

        validation_errors = format_validation_errors(validator, payload)
        if validation_errors:
            print("JSON получен, но не соответствует контракту:")
            for error in validation_errors:
                print(f"- {error}")
            print("\nПолный ответ:")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            print_diagnostics(response, elapsed)
            return 3

        print("Успех: получен JSON, соответствующий контракту BusinessAnalysis 1.0.")
        print("Запрошенная модель:", model)
        print("Модель в ответе:", response.model)
        print(f"Время: {elapsed:.2f} с")
        print("Usage:", json.dumps(usage_summary(response), ensure_ascii=False))
        print("\nСтруктурированный ответ:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print("Не удалось получить структурированный бизнес-анализ:")
        print(safe_error(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
