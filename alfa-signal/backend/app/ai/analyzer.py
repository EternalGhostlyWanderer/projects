"""Company-aware event analyzer."""
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from app.ai.evidence import bank_evidence, company_evidence, event_evidence, market_evidence
from app.ai.prompts import build_analyst_prompt
from app.ai.schemas import Evidence, Insight, InsightDraft
from app.llm import LLMClient, get_llm_client
from app.llm.compact import EVIDENCE_TEXT_LIMIT, clip, compact_json

# Длинные фрагменты обзоров банка и полные тексты новостей обрезаются в запросе по слову,
# сами доказательства (и проверка ссылок на них) не меняются.
DESCRIPTION_LIMIT = 1200
ARTICLE_TEXT_LIMIT = 2500
# Из разложения балла модели нужны признаки и причины; порядок в ленте и свежесть — нет.
RELEVANCE_FIELDS = ("score", "level", "matched_factors", "components")
COMPONENT_FIELDS = ("label", "points", "reason", "certainty")

ALLOWED_SOURCES = {
    "FACT": {"news", "company_data"},
    "BANK_ANALYSIS": {"bank_research"},
}


def _compact_company(context: dict[str, Any]) -> dict[str, Any]:
    payments = context.get("payment_exposures") or {}
    payment_summary: dict[str, Any] = {"status": payments.get("status")}

    for direction in ("incoming", "outgoing"):
        summary = payments.get(direction)
        if summary:
            payment_summary[direction] = {
                "counterparty_count": summary.get("counterparty_count"),
                "top_5_amount_share": summary.get("top_5_amount_share"),
                "concentration": summary.get("concentration"),
            }

    profile = dict(context.get("company_profile") or {})
    # id повторяет company_id; продукты — списком подключённых, а не словарём флагов.
    profile.pop("id", None)
    if isinstance(profile.get("products"), dict):
        profile["products"] = [name for name, enabled in profile["products"].items() if enabled]
    return {
        "company_id": context.get("company_id"),
        "profile": profile,
        # source — имя колонки исходных данных: для вывода модели оно ничего не добавляет.
        "sensitivity_factors": [
            {key: value for key, value in factor.items() if key != "source"} if isinstance(factor, dict) else factor
            for factor in context.get("sensitivity_factors", [])
        ],
        "payments": payment_summary,
    }


def _event_for_prompt(event: dict[str, Any]) -> dict[str, Any]:
    """Метаданные события. Заголовок и краткое описание уже есть в доказательстве event.main —
    повторно их не отправляем; полное описание — только если оно добавляет текст к summary."""
    brief = {
        key: event.get(key)
        for key in ("event_id", "event_type", "impact_channels", "entities", "published_at", "source")
    }
    description = event.get("description")
    summary = event.get("summary") or ""
    if description and summary and " ".join(str(description).split()) not in " ".join(summary.split()):
        brief["description"] = clip(description, DESCRIPTION_LIMIT)
    brief["text_evidence_id"] = "event.main"
    return brief


def _relevance_for_prompt(relevance: dict[str, Any]) -> dict[str, Any]:
    slim = {key: relevance.get(key) for key in RELEVANCE_FIELDS}
    slim["components"] = [
        {key: part.get(key) for key in COMPONENT_FIELDS} for part in relevance.get("components") or []
    ]
    return slim


def check_draft_evidence(
    draft: InsightDraft,
    evidence: list[Evidence],
) -> list[str]:
    by_id = {item.id: item for item in evidence}
    errors: list[str] = []

    unknown = draft.referenced_evidence_ids() - by_id.keys()
    if unknown:
        errors.append(
            "Ссылки на несуществующие evidence_ids: " + ", ".join(sorted(unknown))
        )

    for claim in draft.claims():
        allowed = ALLOWED_SOURCES.get(claim.basis)
        if not allowed:
            continue
        wrong = [
            evidence_id
            for evidence_id in claim.evidence_ids
            if evidence_id in by_id and by_id[evidence_id].source_kind not in allowed
        ]
        if wrong:
            errors.append(
                f"Утверждение «{claim.text[:80]}» с basis={claim.basis} "
                f"ссылается на неподходящие источники: {', '.join(wrong)}"
            )

    for claim in draft.event_summary:
        if not any(
            by_id.get(evidence_id) and by_id[evidence_id].source_kind == "news"
            for evidence_id in claim.evidence_ids
        ):
            errors.append(
                f"event_summary «{claim.text[:80]}» должен ссылаться на evidence новости"
            )

    has_bank_evidence = any(item.source_kind == "bank_research" for item in evidence)
    if draft.bank_view.status == "found" and not has_bank_evidence:
        errors.append(
            "Материалов Альфа-Банка во входных данных нет: "
            "bank_view.status должен быть not_found"
        )

    return errors


def repair_draft(draft: InsightDraft, evidence: list[Evidence]) -> InsightDraft:
    """Исправить механические нарушения контракта, не меняя смысла ответа.

    Модель иногда ссылается на несуществующий id или ставит BANK_ANALYSIS на новость. Раньше такой
    ответ целиком отклонялся (HTTP 502), хотя содержательно он годился. Здесь:
    - ссылки на несуществующие доказательства удаляются;
    - утверждение FACT или BANK_ANALYSIS, у которого после этого не осталось подходящих источников,
      становится AI_INFERENCE — честная метка вывода модели;
    - тезис позиции банка без материала банка убирается из bank_view (там допустим только
      BANK_ANALYSIS); если тезисов не осталось — bank_view=not_found.
    Пункты event_summary не трогаются: факт события без ссылки на новость — повод для повторного запроса.
    """
    by_id = {item.id: item for item in evidence}
    bank_ids = {item.id for item in evidence if item.source_kind == "bank_research"}
    draft.bank_view.claims = [
        claim
        for claim in draft.bank_view.claims
        if claim.basis == "BANK_ANALYSIS" and any(evidence_id in bank_ids for evidence_id in claim.evidence_ids)
    ]
    if not draft.bank_view.claims:
        draft.bank_view.status = "not_found"
    summary_ids = {id(claim) for claim in draft.event_summary}
    for claim in draft.claims():
        claim.evidence_ids = [evidence_id for evidence_id in claim.evidence_ids if evidence_id in by_id]
        allowed = ALLOWED_SOURCES.get(claim.basis)
        if not allowed or id(claim) in summary_ids:
            continue
        fitting = [evidence_id for evidence_id in claim.evidence_ids if by_id[evidence_id].source_kind in allowed]
        if fitting:
            claim.evidence_ids = fitting if claim.basis == "BANK_ANALYSIS" else claim.evidence_ids
        else:
            claim.basis = "AI_INFERENCE"
    return draft


def _repaired_errors(draft: InsightDraft, evidence: list[Evidence]) -> list[str]:
    """Исправить механику и проверить, что исправленный ответ по-прежнему соответствует контракту."""
    repair_draft(draft, evidence)
    try:
        InsightDraft.model_validate(draft.model_dump())
    except ValidationError as exc:
        return [f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()]
    return check_draft_evidence(draft, evidence)


REVISION_PROMPT = (
    "Предыдущий вариант анализа не прошёл проверку:\n{issues}\n\n"
    "Составь анализ заново с учётом замечаний и верни JSON целиком."
)


def analyze_event(
    context: dict[str, Any],
    event: dict[str, Any],
    relevance: dict[str, Any],
    bank_chunks: Iterable[dict[str, Any]] = (),
    *,
    llm: Optional[LLMClient] = None,
    feedback: Iterable[str] = (),
) -> Insight:
    insight, _ = analyze_event_detailed(
        context, event, relevance, bank_chunks, llm=llm, feedback=feedback
    )
    return insight


def analyze_event_detailed(
    context: dict[str, Any],
    event: dict[str, Any],
    relevance: dict[str, Any],
    bank_chunks: Iterable[dict[str, Any]] = (),
    *,
    market_facts: Iterable[dict[str, Any]] = (),
    llm: Optional[LLMClient] = None,
    feedback: Iterable[str] = (),
) -> tuple[Insight, dict[str, Any]]:
    """Same as analyze_event, plus call metadata (model, attempts, usage) for the agent trace."""
    if not event.get("event_id") or not event.get("title"):
        raise ValueError("Событие должно содержать event_id и title")

    evidence = [
        *event_evidence(event),
        *company_evidence(context),
        *bank_evidence(bank_chunks),
        *market_evidence(market_facts),
    ]
    missing_data = (context.get("data_quality") or {}).get("missing_fields", [])

    payload = {
        "company": _compact_company(context),
        "event": _event_for_prompt(event),
        "relevance": _relevance_for_prompt(relevance),
        "evidence": [
            {
                "id": item.id,
                "type": item.type,
                "source_kind": item.source_kind,
                # Текст статьи — длиннее остальных фрагментов: ради него он и загружался.
                "text": clip(item.text, ARTICLE_TEXT_LIMIT if item.id == "event.text" else EVIDENCE_TEXT_LIMIT),
            }
            for item in evidence
        ],
        "missing_data": missing_data,
    }

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": build_analyst_prompt()},
        {
            "role": "user",
            "content": compact_json(payload),
        },
    ]
    feedback = [item for item in feedback if item]
    if feedback:
        messages.append(
            {
                "role": "user",
                "content": REVISION_PROMPT.format(
                    issues="\n".join(f"- {item}" for item in feedback)
                ),
            }
        )

    result = (llm or get_llm_client()).chat_json(
        messages,
        InsightDraft,
        task="analyze_event_revision" if feedback else "analyze_event",
        role="analyze",
        max_tokens=4000,
        # Пересмотр с теми же замечаниями иначе вернул бы из кеша тот же ответ.
        use_cache=not feedback,
        validate=lambda draft: _repaired_errors(draft, evidence),
        # Две попытки исправления: ответ без анализа хуже лишнего запроса за доли рубля.
        max_repairs=2,
    )

    draft = result.value.model_dump()
    if isinstance(relevance.get("score"), int):
        # Балл и уровень — из объяснимого скоринга (как в ленте), чтобы цифры не расходились.
        draft["relevance"]["score"] = relevance["score"]
        draft["relevance"]["level"] = relevance["level"] if relevance.get("level") in {"high", "medium"} else "low"

    insight = Insight(
        **draft,
        insight_id=uuid.uuid4().hex,
        company_id=str(context.get("company_id")),
        event_id=str(event["event_id"]),
        evidence=evidence,
        model=result.model,
        created_at=datetime.now(timezone.utc).isoformat(),
        quality_status="unverified",
    )
    meta = {
        "model": result.model,
        "cached": result.cached,
        "attempts": result.attempts,
        "usage": result.usage,
    }
    return insight, meta
