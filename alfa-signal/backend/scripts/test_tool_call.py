"""Check whether the configured model returns a function tool call."""
from __future__ import annotations

import argparse
import json

from common import THINK_STYLE_CHOICES, make_client, safe_error, think_off_body, usage_summary

TOOL = {
    "type": "function",
    "function": {
        "name": "get_company_profile",
        "description": "Получает профиль тестовой компании по ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Идентификатор синтетической тестовой компании",
                }
            },
            "required": ["company_id"],
            "additionalProperties": False,
        },
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка tool calling.")
    parser.add_argument("--model", help="Модель; по умолчанию LLM_MODEL.")
    parser.add_argument("--think-style", choices=THINK_STYLE_CHOICES, default="none")
    parser.add_argument("--max-tokens", type=int, default=600)
    args = parser.parse_args()

    try:
        client, default_model = make_client()
        model = args.model or default_model
        kwargs: dict = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Для начала анализа нужно получить профиль компании "
                        "SYNTHETIC_A. Используй доступный инструмент."
                    ),
                }
            ],
            "tools": [TOOL],
            "tool_choice": {"type": "function", "function": {"name": "get_company_profile"}},
            "max_tokens": args.max_tokens,
        }
        body = think_off_body(args.think_style)
        if body:
            kwargs["extra_body"] = body

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        message = choice.message
        print("Модель:", model)
        print("finish_reason:", choice.finish_reason)
        print("usage:", json.dumps(usage_summary(response), ensure_ascii=False))

        if message.tool_calls:
            all_ok = True
            for call in message.tool_calls:
                print("\nTool name:", call.function.name)
                print("Raw arguments:", call.function.arguments)
                try:
                    args_obj = json.loads(call.function.arguments)
                    print("Parsed arguments:", json.dumps(args_obj, ensure_ascii=False, indent=2))
                    if call.function.name != "get_company_profile" or "company_id" not in args_obj:
                        all_ok = False
                        print("Предупреждение: имя инструмента или обязательный аргумент company_id не совпали.")
                except (TypeError, json.JSONDecodeError):
                    all_ok = False
                    print("Аргументы не удалось разобрать как JSON.")
            if all_ok:
                print("\nУспех: модель вернула корректный tool_call. Инструмент не выполнялся.")
                return 0
            return 2

        print("Tool call не получен.")
        print("Текст модели:", message.content)
        print("Это может указывать на ограничение шлюза или несовместимый формат; проверьте точную ошибку/документацию API.")
        return 2

    except Exception as exc:
        print("Проверка tool calling не прошла:")
        print(safe_error(exc))
        print("Проверьте поддержку tools/tool_choice на API-шлюзе. Тест не выполняет никаких реальных действий.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
