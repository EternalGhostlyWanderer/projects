"""Deterministic checks of an insight against the evidence the agent collected."""
import re
from datetime import date
from typing import Any, Iterable, Literal, Optional

from pydantic import BaseModel, Field

from app.ai.schemas import Claim, Evidence, Insight
from app.ai.textcheck import extract_numbers, extract_source_numbers
from app.modules.news.corroboration import conflict_numbers
from app.research.search import tokenize

Severity = Literal["error", "warning"]

# Замечания, для исправления которых нужны новые данные, а не только переписанный текст.
NEEDS_TOOLS = {"bank_not_searched"}
# Предупреждения, на которые агент реагирует повторной итерацией.
REVISABLE_WARNINGS = {
    "bank_not_searched",
    "bank_unused",
    "single_company_factor",
    "fact_contains_inference",
    "stale_bank_document",
}
# Коды, которые определяют итоговый статус, если не исправлены после пересмотров.
OUTDATED_CODES = {"outdated_bank_forecast", "outdated_bank_view"}
CONFLICT_CODES = {"disputed_fact"}
# Документ банка считается устаревшим, если по теме события найден документ новее на столько дней.
STALE_DOCUMENT_DAYS = 30
CAVEAT_WORDS = re.compile(r"расход|по данным|по одним|по другим|разн\w+ (цифр|данн|оценк)|уточня|спорн", re.IGNORECASE)
SMALL_NUMBERS = {str(number) for number in range(0, 4)}
# Идентификаторы (U_9250, SYN_001, policy_rate_2026_09_11-p1-05) — не числа из текста, их не проверяем.
IDENTIFIER = re.compile(r"\b[A-Za-z][\w-]*_[\w-]+")
# Коды отрасли — не величины: «ОКВЭД 24, 25», «ОКВЭД 47.11 и 47.19».
OKVED_CODES = re.compile(
    r"ОКВЭД\s*\d{2}(?:\.\d{1,2}){0,2}\b(?:\s*(?:,|и|или|/)\s*\d{2}(?:\.\d{1,2}){0,2}\b(?!\s*(?:%|млн|млрд|тыс|руб)))*",
    re.IGNORECASE,
)
# Год без источника — слабее выдуманной суммы или процента: предупреждаем, но не блокируем.
YEAR = re.compile(r"^(19|20)\d\d$")
MIN_BANK_OVERLAP = 0.35
# Присланная пользователем новость без полного текста: разбор не «проверен», а «частично».
LIMITED_CONTENT = {
    "title_only": "Разбор сделан по одному заголовку: текста новости нет, факты события не сверены со статьёй",
    "partial": "Разбор сделан по фрагменту новости (анонс или платный доступ): детали могли остаться за кадром",
}
INFERENCE_MARKERS = re.compile(
    r"\b(может|могут|зависит|зависят|вероятно|поэтому|следовательно|скорее всего|ожидается)\b",
    re.IGNORECASE,
)
REVENUE_WORD = re.compile(r"выручк", re.IGNORECASE)
REVENUE_DISCLAIMER = re.compile(r"не\s+(равн|являет|означа|отража)", re.IGNORECASE)
# Признаки компании, которые реально персонализируют вывод (регион и численность — слабые).
MEANINGFUL_COMPANY_EVIDENCE = re.compile(
    r"^company\.(product\.|fts|payments\.|revenue|industry|factoring|group|related\.|counterparties|position|user\.)"
)


# Как показатель называют в тексте — чтобы понять, о каком прогнозе утверждение.
INDICATOR_WORDS = {
    "key_rate_end": r"ставк",
    "key_rate_avg": r"ставк",
    "inflation_dec": r"инфляц",
    "inflation_avg": r"инфляц",
    "usd_rub_end": r"курс|доллар|руб",
    "cny_rub_end": r"курс|юан",
    "gdp_growth": r"ввп",
    "retail_growth": r"розниц|торговл|потреблен",
}
# Упоминание старого прогноза допустимо, если он явно назван прежним.
REVISION_WORDS = re.compile(r"ранее|прежн|пересмотр|повысил|понизил|изменил|раньше|до пересмотра", re.IGNORECASE)
# Прогноз не Альфа-Банка: ЦБ, Минфин, аналитики. С прогнозами банка его не сравниваем.
OTHER_FORECASTER = re.compile(
    r"\bцб\b|центробанк|банк\w*\s+росси|регулятор|минфин|минэк|правительств|консенсус|аналитик\w*\s+(?!альфа)",
    re.IGNORECASE,
)
ALFA = re.compile(r"альфа", re.IGNORECASE)
RANGE = re.compile(r"\d+(?:[.,]\d+)?\s*[–—-]\s*\d+(?:[.,]\d+)?")
YEAR_IN_TEXT = re.compile(r"\b20\d{2}\b")


def _repeats_old_forecast(text: str, old: set[str], period: str) -> bool:
    """Утверждение называет прежнее значение прогноза Альфа-Банка на тот же период как текущее."""
    if OTHER_FORECASTER.search(text) and not ALFA.search(text):
        return False
    # Число внутри диапазона («12,5–13,5%») — это не повтор точечного прогноза.
    outside_ranges = RANGE.sub(" ", text)
    if not old & extract_numbers(outside_ranges):
        return False
    years = set(YEAR_IN_TEXT.findall(text))
    return not years or period in years


class Issue(BaseModel):
    code: str
    severity: Severity
    message: str


class VerificationReport(BaseModel):
    passed: bool
    issues: list[Issue] = Field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    def actionable(self) -> list[Issue]:
        return [
            issue
            for issue in self.issues
            if issue.severity == "error" or issue.code in REVISABLE_WARNINGS
        ]


def relabel_inferred_facts(insight: Insight) -> tuple[Insight, list[str]]:
    """FACT с явным выводом («поэтому», «может»…) переводится в AI_INFERENCE кодом.

    Модель повторяет эту ошибку и после замечания, а исправление однозначное — тратить на него
    итерацию незачем. Ссылки на доказательства сохраняются.
    """
    fixed = insight.model_copy(deep=True)
    changed: list[str] = []
    # «Что произошло» (event_summary) по контракту — только FACT: там перемечать нельзя, иначе разбор
    # перестаёт проходить проверку и роняет ленту. Вывод внутри факта события ловит проверка fact_contains_inference.
    summary = {id(claim) for claim in fixed.event_summary}
    for claim in fixed.claims():
        if id(claim) in summary:
            continue
        if claim.basis == "FACT" and INFERENCE_MARKERS.search(claim.text):
            claim.basis = "AI_INFERENCE"
            changed.append(claim.text)
    return fixed, changed


def _days_between(older: str, newer: str) -> Optional[int]:
    try:
        return (date.fromisoformat(newer[:10]) - date.fromisoformat(older[:10])).days
    except ValueError:
        return None


def final_status(report: "VerificationReport") -> str:
    """Итог автоматической проверки: что осталось неисправленным после пересмотров."""
    codes = {issue.code for issue in report.errors}
    if codes & CONFLICT_CODES:
        return "conflicting"
    if codes & OUTDATED_CODES:
        return "outdated"
    warnings = {issue.code for issue in report.issues}
    if "stale_bank_document" in warnings:
        return "outdated"
    if "source_text_limited" in warnings:
        return "partial"
    return "verified" if report.passed else "partial"


def _claim_texts(insight: Insight) -> Iterable[str]:
    for claim in insight.claims():
        yield claim.text
    yield from insight.mechanism
    for scenario in insight.scenarios:
        yield scenario.condition
    for step in insight.next_steps:
        yield step.action
    yield insight.decision_question


def _numbers(text: str) -> set[str]:
    return extract_numbers(OKVED_CODES.sub(" ", IDENTIFIER.sub(" ", text)))


def _known_numbers(insight: Insight, event: dict[str, Any]) -> set[str]:
    texts = [item.text for item in insight.evidence]
    texts += [str(event.get(key) or "") for key in ("title", "summary", "text", "published_at")]
    known: set[str] = set()
    for text in texts:
        known |= extract_source_numbers(OKVED_CODES.sub(" ", IDENTIFIER.sub(" ", text)))
    return known


def _overlap(claim: Claim, evidence_text: str) -> float:
    claim_terms = set(tokenize(claim.text))
    if not claim_terms:
        return 0.0
    return len(claim_terms & set(tokenize(evidence_text))) / len(claim_terms)


def verify_insight(
    insight: Insight,
    *,
    event: dict[str, Any],
    missing_data: Iterable[str] = (),
    bank_searched: bool = True,
    forecasts: Iterable[dict[str, Any]] = (),
) -> VerificationReport:
    by_id: dict[str, Evidence] = {item.id: item for item in insight.evidence}
    issues: list[Issue] = []

    def add(code: str, severity: Severity, message: str) -> None:
        issues.append(Issue(code=code, severity=severity, message=message))

    known = _known_numbers(insight, event)
    invented: set[str] = set()
    for text in _claim_texts(insight):
        invented |= _numbers(text) - known - SMALL_NUMBERS
    years = {number for number in invented if YEAR.match(number)}
    if invented - years:
        add(
            "unsupported_number",
            "error",
            "Числа без источника во входных данных: " + ", ".join(sorted(invented - years)),
        )
    if years:
        add(
            "unsupported_year",
            "warning",
            "Годы без источника во входных данных: " + ", ".join(sorted(years)),
        )

    if not any(
        by_id.get(evidence_id) and by_id[evidence_id].source_kind == "company_data"
        for reason in insight.relevance.reasons
        for evidence_id in reason.evidence_ids
    ):
        add(
            "relevance_without_company_data",
            "error",
            "Причины релевантности не ссылаются ни на один признак компании",
        )

    available = {item.id for item in insight.evidence if MEANINGFUL_COMPANY_EVIDENCE.match(item.id)}
    used = insight.referenced_evidence_ids() & available
    if len(available) >= 2 and len(used) < 2:
        add(
            "single_company_factor",
            "warning",
            "Использован один признак компании, хотя доступны: " + ", ".join(sorted(available)),
        )

    bank_ids = {item.id for item in insight.evidence if item.source_kind == "bank_research"}
    if not bank_searched:
        add(
            "bank_not_searched",
            "warning",
            "Аналитика Альфа-Банка не запрашивалась — выполните search_bank_research",
        )
    elif bank_ids and insight.bank_view.status == "not_found":
        add(
            "bank_unused",
            "warning",
            "Найдены материалы банка, но bank_view = not_found: проверьте, относятся ли они к событию",
        )

    for claim in insight.bank_view.claims:
        best = max(
            (_overlap(claim, by_id[evidence_id].text) for evidence_id in claim.evidence_ids if evidence_id in by_id),
            default=0.0,
        )
        if best < MIN_BANK_OVERLAP:
            add(
                "bank_claim_not_supported",
                "error",
                f"Тезис банка «{claim.text[:80]}» не подтверждается текстом процитированного фрагмента",
            )

    for claim in insight.claims():
        cites_payments = any(evidence_id.startswith("company.payments.") for evidence_id in claim.evidence_ids)
        if cites_payments and REVENUE_WORD.search(claim.text) and not REVENUE_DISCLAIMER.search(claim.text):
            add(
                "payments_as_revenue",
                "error",
                f"Утверждение «{claim.text[:80]}» выводит выручку из платёжных данных",
            )
        if claim.basis == "FACT" and INFERENCE_MARKERS.search(claim.text):
            add(
                "fact_contains_inference",
                "warning",
                f"Утверждение «{claim.text[:80]}» помечено FACT, но содержит вывод — нужен AI_INFERENCE",
            )

    # Противоречащие прогнозы: банк пересмотрел прогноз, а вывод повторяет прежнее значение
    # как текущее. Устаревшая позиция банка вводит клиента в заблуждение — это ошибка.
    texts = list(_claim_texts(insight))
    for entry in forecasts:
        previous = entry.get("previous")
        if not entry.get("revised") or not previous:
            continue
        old = extract_numbers(f"{previous['value']:g}")
        words = re.compile(INDICATOR_WORDS.get(entry["indicator"], r"$^"), re.IGNORECASE)
        for text in texts:
            if words.search(text) and not REVISION_WORDS.search(text) and _repeats_old_forecast(text, old, entry["period"]):
                add(
                    "outdated_bank_forecast",
                    "error",
                    f"«{text[:80]}» повторяет прежний прогноз банка ({entry['label']} {entry['period']}: "
                    f"{previous['value']:g} от {previous['doc_date']}); актуальный — {entry['latest']['value']:g} "
                    f"от {entry['latest']['doc_date']}. Используйте актуальный или укажите, что прогноз пересмотрен",
                )
                break

    # Спорная цифра: издания называют разное, а вывод подаёт одно значение как факт.
    disputed = conflict_numbers(insight.evidence)
    if disputed:
        for claim in insight.claims():
            numbers = {number.replace(",", ".") for number in extract_numbers(claim.text)}
            if claim.basis == "FACT" and numbers & disputed and not CAVEAT_WORDS.search(claim.text):
                add(
                    "disputed_fact",
                    "error",
                    f"«{claim.text[:80]}» подаёт спорную цифру как факт: издания расходятся "
                    f"(event.conflict.*). Назовите оба значения или укажите, что источники расходятся",
                )
                break

    # Позиция банка из старого документа, когда по теме события найден более свежий.
    bank_dates = {
        item.id: item.source_date
        for item in insight.evidence
        if item.source_kind == "bank_research" and item.source_date
    }
    cited = {
        evidence_id
        for claim in insight.bank_view.claims
        for evidence_id in claim.evidence_ids
        if evidence_id in bank_dates
    }
    if cited and bank_dates:
        newest = max(bank_dates.values())
        cited_newest = max(bank_dates[evidence_id] for evidence_id in cited)
        lag = _days_between(cited_newest, newest)
        if lag is not None and lag >= STALE_DOCUMENT_DAYS:
            newer_title = next(
                (item.source_title for item in insight.evidence if item.id in bank_dates and item.source_date == newest),
                "более свежий документ",
            )
            add(
                "stale_bank_document",
                "warning",
                f"Позиция банка взята из документа от {cited_newest}, а по теме найден более свежий "
                f"(«{newer_title}», {newest}, на {lag} дн. новее) — проверьте, не изменилась ли позиция",
            )

    content = event.get("content")
    if content in LIMITED_CONTENT:
        add("source_text_limited", "warning", LIMITED_CONTENT[content])

    missing = [item for item in missing_data if item]
    if missing and not insight.unknowns:
        add(
            "unknowns_missing",
            "warning",
            "В профиле есть пропуски (" + ", ".join(missing) + "), но unknowns пуст",
        )

    return VerificationReport(
        passed=not any(issue.severity == "error" for issue in issues),
        issues=issues,
    )
