"""Position of a company and its group in the industry (task, item 1: «положение в отрасли и долю рынка»).

Рынок целиком в данных нет, поэтому позиция считается **по выборке организаторов**: среди
компаний того же класса ОКВЭД (первые две цифры) с известной выручкой. Это честно называется
«доля в выручке отрасли по данным банка», а не доля рынка. Для группы — то же по сумме выручки
компаний группы в этой отрасли.
"""
from typing import Any, Optional

from app.modules.companies.links import clean_revenue, okved_class
from app.modules.companies.repository import CompanyDataError, get_all_companies
from app.schemas.company import Company

# Меньше стольких компаний с выручкой — позиция ненадёжна, не считаем.
MIN_PEERS = 5
LEADER_TOP_SHARE = 0.1  # топ-10% по выручке — лидер отрасли в выборке
LARGE_TOP_SHARE = 0.25


_cache: dict[int, dict[str, tuple[tuple[str, Optional[str], float], ...]]] = {}


def _industries() -> dict[str, tuple[tuple[str, Optional[str], float], ...]]:
    """Класс ОКВЭД → (компания, группа, выручка) по убыванию выручки.

    Кеш привязан к загруженному набору компаний: при смене CSV (тесты, другие данные) пересчитывается.
    """
    companies = get_all_companies()
    cached = _cache.get(id(companies))
    if cached is not None:
        return cached
    by_class: dict[str, list[tuple[str, Optional[str], float]]] = {}
    for company in companies:
        revenue = clean_revenue(company.revenue)
        code = okved_class(company.main_okved_code)
        if revenue is None or code is None:
            continue
        by_class.setdefault(code, []).append((company.id, company.group_id, revenue))
    result = {code: tuple(sorted(items, key=lambda item: item[2], reverse=True)) for code, items in by_class.items()}
    _cache.clear()
    _cache[id(companies)] = result
    return result


def _tier(rank: int, total: int) -> str:
    share = (rank - 1) / total  # первое место — всегда лидер
    if share <= LEADER_TOP_SHARE:
        return "leader"
    if share <= LARGE_TOP_SHARE:
        return "large"
    return "regular" if share <= 0.75 else "small"


TIER_LABELS = {
    "leader": "один из лидеров отрасли",
    "large": "крупный игрок отрасли",
    "regular": "средний игрок отрасли",
    "small": "небольшой игрок отрасли",
}


def industry_position(company: Company) -> dict[str, Any]:
    code = okved_class(company.main_okved_code)
    revenue = clean_revenue(company.revenue)
    base: dict[str, Any] = {"okved_class": code, "basis": "выборка компаний банка с известной выручкой"}
    if code is None:
        return {**base, "status": "unknown_industry"}
    try:
        peers = _industries().get(code, ())
    except CompanyDataError:
        return {**base, "status": "unavailable"}
    if len(peers) < MIN_PEERS:
        return {**base, "status": "too_few_peers", "peers": len(peers)}
    if revenue is None:
        return {**base, "status": "no_revenue", "peers": len(peers)}

    total = sum(item[2] for item in peers)
    rank = next((index for index, item in enumerate(peers, start=1) if item[0] == company.id), None)
    if rank is None:
        rank = 1 + sum(1 for item in peers if item[2] > revenue)
    tier = _tier(rank, len(peers))
    result = {
        **base,
        "status": "ok",
        "peers": len(peers),
        "rank": rank,
        "percentile": round(100 * (1 - (rank - 1) / len(peers))),
        "share_of_sample": round(revenue / total, 4),
        "tier": tier,
        "tier_label": TIER_LABELS[tier],
    }
    if company.group_id:
        groups: dict[str, float] = {}
        for company_id, group_id, value in peers:
            key = group_id or company_id
            groups[key] = groups.get(key, 0.0) + value
        ordered = sorted(groups.items(), key=lambda item: item[1], reverse=True)
        group_rank = next(index for index, (key, _) in enumerate(ordered, start=1) if key == company.group_id) if company.group_id in groups else None
        if group_rank is not None:
            result["group"] = {
                "rank": group_rank,
                "players": len(ordered),
                "share_of_sample": round(groups[company.group_id] / total, 4),
            }
    return result


def describe_position(position: dict[str, Any]) -> Optional[str]:
    if position.get("status") != "ok":
        return None
    text = (
        f"По выручке {position['rank']}-е место из {position['peers']} компаний отрасли (ОКВЭД {position['okved_class']}) "
        f"в выборке банка — {position['tier_label']}; доля в выручке отрасли по выборке "
        f"{position['share_of_sample'] * 100:.1f}%".replace(".", ",")
    )
    group = position.get("group")
    if group:
        text += (
            f"; группа компаний — {group['rank']}-е место из {group['players']}, доля "
            f"{group['share_of_sample'] * 100:.1f}%".replace(".", ",")
        )
    return text


def clear_position_cache() -> None:
    _cache.clear()
