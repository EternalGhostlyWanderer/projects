"""Роли пользователей компании (вебинар, вопросы 31 и 56).

Сервис работает с людьми, а не с юрлицом: у одной компании несколько пользователей,
и у финдиректора, бухгалтера и собственника разные задачи. Роль меняет порядок ленты
(и может добавить события, важные для любой компании в этой роли) и акценты ответов чата.
Выводы о самой компании от роли не зависят: разбор агента общий для всех её пользователей.
"""
from typing import Literal, Optional, get_args

Role = Literal["owner", "ceo", "cfo", "accountant", "treasury", "other"]
ROLES: tuple[str, ...] = get_args(Role)

ROLE_LABELS = {
    "owner": "Собственник",
    "ceo": "Генеральный директор",
    "cfo": "Финансовый директор",
    "accountant": "Главный бухгалтер",
    "treasury": "Казначейство",
    "other": "Другая роль",
}

# Для подсказки модели в чате: какие задачи у роли.
ROLE_FOCUS = {
    "owner": "собственник: стоимость бизнеса, риски для капитала, стратегические решения",
    "ceo": "генеральный директор: операционные последствия, сроки, решения по проектам",
    "cfo": "финансовый директор: стоимость долга, ликвидность, бюджет, финансовые показатели",
    "accountant": "главный бухгалтер: расчёты, документы, налоги, сроки платежей",
    "treasury": "казначейство: платежи, валюты, остатки, размещение средств, ставки",
    "other": "сотрудник, влияющий на решения",
}

# Баллы группы «Задачи роли» (до ROLE_MAX) по типу события и каналам влияния.
# Берётся лучший совпавший признак, как в остальных группах скоринга.
ROLE_MAX = 15
ROLE_EVENT_POINTS: dict[str, dict[str, int]] = {
    "owner": {"sanctions": 15, "industry": 12, "company": 12, "trade": 8, "regulation": 6},
    "ceo": {"industry": 12, "logistics": 12, "sanctions": 10, "regulation": 8, "company": 8},
    "cfo": {"monetary_policy": 15, "inflation": 10, "currency": 10, "taxes": 10, "financial_markets": 8},
    "accountant": {"taxes": 15, "regulation": 12},
    "treasury": {"currency": 15, "monetary_policy": 12, "financial_markets": 10},
    "other": {},
}
ROLE_CHANNEL_POINTS: dict[str, dict[str, int]] = {
    "owner": {"revenue": 10, "industry": 10},
    "ceo": {"supply_chain": 12, "revenue": 10, "industry": 8},
    "cfo": {"interest_rate": 15, "leasing_cost": 12, "inflation": 10, "currency": 10},
    "accountant": {"regulation": 12},
    "treasury": {"currency": 15, "deposit_yield": 12, "interest_rate": 10, "international_trade": 8},
    "other": {},
}
ROLE_TOPICS = {
    "monetary_policy": "ключевая ставка",
    "inflation": "инфляция",
    "currency": "валютный курс",
    "taxes": "налоги",
    "regulation": "регулирование",
    "sanctions": "санкции",
    "industry": "отрасль",
    "company": "компании рынка",
    "trade": "внешняя торговля",
    "logistics": "логистика",
    "financial_markets": "финансовые рынки",
    "interest_rate": "стоимость кредитов",
    "leasing_cost": "стоимость лизинга",
    "deposit_yield": "доходность размещения",
    "international_trade": "внешнеторговые платежи",
    "revenue": "спрос и выручка",
    "supply_chain": "цепочка поставок",
}
# События, важные любой компании для этой роли, даже без связи с её продуктами и отраслью:
# закон о налогах бухгалтер должен увидеть, даже если у компании нет кредитов и ВЭД.
# Только общие события (без отраслей): «требования к застройщикам» бухгалтеру ритейлера не нужны.
ROLE_UNIVERSAL: dict[str, set[str]] = {
    "accountant": {"taxes", "regulation"},
    "cfo": {"taxes", "monetary_policy"},
    "treasury": {"currency", "monetary_policy"},
}


def normalize_role(value: Optional[str]) -> Optional[str]:
    """Роль из заголовка или параметра: неизвестная или пустая — без роли."""
    role = (value or "").strip().casefold()
    return role if role in ROLES else None


def role_match(role: Optional[str], event_type: Optional[str], channels: set[str]) -> Optional[tuple[int, str]]:
    """Лучшее совпадение события с задачами роли: (баллы до ROLE_MAX, причина)."""
    if not role:
        return None
    options: list[tuple[int, str]] = []
    if event_type and event_type in ROLE_EVENT_POINTS.get(role, {}):
        options.append((ROLE_EVENT_POINTS[role][event_type], ROLE_TOPICS.get(event_type, event_type)))
    for channel in channels:
        points = ROLE_CHANNEL_POINTS.get(role, {}).get(channel)
        if points:
            options.append((points, ROLE_TOPICS.get(channel, channel)))
    if not options:
        return None
    points, topic = max(options, key=lambda option: option[0])
    return min(points, ROLE_MAX), f"{ROLE_LABELS[role].lower()}: {topic}"


def is_universal_for_role(role: Optional[str], event_type: Optional[str], event_codes: set[str]) -> bool:
    return bool(role and event_type and not event_codes and event_type in ROLE_UNIVERSAL.get(role, set()))
