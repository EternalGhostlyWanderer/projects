"""Comparison of approved models on synthetic cases, validated against the BusinessAnalysis contract."""
from __future__ import annotations

import argparse
import json
import time

from jsonschema import Draft202012Validator

from common import (
    PROJECT_ROOT,
    THINK_STYLE_CHOICES,
    build_analyst_prompt,
    extract_json_text,
    format_validation_errors,
    get_config,
    load_schema,
    make_client,
    safe_error,
    think_off_body,
    usage_summary,
)

MODELS = [
    "qwen/qwen3.6-35b-a3b",
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "google/gemma-4-26b-a4b-it",
    "moonshotai/kimi-k2.6",
]

TEST_CASES = [
    {
        "case_id": "loan_exposure",
        "company_profile": {
            "company_id": "SYNTHETIC_A",
            "industry": "manufacturing",
            "loan_product": True,
            "deposit_product": False,
            "debt_amount_rub": None,
            "loan_rate_type": None,
        },
        "event": {
            "title": "Регулятор сохранил ключевую ставку",
            "summary": "Синтетический сценарий без дополнительных числовых данных.",
        },
    },
    {
        "case_id": "deposit_exposure",
        "company_profile": {
            "company_id": "SYNTHETIC_B",
            "industry": "retail",
            "loan_product": False,
            "deposit_product": True,
            "deposit_amount_rub": None,
            "deposit_terms": None,
        },
        "event": {
            "title": "Регулятор сохранил ключевую ставку",
            "summary": "Синтетический сценарий без дополнительных числовых данных.",
        },
    },
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Сравнение моделей на синтетических кейсах.")
    parser.add_argument("--models", nargs="+", default=MODELS, help="Подмножество моделей.")
    parser.add_argument("--cases", nargs="+", default=[c["case_id"] for c in TEST_CASES],
                        help="Подмножество кейсов (case_id).")
    parser.add_argument("--max-tokens", type=int, default=4000)
    parser.add_argument("--think-style", choices=THINK_STYLE_CHOICES, default="none",
                        help="Как отключать рассуждения у всех моделей (none = не передавать).")
    parser.add_argument("--show", action="store_true", help="Печатать полный ответ каждой модели.")
    args = parser.parse_args()

    cases = [c for c in TEST_CASES if c["case_id"] in args.cases]
    if not cases:
        print("Не выбран ни один кейс.")
        return 1

    try:
        get_config()
        schema = load_schema()
    except Exception as exc:
        print(safe_error(exc))
        return 1

    validator = Draft202012Validator(schema)
    system_prompt = build_analyst_prompt(schema)
    total = len(cases) * len(args.models)

    print(f"Будет выполнено запросов к API: {total} ({len(args.models)} моделей × {len(cases)} кейсов).")
    print(f"max_tokens={args.max_tokens}, think-style={args.think_style}.")
    print("Бюджет 500 рублей/день общий для всех участников команды и моделей.")
    answer = input("Запустить сравнение? Введите yes для подтверждения: ").strip().lower()
    if answer != "yes":
        print("Отменено; API-запросы не отправлялись.")
        return 0

    client, _default_model = make_client()
    results: list[dict] = []

    for case in cases:
        case_input = {k: v for k, v in case.items() if k != "case_id"}
        user_payload = {"input": case_input, "output_schema": schema}
        for model in args.models:
            record: dict = {"case_id": case["case_id"], "model": model, "synthetic_data": True}
            kwargs: dict = {
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "max_tokens": args.max_tokens,
                "response_format": {"type": "json_object"},
            }
            body = think_off_body(args.think_style)
            if body:
                kwargs["extra_body"] = body

            start = time.perf_counter()
            try:
                response = client.chat.completions.create(**kwargs)
                record["seconds"] = round(time.perf_counter() - start, 2)
                choice = response.choices[0]
                content = choice.message.content or ""
                record["finish_reason"] = choice.finish_reason
                record["usage"] = usage_summary(response)
                record["response"] = content
                try:
                    payload = json.loads(extract_json_text(content))
                    record["valid_json"] = True
                    errors = format_validation_errors(validator, payload)
                    record["schema_valid"] = not errors
                    record["schema_errors"] = errors
                except (TypeError, json.JSONDecodeError):
                    record["valid_json"] = False
                    record["schema_valid"] = False
                print(
                    f"\n{'=' * 70}\n{model} | {case['case_id']} | {record['seconds']}s | "
                    f"finish={record['finish_reason']} | json={record['valid_json']} | "
                    f"schema={record['schema_valid']}\n"
                    f"usage={json.dumps(record['usage'], ensure_ascii=False)}"
                )
                if record.get("schema_errors"):
                    for err in record["schema_errors"][:5]:
                        print(f"  - {err}")
                if args.show:
                    print(content or "[Empty response]")
            except Exception as exc:
                record["error"] = safe_error(exc)
                record["seconds"] = round(time.perf_counter() - start, 2)
                print(f"\nERROR | {model} | {case['case_id']}: {record['error']}")
            results.append(record)

    output_dir = PROJECT_ROOT / "backend" / "test_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "model_comparison.json"
    output_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 70}\nСВОДКА")
    print(f"{'модель':<32}{'кейс':<18}{'схема':<8}{'сек':<8}{'токены':<9}{'reasoning':<10}{'cost':<10}")
    for r in results:
        u = r.get("usage") or {}
        print(
            f"{r['model']:<32}{r['case_id']:<18}{str(r.get('schema_valid')):<8}"
            f"{str(r.get('seconds')):<8}{str(u.get('completion_tokens')):<9}"
            f"{str(u.get('reasoning_tokens')):<10}{str(u.get('cost')):<10}"
        )
    print(f"\nРезультаты сохранены: {output_path}")
    print("Валидная схема не означает правильный анализ: сравните содержание ответов вручную (--show или файл выше).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
