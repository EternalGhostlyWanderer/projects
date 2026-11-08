"""Role layer of an insight: «what it means for you» for the person who looks at it.

Разбор события общий для компании (его дорого считать на каждого сотрудника), но читают его
разные люди: финдиректору важны стоимость долга и ликвидность, бухгалтеру — расчёты, налоги и
сроки, собственнику — капитал и стратегия (задание: сервис для людей, а не для юрлиц).
Ролевой слой — короткий отдельный запрос к модели поверх готового разбора:
- 2–3 вывода с акцентом на задачи роли, только из доказательств разбора;
- свой порядок рисков и свои следующие шаги.
Результат хранится по паре «разбор × роль». Без LLM (нет ключа, исчерпан бюджет) — правила:
риски и шаги, в которых есть слова задач роли, поднимаются наверх.
"""
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import Claim, Insight, Level, NextStep
from app.ai.textcheck import extract_numbers
from app.llm import LLMClient, LLMError, get_llm_client
from app.llm.compact import EVIDENCE_TEXT_LIMIT, compact_json
from app.llm.config import LLMConfigError
from app.llm.parsing import schema_for_prompt
from app.modules.personalization.roles import ROLE_FOCUS, ROLE_LABELS, normalize_role

logger = logging.getLogger(__name__)

# Слова задач роли: по ним правила выбирают, какие риски и шаги показать первыми.
ROLE_KEYWORDS = {
    "owner": r"капитал|стоимост\w* бизнес|дивиденд|стратег|инвест|собственник|групп|доля рынка|лидер",
    "ceo": r"операцион|проект|срок|поставк|логистик|производств|персонал|клиент|контрагент|рынок",
    "cfo": r"долг|кредит|ставк|ликвидн|бюджет|рефинанс|процент|финансир|лизинг|ковенант|маржа",
    "accountant": r"налог|отчётн|отчетн|документ|расчёт|расчет|платеж|срок|начислен|закон|требовани",
    "treasury": r"валют|курс|остат|размещ|депозит|платеж|юан|доллар|хедж|ставк|ликвидн",
    "other": r"риск|возможност",
}


class RoleViewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=300, description="Главное для этой роли одной фразой")
    points: list[Claim] = Field(min_length=1, max_length=3, description="2–3 вывода с акцентом на задачи роли")
    risk_order: list[str] = Field(default_factory=list, description="Названия рисков разбора в порядке важности для роли")
    next_steps: list[NextStep] = Field(default_factory=list, max_length=3, description="Шаги именно для этой роли")


class RoleView(BaseModel):
    insight_id: str
    role: str
    role_label: str
    headline: str
    points: list[Claim]
    risk_order: list[str]
    next_steps: list[NextStep]
    method: Literal["llm", "rules"]
    created_at: str
    issues: list[str] = Field(default_factory=list)


ROLE_PROMPT = """
Ты готовишь для конкретного сотрудника компании блок «Что это значит для вас» к готовому разбору
события сервиса Альфа Сигнал. Роль сотрудника: {role_focus}.
Используй только разбор (insight) и его evidence. Ничего не добавляй от себя: ни новых чисел,
ни новых фактов. FACT и BANK_ANALYSIS — только со ссылками на evidence_ids из разбора, свои выводы —
AI_INFERENCE, предположения — HYPOTHESIS.
- headline — одна фраза: что событие значит для задач этой роли;
- points — 2–3 вывода с акцентом на задачи роли;
- risk_order — названия рисков разбора (как в insight.risks[].title) в порядке важности для роли;
- next_steps — до трёх шагов, которые делает именно эта роль (не общие советы).
Пиши по-русски, кратко. Не упоминай слова evidence, insight, JSON.
Верни JSON по схеме:
{schema}
""".strip()


def _known_numbers(insight: Insight) -> set[str]:
    known: set[str] = set()
    for item in insight.evidence:
        known |= extract_numbers(item.text)
    for claim in insight.claims():
        known |= extract_numbers(claim.text)
    return known


def check_role_view(draft: RoleViewDraft, insight: Insight) -> list[str]:
    """Ролевой блок не добавляет ничего нового: ссылки и числа — только из разбора."""
    errors: list[str] = []
    known_ids = {item.id for item in insight.evidence}
    for claim in draft.points:
        unknown = [evidence_id for evidence_id in claim.evidence_ids if evidence_id not in known_ids]
        if unknown:
            errors.append(f"Ссылки на несуществующие доказательства: {', '.join(unknown)}")
    known = _known_numbers(insight)
    texts = [draft.headline, *(claim.text for claim in draft.points), *(step.action for step in draft.next_steps)]
    invented = {number for text in texts for number in extract_numbers(text)} - known - {str(n) for n in range(4)}
    invented = {number for number in invented if not re.fullmatch(r"(19|20)\d\d", number)}
    if invented:
        errors.append(f"Числа, которых нет в разборе: {', '.join(sorted(invented))}")
    titles = {risk.title for risk in insight.risks}
    if any(title not in titles for title in draft.risk_order):
        errors.append("risk_order должен состоять из названий рисков разбора")
    return errors


HEADLINE_MAX = 300


def _matches(role: str, text: str) -> int:
    return len(re.findall(ROLE_KEYWORDS.get(role, ROLE_KEYWORDS["other"]), text, re.IGNORECASE))


def rules_view(insight: Insight, role: str) -> RoleViewDraft:
    """Без LLM: что из разбора относится к задачам роли — наверх."""
    risks = sorted(insight.risks, key=lambda risk: -_matches(role, f"{risk.title} {risk.text}"))
    steps = sorted(insight.next_steps, key=lambda step: -_matches(role, step.action))
    relevant = [risk for risk in risks if _matches(role, f"{risk.title} {risk.text}")] or risks[:1]
    points = [
        Claim(text=risk.text, basis=risk.basis, evidence_ids=risk.evidence_ids, confidence=risk.confidence)
        for risk in relevant[:2]
    ] or [insight.primary_effect]
    headline = f"{ROLE_LABELS[role]}: {insight.primary_effect.text}"
    if len(headline) > HEADLINE_MAX:
        # Длинный главный эффект не должен ронять ролевой блок: обрезаем по слову.
        headline = headline[: HEADLINE_MAX - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return RoleViewDraft(
        headline=headline,
        points=points,
        risk_order=[risk.title for risk in risks],
        next_steps=steps[:3],
    )


def llm_available() -> bool:
    """Есть ли ключ LLM: без него ролевой блок собирается только по правилам."""
    try:
        get_llm_client()
    except (LLMConfigError, LLMError):
        return False
    return True


def build_role_view(insight: Insight, role: Optional[str], *, llm: Optional[LLMClient] = None) -> RoleView:
    role = normalize_role(role) or "cfo"
    method: Literal["llm", "rules"] = "llm"
    issues: list[str] = []
    if not role_view_llm_enabled():
        draft = rules_view(insight, role)
        return _role_view(insight, role, draft, "rules", ["Ролевой блок собран по правилам (ROLE_VIEW_LLM=0)"])
    # Модели нужны только доказательства, на которые ссылается разбор, и в сокращённом виде.
    referenced = insight.referenced_evidence_ids()
    payload = {
        "role": ROLE_LABELS[role],
        "insight": insight.model_dump(
            mode="json",
            include={"primary_effect", "mechanism", "risks", "opportunities", "scenarios", "bank_view", "next_steps", "decision_question"}
        ),
        "evidence": [
            {"id": item.id, "type": item.type, "text": item.text}
            for item in insight.evidence
            if item.id in referenced
        ],
    }
    messages = [
        {"role": "system", "content": ROLE_PROMPT.format(role_focus=ROLE_FOCUS[role], schema=schema_for_prompt(RoleViewDraft))},
        {"role": "user", "content": _json(payload)},
    ]
    try:
        draft = (llm or get_llm_client()).chat_json(
            messages,
            RoleViewDraft,
            task="role_view",
            role="analyze",
            max_tokens=1500,
            validate=lambda value: check_role_view(value, insight),
        ).value
    except (LLMError, LLMConfigError) as exc:
        logger.info("Ролевой блок по правилам: %s", exc)
        draft, method = rules_view(insight, role), "rules"
        issues.append(f"Ролевой блок собран по правилам: {exc}")
    return _role_view(insight, role, draft, method, issues)


def role_view_llm_enabled() -> bool:
    """ROLE_VIEW_LLM=0 — ролевой блок по правилам, без отдельного запроса к LLM на каждый разбор."""
    return os.getenv("ROLE_VIEW_LLM", "1").strip() != "0"


def _role_view(
    insight: Insight, role: str, draft: RoleViewDraft, method: Literal["llm", "rules"], issues: list[str]
) -> RoleView:
    return RoleView(
        insight_id=insight.insight_id,
        role=role,
        role_label=ROLE_LABELS[role],
        headline=draft.headline,
        points=draft.points,
        risk_order=draft.risk_order,
        next_steps=draft.next_steps,
        method=method,
        created_at=datetime.now(timezone.utc).isoformat(),
        issues=issues,
    )


def _json(value: Any) -> str:
    return compact_json(value, max_text=EVIDENCE_TEXT_LIMIT)


__all__ = ["RoleView", "RoleViewDraft", "build_role_view", "check_role_view", "rules_view", "Level"]
