"""Read-only tools the agent may call. Every tool works within the company of the request."""
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.modules.companies.relationships import RelationshipDataError
from app.modules.news.sources import cbr
from app.modules.news.sources.article import FULL_TEXT_CHARS, ArticleFetchError, fetch_article
from app.modules.personalization.context import build_personalization_context
from app.modules.personalization.relevance import assess_relevance
from app.research.forecasts import describe, relevant_forecasts
from app.research.search import bank_forecasts, search_bank_research
from app.schemas.event import NewsEvent

MAX_BANK_RESULTS = 5
MAX_GROUP_MEMBERS = 5


class ToolError(Exception):
    """Инструмент не смог выполниться; агент продолжает без его результата."""


@dataclass
class AgentState:
    """Shared context of one analysis: what the previous steps found."""

    company_id: str
    event: NewsEvent
    context: Optional[dict[str, Any]] = None
    relevance: Optional[dict[str, Any]] = None
    bank_chunks: list[dict[str, Any]] = field(default_factory=list)
    bank_searched: bool = False
    bank_queries: list[str] = field(default_factory=list)
    group: Optional[dict[str, Any]] = None
    user_data: dict[str, Any] = field(default_factory=dict)
    forecasts: list[dict[str, Any]] = field(default_factory=list)
    market_facts: list[dict[str, Any]] = field(default_factory=list)
    # Полный текст статьи загружен в ходе разбора: вызывающий сохраняет его в событии (без повторной загрузки).
    article_fetched: bool = False

    def event_dict(self) -> dict[str, Any]:
        return self.event.model_dump(mode="json")


@dataclass
class ToolResult:
    summary: str
    evidence_ids: list[str] = field(default_factory=list)


class NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BankSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=3, max_length=300, description="Поисковый запрос по-русски")
    channels: list[str] = Field(default_factory=list, description="Каналы влияния события")
    top_k: int = Field(default=3, ge=1, le=MAX_BANK_RESULTS)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[AgentState, Any], ToolResult]


def _get_company_profile(state: AgentState, _: NoArgs) -> ToolResult:
    context = build_personalization_context(state.company_id, state.user_data)
    if context is None:
        raise ToolError(f"Компания {state.company_id} не найдена")
    state.context = context

    profile = context["company_profile"]
    products = [name for name, enabled in (profile.get("products") or {}).items() if enabled]
    factors = [item["factor"] for item in context.get("sensitivity_factors", [])]
    missing = context.get("data_quality", {}).get("missing_fields", [])
    return ToolResult(
        summary=(
            f"Отрасль: {(profile.get('industry') or {}).get('name') or 'нет данных'}; "
            f"продукты: {', '.join(products) or 'нет'}; "
            f"факторы чувствительности: {', '.join(factors) or 'нет'}; "
            f"платежи: {context['payment_exposures'].get('status')}; "
            f"пропуски: {', '.join(missing) or 'нет'}"
        )
    )


def _get_company_relations(state: AgentState, _: NoArgs) -> ToolResult:
    if state.context is None:
        _get_company_profile(state, NoArgs())

    context = state.context or {}
    payments = context.get("payment_exposures") or {}
    profile = context.get("company_profile") or {}
    related = context.get("related_companies") or []
    counterparties = context.get("counterparty_industries") or {}
    state.group = {
        **(profile.get("group") or {"group_id": profile.get("group_id")}),
        "related": related[:MAX_GROUP_MEMBERS],
        "counterparties": counterparties,
    }

    confirmed = sum(1 for item in related if item["certainty"] == "confirmed")
    parts = [
        f"группа: {profile.get('group_id') or 'нет'}, компаний группы рядом: {confirmed}, "
        f"связей-гипотез через физлиц: {len(related) - confirmed}"
    ]
    if payments.get("status") == "available":
        for direction in ("incoming", "outgoing"):
            summary = payments.get(direction) or {}
            parts.append(
                f"{direction}: контрагентов {summary.get('counterparty_count')}, "
                f"концентрация {summary.get('concentration')}"
            )
    else:
        parts.append("платёжные данные недоступны")
    top = (counterparties.get("industries") or [])[:3]
    if top:
        parts.append(
            "отрасли контрагентов: "
            + ", ".join(f"{item['okved_class']} ({item['direction']}, {item['share']:.0%})" for item in top)
        )
    return ToolResult(summary="; ".join(parts))


def _assess_relevance(state: AgentState, _: NoArgs) -> ToolResult:
    if state.context is None:
        _get_company_profile(state, NoArgs())
    state.relevance = assess_relevance(state.context, state.event_dict())  # type: ignore[arg-type]
    matched = state.relevance["matched_factors"]
    return ToolResult(
        summary=(
            f"Балл {state.relevance['score']}/100 ({state.relevance['level']}): "
            f"{state.relevance['explanation']}; совпавшие факторы: {', '.join(matched) or 'нет'}"
        )
    )


def _search_bank(state: AgentState, args: BankSearchArgs) -> ToolResult:
    try:
        results = search_bank_research(args.query, args.channels, top_k=args.top_k)
    except (OSError, ValueError) as exc:
        raise ToolError(f"Индекс аналитики банка недоступен: {exc}") from exc

    state.bank_searched = True
    state.bank_queries.append(args.query)
    known = {chunk["chunk_id"] for chunk in state.bank_chunks}
    new = [chunk for chunk in results if chunk["chunk_id"] not in known]
    state.bank_chunks.extend(new)

    if not results:
        return ToolResult(summary=f"По запросу «{args.query}» материалов банка не найдено")
    titles = "; ".join(f"{chunk['doc_title']}, стр. {chunk['page']}" for chunk in results)
    return ToolResult(
        summary=f"Найдено фрагментов: {len(results)} (новых {len(new)}): {titles}",
        evidence_ids=[f"bank.{chunk['chunk_id']}" for chunk in new],
    )


def forecast_chunk(entry: dict[str, Any]) -> dict[str, Any]:
    """Прогноз как фрагмент аналитики: ссылается на страницу свежего документа."""
    latest = entry["latest"]
    return {
        "chunk_id": f"{latest['doc_id']}-p{latest['page']}-fc-{entry['indicator']}-{entry['period']}",
        "doc_id": latest["doc_id"],
        "doc_title": latest["doc_title"],
        "doc_date": latest["doc_date"],
        "page": latest["page"],
        "text": describe(entry),
    }


def _bank_forecasts(state: AgentState, _: NoArgs) -> ToolResult:
    """Актуальные прогнозы банка по каналам события; пересмотренные — с прежним значением."""
    try:
        table = bank_forecasts()
    except (OSError, ValueError) as exc:
        raise ToolError(f"Прогнозы банка недоступны: {exc}") from exc
    entries = relevant_forecasts(table, state.event.impact_channels)
    state.forecasts = entries
    if not entries:
        return ToolResult(summary="Прогнозов банка по каналам этого события в таблицах обзоров нет")

    chunks = [forecast_chunk(entry) for entry in entries]
    known = {chunk["chunk_id"] for chunk in state.bank_chunks}
    state.bank_chunks.extend(chunk for chunk in chunks if chunk["chunk_id"] not in known)
    revised = [entry for entry in entries if entry["revised"]]
    summary = f"Прогнозов: {len(entries)}"
    if revised:
        summary += "; пересмотрены: " + "; ".join(
            f"{entry['label']} {entry['period']}: {entry['previous']['value']:g} → {entry['latest']['value']:g}"
            f" ({entry['previous']['doc_date']} → {entry['latest']['doc_date']})"
            for entry in revised
        )
    return ToolResult(summary=summary, evidence_ids=[f"bank.{chunk['chunk_id']}" for chunk in chunks])


# Каналы, для которых нужна фактическая ставка или курс из первоисточника.
MARKET_CHANNELS = {"interest_rate", "deposit_yield", "leasing_cost", "currency", "international_trade", "inflation"}


def _official_rates(state: AgentState, _: NoArgs) -> ToolResult:
    """Текущая ключевая ставка и официальные курсы ЦБ — факты из первоисточника, а не из пересказа."""
    if not cbr.enabled():
        raise ToolError("Официальные данные ЦБ отключены (CBR_DATA_ENABLED=0)")
    try:
        snapshot = cbr.market_snapshot()
    except cbr.CBRDataError as exc:
        raise ToolError(f"Данные ЦБ недоступны: {exc}") from exc
    state.market_facts = cbr.snapshot_facts(snapshot)
    return ToolResult(
        summary="; ".join(fact["text"] for fact in state.market_facts),
        evidence_ids=[fact["id"] for fact in state.market_facts],
    )


# Сколько текста статьи хранить в событии и передавать в анализ.
ARTICLE_CHARS = 6000


def full_text_enabled() -> bool:
    """NEWS_FETCH_FULL_TEXT=0 — разбирать по анонсу из ленты, не загружая статью."""
    return os.getenv("NEWS_FETCH_FULL_TEXT", "1") != "0"


def needs_full_text(event: NewsEvent) -> bool:
    """В ленте только анонс: по нему не всегда можно судить о сути — нужна сама статья."""
    if event.submitted_by is not None or event.content in {"full", "partial", "title_only"}:
        return False  # присланная пользователем новость уже загружена (или это вставленный текст)
    return len(event.text or "") < FULL_TEXT_CHARS


def _full_article(state: AgentState, _: NoArgs) -> ToolResult:
    """Загрузить статью по ссылке события (защита от SSRF — в fetch_article)."""
    event = state.event
    if not needs_full_text(event):
        return ToolResult(summary="Полный текст уже есть")
    try:
        article = fetch_article(str(event.url))
    except ArticleFetchError as exc:
        raise ToolError(f"Статья не загружена, разбор по анонсу: {exc}") from exc
    text = " ".join(article.text.split())[:ARTICLE_CHARS]
    if len(text) <= len(event.summary or ""):
        raise ToolError("На странице нет текста сверх анонса" + (" (платный доступ)" if article.paywalled else ""))
    state.event = event.model_copy(update={"text": text})
    state.article_fetched = True
    note = " — платный доступ, доступен фрагмент" if article.paywalled else ""
    return ToolResult(summary=f"Текст статьи: {len(text)} символов{note}", evidence_ids=["event.text"])


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            name="get_company_profile",
            description="Профиль компании: отрасль, регион, продукты банка, ФТС, платёжные показатели, пропуски данных",
            args_model=NoArgs,
            run=_get_company_profile,
        ),
        Tool(
            name="get_company_relations",
            description="Группа компаний и концентрация платежей по контрагентам",
            args_model=NoArgs,
            run=_get_company_relations,
        ),
        Tool(
            name="assess_relevance",
            description="Совпадения каналов влияния и сущностей события с признаками компании",
            args_model=NoArgs,
            run=_assess_relevance,
        ),
        Tool(
            name="search_bank_research",
            description="Поиск тезисов в аналитике Альфа-Банка; можно повторить с другим запросом",
            args_model=BankSearchArgs,
            run=_search_bank,
        ),
        Tool(
            name="get_bank_forecasts",
            description=(
                "Актуальные прогнозы Альфа-Банка (ставка, инфляция, курс, ВВП) по каналам события; "
                "если банк пересмотрел прогноз, показывает прежнее и новое значение"
            ),
            args_model=NoArgs,
            run=_bank_forecasts,
        ),
        Tool(
            name="get_full_article",
            description="Полный текст статьи по ссылке события, если в ленте был только анонс",
            args_model=NoArgs,
            run=_full_article,
        ),
        Tool(
            name="get_official_rates",
            description=(
                "Текущая ключевая ставка и официальные курсы юаня, доллара и евро по данным Банка России "
                "(cbr.ru) — факты из первоисточника"
            ),
            args_model=NoArgs,
            run=_official_rates,
        ),
    )
}


def tool_catalog() -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "args_schema": tool.args_model.model_json_schema(),
        }
        for tool in TOOLS.values()
    ]


def run_tool(state: AgentState, name: str, raw_args: dict[str, Any]) -> ToolResult:
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"Неизвестный инструмент: {name}")
    args = tool.args_model.model_validate(raw_args or {})
    try:
        return tool.run(state, args)
    except RelationshipDataError as exc:
        raise ToolError(f"Данные компании недоступны: {exc}") from exc
