"""Groups of companies, links through people and industries of payment counterparties.

По ответам организаторов (вебинар): GROUP_ID объединяет компании по владению и управлению;
крупный бизнес определяется по выручке группы; событие в одной компании группы может быть
значимо для остальных. Связь через общее физлицо и платежи — косвенные: тип отношений по ним
не определить, поэтому они помечаются как гипотезы с уровнем уверенности.
"""
import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from app.modules.companies.relationships import RelationshipDataError, get_company_relationships
from app.modules.companies.repository import CompanyDataError, get_all_companies, get_company_index
from app.schemas.company import Company

PROJECT_ROOT = Path(__file__).resolve().parents[4]
# Путь можно переопределить переменной окружения PEOPLE_CSV (относительный — от корня репозитория).
PEOPLE_CSV = PROJECT_ROOT / (
    os.getenv("PEOPLE_CSV") or Path("data") / "raw" / "df_Fid_Uid_link_hack.csv"
)

LARGE_BUSINESS_REVENUE_RUB = 15e9
# Физлицо, связанное с десятками компаний, — скорее массовый руководитель или артефакт данных,
# а не признак реальной связи: такие связи не используем.
MAX_COMPANIES_PER_PERSON = 10
MAX_RELATED = 10
# Выручка 1000 руб. — техническая заглушка организаторов, а не подтверждённая выручка.
REVENUE_PLACEHOLDER = 1000


def clean_revenue(value: Optional[float]) -> Optional[float]:
    if value is None or value == REVENUE_PLACEHOLDER or value <= 0:
        return None
    return value


def okved_class(code: Optional[str]) -> Optional[str]:
    """Класс ОКВЭД — первые две цифры: «46.72» → «46»."""
    if not code:
        return None
    head = code.strip().split(".")[0]
    return head if head.isdigit() else None


@lru_cache(maxsize=1)
def _groups() -> dict[str, tuple[str, ...]]:
    groups: dict[str, list[str]] = {}
    for company in get_all_companies():
        if company.group_id:
            groups.setdefault(company.group_id, []).append(company.id)
    return {group_id: tuple(ids) for group_id, ids in groups.items()}


def group_summary(company: Company) -> dict[str, Any]:
    """Выручка и состав группы; без группы компания считается группой из одной себя."""
    try:
        index = get_company_index()
        member_ids = _groups().get(company.group_id, (company.id,)) if company.group_id else (company.id,)
        members = [index[member_id] for member_id in member_ids if member_id in index] or [company]
    except CompanyDataError:
        members = [company]
    revenues = [clean_revenue(member.revenue) for member in members]
    known = [value for value in revenues if value is not None]
    revenue = sum(known) if known else None
    return {
        "group_id": company.group_id,
        "company_count": len(members),
        "revenue_rub": revenue,
        "revenue_complete": len(known) == len(members),
        "large_business": revenue is not None and revenue >= LARGE_BUSINESS_REVENUE_RUB,
    }


@lru_cache(maxsize=1)
def _people_links() -> tuple[dict[str, frozenset[str]], dict[str, frozenset[str]]]:
    """company_id → физлица и физлицо → компании (дубли строк схлопываются)."""
    if not PEOPLE_CSV.is_file():
        return {}, {}
    by_company: dict[str, set[str]] = {}
    by_person: dict[str, set[str]] = {}
    with PEOPLE_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            person = (row.get("SYNTHETIC_F") or "").strip()
            company = (row.get("SYNTHETIC_U") or "").strip()
            if person and company:
                by_company.setdefault(company, set()).add(person)
                by_person.setdefault(person, set()).add(company)
    return (
        {key: frozenset(value) for key, value in by_company.items()},
        {key: frozenset(value) for key, value in by_person.items()},
    )


def _brief(company: Company) -> dict[str, Any]:
    return {
        "company_id": company.id,
        "okved_code": company.main_okved_code,
        "okved_name": company.main_okved_name,
        "region": company.region,
    }


def related_companies(company: Company) -> list[dict[str, Any]]:
    """Компании группы (подтверждённая связь) и связанные через общее физлицо (гипотеза)."""
    index = get_company_index()
    related: dict[str, dict[str, Any]] = {}

    if company.group_id:
        for member_id in _groups().get(company.group_id, ()):
            if member_id != company.id and member_id in index:
                related[member_id] = {
                    **_brief(index[member_id]),
                    "link": "group",
                    "certainty": "confirmed",
                    "basis": f"общая группа компаний {company.group_id}",
                }

    by_company, by_person = _people_links()
    for person in sorted(by_company.get(company.id, ())):
        companies = by_person.get(person, frozenset())
        if len(companies) > MAX_COMPANIES_PER_PERSON:
            continue
        for other_id in sorted(companies):
            if other_id == company.id or other_id in related or other_id not in index:
                continue
            related[other_id] = {
                **_brief(index[other_id]),
                "link": "shared_person",
                "certainty": "hypothesis",
                "basis": f"общее связанное физлицо {person}",
            }

    ordered = sorted(related.values(), key=lambda item: (item["certainty"] != "confirmed", item["company_id"]))
    return ordered[:MAX_RELATED]


def counterparty_industries(company_id: str) -> dict[str, Any]:
    """Доли платежей по отраслям контрагентов (класс ОКВЭД), без переводов самой себе.

    Контрагент без профиля в таблице компаний учитывается как «отрасль неизвестна»:
    восстанавливать его профиль нельзя (ответ организаторов).
    """
    try:
        edges = get_company_relationships(company_id, direction="both", limit=None)
    except RelationshipDataError:
        return {"status": "unavailable", "industries": [], "unknown_share": None}

    index = get_company_index()
    total = sum(edge["amount"] for edge in edges)
    if total <= 0:
        return {"status": "no_payments", "industries": [], "unknown_share": None}

    shares: dict[tuple[str, str], dict[str, Any]] = {}
    unknown = 0.0
    for edge in edges:
        counterparty = index.get(edge["counterparty_id"])
        code = okved_class(counterparty.main_okved_code) if counterparty else None
        if code is None:
            unknown += edge["amount"]
            continue
        item = shares.setdefault(
            (code, edge["direction"]),
            {
                "okved_class": code,
                "example_name": counterparty.main_okved_name,
                "direction": edge["direction"],
                "amount": 0.0,
            },
        )
        item["amount"] += edge["amount"]

    industries = sorted(
        (
            {**item, "share": round(item["amount"] / total, 4)}
            for item in shares.values()
        ),
        key=lambda item: item["amount"],
        reverse=True,
    )
    return {
        "status": "available",
        "industries": industries,
        "unknown_share": round(unknown / total, 4),
        "certainty": "hypothesis",
        "note": "Платёж показывает финансовое взаимодействие, но не его характер.",
    }


def clear_links_cache() -> None:
    _groups.cache_clear()
    _people_links.cache_clear()
