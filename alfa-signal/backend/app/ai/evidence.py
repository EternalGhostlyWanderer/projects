"""Build the evidence pool the LLM is allowed to cite."""
from typing import Any, Iterable

from app.ai.schemas import Evidence
from app.modules.companies.position import describe_position
from app.modules.companies.user_data import user_data_evidence
from app.modules.news.corroboration import corroborate, describe_confirmed, describe_conflict

PRODUCT_LABELS = {
    "rko": ("CL_PRODUCT_RKO_MARK", "расчётно-кассовое обслуживание"),
    "gar": ("CL_PRODUCT_GAR_MARK", "банковские гарантии"),
    "loa": ("CL_PRODUCT_LOA_MARK", "кредитные продукты"),
    "lea": ("CL_PRODUCT_LEA_MARK", "лизинговые продукты"),
    "dep": ("CL_PRODUCT_DEP_MARK", "депозитные продукты"),
    "zpp": ("CL_PRODUCT_ZPP_MARK", "зарплатный проект"),
}

DIRECTION_LABELS = {
    "incoming": "Входящие платежи",
    "outgoing": "Исходящие платежи",
}


def _company_fact(evidence_id: str, text: str, source_id: str) -> Evidence:
    return Evidence(
        id=evidence_id,
        type="FACT",
        text=text,
        source_kind="company_data",
        source_id=source_id,
        source_title="Профиль компании",
    )


def company_evidence(context: dict[str, Any]) -> list[Evidence]:
    profile = context.get("company_profile") or {}
    items: list[Evidence] = []

    industry = profile.get("industry") or {}
    if industry.get("name"):
        code = f" ({industry['code']})" if industry.get("code") else ""
        items.append(
            _company_fact(
                "company.industry",
                f"Основной вид деятельности: {industry['name']}{code}",
                "MAINOKVED_NAME",
            )
        )

    location = profile.get("location") or {}
    place = ", ".join(value for value in (location.get("city"), location.get("region")) if value)
    if place:
        items.append(_company_fact("company.location", f"Регистрация: {place}", "REGION"))

    financials = profile.get("financials") or {}
    if financials.get("revenue_rub") is not None:
        items.append(
            _company_fact(
                "company.revenue",
                f"Годовая выручка за {financials.get('revenue_year')}: "
                f"{financials['revenue_rub']:.0f} руб.",
                "REVENUE_COMPANY",
            )
        )
    employees = financials.get("employees_fns") or financials.get("employees_spark")
    if employees:
        items.append(
            _company_fact(
                "company.employees",
                f"Численность работников: {employees}",
                "AMOUNT_WORKERS_FNS_GRADATION",
            )
        )

    for key, enabled in (profile.get("products") or {}).items():
        if enabled is True and key in PRODUCT_LABELS:
            source_id, label = PRODUCT_LABELS[key]
            items.append(
                _company_fact(
                    f"company.product.{key}",
                    f"У компании есть {label} в банке",
                    source_id,
                )
            )

    risk = profile.get("risk_indicators") or {}
    if risk.get("fts_data_available") and risk.get("fts_country"):
        items.append(
            _company_fact(
                "company.fts",
                f"По данным ФТС у компании есть внешнеторговая связь со страной: "
                f"{risk['fts_country']}",
                "FTS_COUNTRY_NAME",
            )
        )
    if risk.get("factoring_product"):
        items.append(
            _company_fact(
                "company.factoring",
                "У компании есть факторинговый продукт",
                "FACTORING_MARK",
            )
        )

    group = context.get("group_summary") or {}
    if profile.get("group_id"):
        details = ""
        if group.get("company_count"):
            details = f"; компаний группы в данных: {group['company_count']}"
        if group.get("revenue_rub"):
            details += f"; выручка группы за 2025: {group['revenue_rub']:.0f} руб."
            if not group.get("revenue_complete"):
                details += " (не по всем компаниям группы есть данные)"
        items.append(
            _company_fact(
                "company.group",
                f"Компания входит в группу компаний {profile['group_id']}{details}",
                "GROUP_ID",
            )
        )

    position_text = describe_position(profile.get("industry_position") or {})
    if position_text:
        items.append(_company_fact("company.position", position_text, "REVENUE_COMPANY, MAINOKVED_CODE"))

    # Связи и отрасли контрагентов попадают в доказательства, только если агент вызвал
    # get_company_relations. Связь через физлицо и цепочка поставок по платежам — гипотезы.
    for related in group.get("related") or []:
        prefix = (
            "Компания той же группы"
            if related["certainty"] == "confirmed"
            else "Возможно связанная компания (гипотеза: общее связанное физлицо)"
        )
        items.append(
            Evidence(
                id=f"company.related.{related['company_id']}",
                type="FACT" if related["certainty"] == "confirmed" else "HYPOTHESIS",
                text=f"{prefix} {related['company_id']}: {related.get('okved_name') or 'отрасль не указана'}"
                + (f", {related['region']}" if related.get("region") else ""),
                source_kind="company_data",
                source_id="GROUP_ID" if related["certainty"] == "confirmed" else "df_Fid_Uid_link",
                source_title="Связи компании",
            )
        )

    counterparties = group.get("counterparties") or {}
    top = (counterparties.get("industries") or [])[:4]
    if top:
        labels = {"incoming": "покупатели", "outgoing": "поставщики"}
        parts = [
            f"{labels[item['direction']]} — {item['example_name'] or 'класс ' + item['okved_class']} "
            f"(ОКВЭД {item['okved_class']}): {item['share'] * 100:.0f}%"
            for item in top
        ]
        unknown = counterparties.get("unknown_share")
        tail = f"; отрасль неизвестна у {unknown * 100:.0f}% суммы" if unknown else ""
        items.append(
            Evidence(
                id="company.counterparties",
                type="HYPOTHESIS",
                text="Отрасли контрагентов по сумме платежей (гипотеза о цепочке поставок: "
                "платёж не показывает характер отношений): " + "; ".join(parts) + tail,
                source_kind="company_data",
                source_id="payment_edges",
                source_title="Платежи компании",
            )
        )

    items.extend(user_data_evidence(context.get("user_data") or {}))

    payments = context.get("payment_exposures") or {}
    if payments.get("status") == "available":
        for direction, label in DIRECTION_LABELS.items():
            summary = payments.get(direction) or {}
            if not summary.get("counterparty_count"):
                continue
            share = round(summary.get("top_5_amount_share", 0) * 100)
            items.append(
                _company_fact(
                    f"company.payments.{direction}",
                    f"{label}: контрагентов — {summary['counterparty_count']}, "
                    f"доля пяти крупнейших — {share}% "
                    f"(концентрация: {summary.get('concentration')}). "
                    "Период с 1 января; сумма платежей не равна выручке.",
                    "payment_edges",
                )
            )

    return items


ARTICLE_EVIDENCE_CHARS = 3000


def event_evidence(event: dict[str, Any]) -> list[Evidence]:
    description = event.get("summary") or event.get("description")
    if not description and event.get("text"):
        description = " ".join(str(event["text"]).split())[:600]
    text = event["title"] if not description else f"{event['title']}. {description}"
    source = {
        "source_kind": "news",
        "source_id": event.get("event_id"),
        "source_title": event.get("source") or event.get("title"),
        "source_url": event.get("url"),
        "source_date": str(event["published_at"]) if event.get("published_at") else None,
    }

    items = [Evidence(id="event.main", type="FACT", text=text, **source)]
    # Полный текст статьи (get_full_article или полная RSS-лента): по анонсу не всегда можно судить о сути.
    # У иностранных изданий текст на английском, заголовок и анонс — в переводе (foreign.py).
    article = " ".join(str(event.get("text") or "").split())
    if article and description and len(article) > len(description) + 100:
        items.append(Evidence(id="event.text", type="FACT", text=article[:ARTICLE_EVIDENCE_CHARS], **source))
    for index, fact in enumerate(event.get("facts") or [], start=1):
        items.append(Evidence(id=f"event.fact.{index}", type="FACT", text=fact, **source))
    return items + corroboration_evidence(event)


def corroboration_evidence(event: dict[str, Any]) -> list[Evidence]:
    """Другие публикации о событии — со своим текстом и ссылкой — и сверка цифр между изданиями.

    Текст каждой публикации ссылается на своё издание: цитата не уходит к чужой ссылке.
    """
    items: list[Evidence] = []
    main_url = str(event.get("url") or "")
    for index, publication in enumerate(
        [item for item in event.get("sources") or [] if str(item.get("url")) != main_url], start=1
    ):
        text = publication.get("title") or ""
        if publication.get("summary"):
            text = f"{text}. {publication['summary']}"
        items.append(
            Evidence(
                id=f"event.source.{index}",
                type="FACT",
                text=text,
                source_kind="news",
                source_id=event.get("event_id"),
                source_title=publication.get("source"),
                source_url=publication.get("url"),
                source_date=str(publication["published_at"]) if publication.get("published_at") else None,
            )
        )
    if not items:
        return items

    result = corroborate(event)
    check = {"source_kind": "news", "source_id": event.get("event_id"), "source_title": "Сверка публикаций"}
    for index, confirmed in enumerate(result["confirmed"], start=1):
        items.append(Evidence(id=f"event.confirmed.{index}", type="FACT", text=describe_confirmed(confirmed), **check))
    for index, conflict in enumerate(result["conflicts"], start=1):
        items.append(Evidence(id=f"event.conflict.{index}", type="FACT", text=describe_conflict(conflict), **check))
    return items


def bank_evidence(chunks: Iterable[dict[str, Any]]) -> list[Evidence]:
    return [
        Evidence(
            id=f"bank.{chunk['chunk_id']}",
            type="BANK_ANALYSIS",
            text=chunk["text"],
            source_kind="bank_research",
            source_id=chunk["chunk_id"],
            source_title=chunk.get("doc_title"),
            source_url=chunk.get("doc_url"),
            source_date=chunk.get("doc_date"),
            source_page=chunk.get("page"),
        )
        for chunk in chunks
    ]


def market_evidence(facts: Iterable[dict[str, Any]]) -> list[Evidence]:
    """Официальные ставка и курсы ЦБ (get_official_rates) — подтверждённые факты с источником."""
    return [
        Evidence(
            id=fact["id"],
            type="FACT",
            text=fact["text"],
            source_kind="news",
            source_id=fact["id"],
            source_title="Банк России (официальные данные)",
            source_url=fact.get("url"),
            source_date=fact.get("date"),
        )
        for fact in facts
    ]
