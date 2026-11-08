"""Quality metrics over agent runs and feed rankings (no LLM calls here)."""
from collections import defaultdict
from itertools import combinations
from statistics import mean
from typing import Any, Iterable, Optional


def run_record(company_id: str, event_id: str, result: Any, seconds: float) -> dict[str, Any]:
    """Flatten one AgentResult into a JSON-friendly record."""
    insight = result.insight
    issues = (result.verification.issues if result.verification else [])
    return {
        "company_id": company_id,
        "event_id": event_id,
        "ok": insight is not None,
        "seconds": round(seconds, 2),
        "quality_status": insight.quality_status if insight else None,
        "issue_codes": [issue.code for issue in issues],
        "tool_calls": result.trace.tool_calls,
        "rounds": result.trace.rounds,
        "bank_view": insight.bank_view.status if insight else None,
        "kind": insight.kind if insight else None,
        "score": insight.relevance.score if insight else None,
        "company_evidence": sorted(
            evidence_id
            for evidence_id in (insight.referenced_evidence_ids() if insight else set())
            if evidence_id.startswith("company.")
        ),
        "trace_id": result.trace.trace_id,
    }


def _rate(records: list[dict[str, Any]], predicate) -> Optional[float]:
    return round(sum(1 for record in records if predicate(record)) / len(records), 3) if records else None


def _jaccard(first: Iterable[str], second: Iterable[str]) -> float:
    a, b = set(first), set(second)
    return len(a & b) / len(a | b) if a | b else 1.0


def personalization(records: list[dict[str, Any]]) -> dict[str, Any]:
    """For events analyzed for several companies: how different are the conclusions?"""
    by_event: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if record["ok"]:
            by_event[record["event_id"]].append(record)

    pairs = [pair for group in by_event.values() for pair in combinations(group, 2)]
    if not pairs:
        return {"pairs": 0}
    return {
        "pairs": len(pairs),
        "mean_company_evidence_jaccard": round(mean(_jaccard(a["company_evidence"], b["company_evidence"]) for a, b in pairs), 3),
        "share_different_kind_or_score": round(
            sum(1 for a, b in pairs if a["kind"] != b["kind"] or a["score"] != b["score"]) / len(pairs), 3
        ),
    }


def summarize(records: list[dict[str, Any]], llm_usage: Optional[dict[str, float]] = None) -> dict[str, Any]:
    ok = [record for record in records if record["ok"]]
    issue_counts: dict[str, int] = defaultdict(int)
    for record in ok:
        for code in record["issue_codes"]:
            issue_counts[code] += 1

    return {
        "runs": len(records),
        "success_rate": _rate(records, lambda record: record["ok"]),
        "verified_rate": _rate(ok, lambda record: record["quality_status"] == "verified"),
        # «verified» — проверено автоматически, а не экспертно (app/ai/schemas.py, QualityStatus).
        "status_counts": dict(sorted(
            {status: sum(1 for record in ok if record["quality_status"] == status)
             for status in {record["quality_status"] for record in ok}}.items()
        )),
        "revision_rate": _rate(ok, lambda record: record["rounds"] > 0),
        "bank_found_rate": _rate(ok, lambda record: record["bank_view"] == "found"),
        "runs_with_unsupported_numbers": issue_counts.get("unsupported_number", 0),
        "avg_tool_calls": round(mean(record["tool_calls"] for record in ok), 2) if ok else None,
        "avg_seconds": round(mean(record["seconds"] for record in records), 2) if records else None,
        "issue_counts": dict(sorted(issue_counts.items())),
        "personalization": personalization(records),
        "llm_usage": llm_usage,
    }


def precision_at_k(ranked_event_ids: list[str], relevant_ids: set[str], k: int = 5) -> Optional[float]:
    top = ranked_event_ids[:k]
    return round(sum(1 for event_id in top if event_id in relevant_ids) / len(top), 3) if top else None


def recall_at_k(ranked_event_ids: list[str], relevant_ids: set[str], k: int = 5) -> Optional[float]:
    """Доля важных событий, попавших в топ-k (из тех, что вообще могут поместиться в k).

    Пропуск важного события — самая серьёзная ошибка по кейсу, поэтому считаем и полноту.
    """
    if not relevant_ids:
        return None
    found = sum(1 for event_id in ranked_event_ids[:k] if event_id in relevant_ids)
    return round(found / min(k, len(relevant_ids)), 3)
