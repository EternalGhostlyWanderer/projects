"""End-to-end scenario against a running API: two companies, one event, trace, follow-up question.

Пример (сервер уже запущен на :8000):
    python backend/scripts/demo_scenario.py --companies SYN_001 SYN_002 --event-match "ключевую ставку"

Платно: два анализа агентом (2–6 запросов каждый) и один вопрос в чат (2 запроса).
Повторный запуск берёт готовые инсайты из хранилища (кроме вопроса в чат).
"""
import argparse
import json
import sys
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

QUESTION = "Что если ставка снизится на 1 п.п. при долге 500 млн руб.?"


def call(base: str, method: str, path: str, body: dict | None = None, timeout: int = 180) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = Request(
        base + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} → HTTP {exc.code}: {detail}") from exc


def show_insight(insight: dict) -> None:
    print(f"  quality_status: {insight['quality_status']}  kind: {insight['kind']}  "
          f"relevance: {insight['relevance']['score']} ({insight['relevance']['level']})")
    print("  почему важно:", "; ".join(reason["text"] for reason in insight["relevance"]["reasons"]))
    print("  цепочка:", " → ".join(insight["mechanism"]))
    print("  эффект:", insight["primary_effect"]["text"])
    print("  позиция банка:", insight["bank_view"]["status"],
          "|", "; ".join(claim["text"] for claim in insight["bank_view"]["claims"]) or "—")
    for issue in insight["quality_issues"]:
        print("  !", issue)


def main() -> int:
    parser = argparse.ArgumentParser(description="Сквозной сценарий через API.")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--companies", nargs=2, default=["SYN_001", "SYN_002"])
    parser.add_argument("--event-match", default="ключевую ставку", help="Фрагмент заголовка события")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--force", action="store_true", help="Пересчитать анализ, даже если он уже сохранён (платно)")
    args = parser.parse_args()

    status = call(args.base, "GET", "/api/v1/system/status")
    print("Статус:", json.dumps(status, ensure_ascii=False))
    if not status["llm"].get("configured"):
        print("LLM не настроена — проверьте backend/.env")
        return 1

    print("\n1) Ленты компаний (без LLM)")
    feeds = {}
    for company_id in args.companies:
        feeds[company_id] = call(args.base, "GET", "/api/v1/feed?" + urlencode({"company_id": company_id, "limit": 5}))
        print(f"  {company_id}:")
        for item in feeds[company_id]["items"]:
            relevance = item["relevance"]
            print(f"    - [{relevance.get('score', '—'):>3}] {item['event']['title'][:70]}")
            print(f"          {relevance.get('explanation', relevance['matched_factors'])}"[:160])

    events = call(args.base, "GET", "/api/v1/events?limit=200")["items"]
    event = next((item for item in events if args.event_match.lower() in item["title"].lower()), None)
    if event is None:
        print(f"Событие с «{args.event_match}» не найдено; загрузите новости через load_events.py")
        return 1

    if not args.yes and input(f"\nРазобрать «{event['title']}» для двух компаний и задать вопрос (платно)? yes: ").strip() != "yes":
        return 0

    insights = {}
    for number, company_id in enumerate(args.companies, start=2):
        print(f"\n{number}) Анализ для {company_id}…")
        insights[company_id] = call(
            args.base, "POST", "/api/v1/insights/analyze", {"company_id": company_id, "event_id": event["event_id"], "force": args.force},
        )
        if not args.force:
            print("  (если анализ уже был, показан сохранённый; пересчитать — флаг --force)")
        show_insight(insights[company_id])

    first = insights[args.companies[0]]
    trace = call(args.base, "GET", f"/api/v1/insights/{first['insight_id']}/trace")
    print(f"\n4) Журнал агента ({args.companies[0]}): вызовов инструментов {trace['tool_calls']}, итераций {trace['rounds']}")
    for step in trace["steps"]:
        mark = "" if step["status"] == "ok" else f" [{step['status']}]"
        print(f"  {step['n']:>2}. {step['phase']:<10} {step['name']:<22}{mark} {step['output_summary'][:90]}")

    print(f"\n5) Вопрос: {QUESTION}")
    answer = call(args.base, "POST", f"/api/v1/insights/{first['insight_id']}/ask", {"question": QUESTION})
    for claim in answer["answer"]:
        print(f"  [{claim['basis']}] {claim['text']}")
    if answer.get("calculation"):
        print("  расчёт:", answer["calculation"]["annual_interest_change_rub"], "руб./год")
    return 0


if __name__ == "__main__":
    sys.exit(main())
