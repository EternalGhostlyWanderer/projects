"""Evaluate the agent on company × event pairs and the feed ranking against manual labels.

Примеры:
    # бесплатно: только ранжирование ленты по ручной разметке
    python backend/scripts/run_eval.py --companies SYN_001 SYN_002 --labels data/synthetic/relevance_labels.json --feed-only
    # платно: агент на парах «компания × событие» (спросит подтверждение)
    python backend/scripts/run_eval.py --companies SYN_001 SYN_002 --max-events 3

События берутся из хранилища (загрузите их через load_events.py). Результат —
backend/test_results/eval_<время>.json (папка не попадает в Git).
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import run_agent  # noqa: E402
from app.db.store import get_store  # noqa: E402
from app.evaluation.metrics import precision_at_k, recall_at_k, run_record, summarize  # noqa: E402
from app.llm.config import get_settings  # noqa: E402
from app.llm.store import LLMStore  # noqa: E402
from app.modules.personalization.context import build_personalization_context  # noqa: E402
from app.modules.personalization.relevance import assess_relevance  # noqa: E402
from app.modules.personalization.scoring import MIN_FEED_SCORE  # noqa: E402

RESULTS_DIR = Path(__file__).resolve().parents[1] / "test_results"


def ranked_events(company_id: str, events) -> list[tuple]:
    """Лента как в API: по баллу 0–100, только события не ниже порога показа."""
    context = build_personalization_context(company_id) or {}
    scored = [(assess_relevance(context, event.model_dump(mode="json")), event) for event in events]
    return [
        (relevance["score"], event)
        for relevance, event in sorted(scored, key=lambda item: item[0]["score"], reverse=True)
        if relevance["score"] >= MIN_FEED_SCORE
    ]


def legacy_ranked_events(company_id: str, events) -> list[tuple]:
    """Прежнее ранжирование — по числу совпавших факторов; для сравнения со скорингом."""
    context = build_personalization_context(company_id) or {}
    scored = [(assess_relevance(context, event.model_dump(mode="json"))["match_count"], event) for event in events]
    return [item for item in sorted(scored, key=lambda item: item[0], reverse=True) if item[0] > 0]


def feed_quality(rankings: dict, labels: dict) -> dict:
    precision = {
        company_id: precision_at_k([event.event_id for _, event in ranking], set(labels.get(company_id, [])))
        for company_id, ranking in rankings.items()
    }
    recall = {
        company_id: recall_at_k([event.event_id for _, event in ranking], set(labels.get(company_id, [])))
        for company_id, ranking in rankings.items()
    }
    mean = lambda values: round(sum(v for v in values if v is not None) / max(1, sum(v is not None for v in values)), 3)  # noqa: E731
    return {
        "precision_at_5": precision,
        "recall_at_5": recall,
        "mean_precision_at_5": mean(precision.values()),
        "mean_recall_at_5": mean(recall.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Оценка качества агента и ленты.")
    parser.add_argument("--companies", nargs="+", required=True, help="SYNTHETIC_U компаний")
    parser.add_argument("--max-events", type=int, default=3, help="Сколько самых релевантных событий на компанию")
    parser.add_argument("--labels", type=Path, help='JSON {"company_id": ["event_id", ...]} — релевантные события')
    parser.add_argument("--feed-only", action="store_true", help="Только ранжирование ленты, без LLM")
    parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение")
    args = parser.parse_args()

    store = get_store()
    events = store.list_events(limit=500)
    if not events:
        print("В хранилище нет событий: загрузите их через backend/scripts/load_events.py")
        return 1

    report: dict = {"created_at": datetime.now().isoformat(), "companies": args.companies}
    rankings = {company_id: ranked_events(company_id, events) for company_id in args.companies}

    if args.labels:
        labels = json.loads(args.labels.read_text(encoding="utf-8"))
        legacy = {company_id: legacy_ranked_events(company_id, events) for company_id in args.companies}
        report["feed"] = feed_quality(rankings, labels)
        report["feed_legacy_ranking"] = feed_quality(legacy, labels)
        print(
            f"Лента (скоринг 0–100): Precision@5 {report['feed']['mean_precision_at_5']}, "
            f"Recall@5 {report['feed']['mean_recall_at_5']}"
        )
        print(
            f"Прежнее ранжирование:  Precision@5 {report['feed_legacy_ranking']['mean_precision_at_5']}, "
            f"Recall@5 {report['feed_legacy_ranking']['mean_recall_at_5']}"
        )
        for company_id in args.companies:
            print(
                f"  {company_id}: P@5 {report['feed']['precision_at_5'][company_id]} "
                f"R@5 {report['feed']['recall_at_5'][company_id]} "
                f"(было P@5 {report['feed_legacy_ranking']['precision_at_5'][company_id]})"
            )

    if not args.feed_only:
        pairs = [
            (company_id, event)
            for company_id, ranking in rankings.items()
            for count, event in ranking[: args.max_events]
            if count > 0
        ]
        print(f"Запусков агента: {len(pairs)} (каждый — 2–6 запросов к LLM).")
        if pairs and not args.yes and input("Запустить? Введите yes: ").strip().lower() != "yes":
            print("Отменено; запросы к API не отправлялись.")
            return 0

        llm_store = LLMStore(get_settings().state_db)
        usage_before = llm_store.daily_usage()
        records = []
        for company_id, event in pairs:
            started = time.perf_counter()
            result = run_agent(company_id, event)
            records.append(run_record(company_id, event.event_id, result, time.perf_counter() - started))
            if result.insight:
                store.save_analysis(result.insight, result.trace)
            print(f"{company_id} | {event.title[:50]} | {records[-1]['quality_status']} | {records[-1]['issue_codes']}")
        usage_after = llm_store.daily_usage()
        report["runs"] = records
        report["summary"] = summarize(
            records,
            {
                "requests": usage_after["requests"] - usage_before["requests"],
                "cost": round(usage_after["cost"] - usage_before["cost"], 4),
            },
        )
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / f"eval_{datetime.now():%Y%m%d_%H%M%S}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"\nОтчёт: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
