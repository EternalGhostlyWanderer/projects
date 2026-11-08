"""Explainable relevance score 0–100 of an event for a specific company (no LLM).

Балл — сумма пяти групп факторов компании и, если известна роль пользователя, группы
«Задачи роли» (roles.py). Внутри группы берётся максимум, а не сумма, чтобы десяток
похожих совпадений не завышал оценку. Затем каждая группа умножается на значимость события,
поэтому сумма факторов всегда равна итоговому баллу. Описание — docs/scoring.md.
"""
import re
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from app.modules.news.quality import source_trust
from app.modules.personalization.roles import ROLE_MAX, is_universal_for_role, normalize_role, role_match

Certainty = Literal["confirmed", "potential", "hypothesis"]

GROUP_MAX = {
    "industry": 30,
    "channels": 35,
    "geography": 20,
    "supply_chain": 15,
    "related": 10,
    "interests": 15,
    "role": ROLE_MAX,
}
GROUP_LABELS = {
    "industry": "Отрасль компании",
    "channels": "Финансовые каналы",
    "geography": "География",
    "supply_chain": "Цепочка поставок",
    "related": "Связанные компании",
    "interests": "Интересы компании",
    "role": "Задачи роли",
}

# Значимость события: решение ЦБ или санкции касаются всех, новость одной компании — немногих.
SIGNIFICANCE = {
    "monetary_policy": 1.0,
    "sanctions": 1.0,
    "regulation": 0.9,
    "taxes": 0.9,
    "trade": 0.9,
    "currency": 0.9,
    "inflation": 0.85,
    "commodities": 0.85,
    "logistics": 0.8,
    "industry": 0.8,
    "macro_statistics": 0.75,
    "financial_markets": 0.75,
    "company": 0.7,
    "other": 0.6,
}
DEFAULT_SIGNIFICANCE = 0.7

# Макрособытия касаются всех через финансовые каналы. Остальные события с указанными отраслями —
# отраслевые: финансовый канал засчитывается, только если задета отрасль компании, её
# контрагенты или связанные компании (иначе «льготные кредиты аграриям» попадут каждому заёмщику).
# Решение по ставке и комментарий к нему — разные по весу события: «Набиуллина обсудила
# сохранение ставки» или «ЦБ сопроводил сообщение изображением кота» не меняют условий кредита.
RATE_DECISION = re.compile(
    r"(принял\w*\s+решени\w*|сохранил\w*|снизил\w*|повысил\w*|оставил\w*)\s+(\w+\s+){0,2}ключев\w*\s+ставк|"
    r"ключев\w*\s+ставк\w*\s+(\w+\s+){0,2}(сохранен\w*|снижен\w*|повышен\w*)\s+(до|на)\b",
    re.IGNORECASE,
)
RATE_COMMENTARY_SIGNIFICANCE = 0.8
# Заявление без новой меры («Медведев заявил, что Россия вопреки санкциям стоит») и онлайн-трансляции
# не меняют условий бизнеса: тема (санкции, пошлины) есть, а нового решения нет.
STATEMENT = re.compile(
    r"\b(заявил\w*|счита\w*|назвал\w*|высказал\w*|уверен\w*|пообещал\w*|предупредил\w*|прокомментировал\w*|"
    r"призвал\w*|оценил\w*|ответил\w*|раскритиковал\w*|допустил\w*|не исключил\w*)\b",
    re.IGNORECASE,
)
NEW_MEASURE = re.compile(
    r"\b(ввел\w*|ввёл\w*|введ\w*|ввод\w*|запрет\w*|запрети\w*|утверд\w*|расширил\w*|продлил\w*|продлен\w*|пакет\w*|"
    r"пошлин\w*|квот\w*|отмен\w*|снял\w*|подписал\w*|принял\w*|повысил\w*|снизил\w*|сохранил\w*|изменил\w*|"
    r"вступ\w*\s+в\s+силу|с\s+\d{1,2}\s+\w+|\d+([,.]\d+)?\s*(%|процент|млрд|млн))",
    re.IGNORECASE,
)
LIVE_COVERAGE = re.compile(
    r"\bонлайн\s*$|\bонлайн-трансляц|\bхроника\b|главное\s+(за|к)\s+\w+|\bчто\s+известно\b"
    # Анонс: сообщает дату будущего события, а не решение («состоится пресс-конференция»).
    r"|\b(состоится|состоятся|пройд[её]т|пройдут|начнётся|начнется)\b.{0,60}\b(пресс-конференц\w*|заседани\w*|брифинг\w*|форум\w*|совещани\w*)",
    re.IGNORECASE,
)
LOW_INFO_SIGNIFICANCE = 0.3
# Сигналы регулятора о будущих решениях — не пустые заявления (у них свой вес, RATE_COMMENTARY_SIGNIFICANCE).
REGULATOR_SPEAKER = re.compile(r"\b(ЦБ|Банк\w*\s+России|Набиуллин\w*|Заботкин\w*|регулятор\w*)\b", re.IGNORECASE)


def is_low_information(title: str) -> bool:
    """Заявление без новой меры или онлайн-трансляция: тема есть, нового решения нет."""
    title = title.strip()
    if LIVE_COVERAGE.search(title):
        return True
    return bool(STATEMENT.search(title)) and not NEW_MEASURE.search(title) and not REGULATOR_SPEAKER.search(title)
# Второй и следующие финансовые каналы добавляют половину своих баллов (до максимума группы):
# компания с кредитом, лизингом и депозитом зависит от ставки сильнее, чем только с депозитом.
EXTRA_CHANNEL_SHARE = 0.5

MACRO_TYPES = {"monetary_policy", "inflation", "currency", "macro_statistics", "financial_markets", "taxes"}

# Отрасли, выручка которых напрямую зависит от потребительского спроса (классы ОКВЭД).
CONSUMER_CLASSES = {"45", "47", "55", "56", "79", "93", "96"}
MIN_SUPPLY_SHARE = 0.05
# Только цепочка поставок с малой долей — слишком слабое основание, чтобы показывать событие.
MIN_SUPPLY_SHARE_ALONE = 0.10

# Порог показа в ленте: ниже — фоновое влияние (например, инфляция для любого заёмщика).
# 20 — по ручной разметке (отчёт 19): при 10 три из четырёх показанных событий люди оценили как фон,
# при 20 фона на 40% меньше, а важных скрыто столько же (1 из 12); при 25 скрыта уже треть важных.
MIN_FEED_SCORE = 20
# Уровни (вебинар, вопрос 46: шкалу нужно определить): high — событие прямо меняет условия
# бизнеса компании; medium — заметно влияет через один канал; low — косвенное влияние.
LEVELS = ((60, "high"), (30, "medium"), (MIN_FEED_SCORE, "low"))


# Свежесть: в первые сутки вес 1,0, дальше вдвое за неделю, но не ниже 0,3 — важное старое
# событие не пропадает, но вчерашняя новость при близком балле стоит выше месячной.
FRESH_HOURS = 24
HALF_LIFE_DAYS = 7
MIN_FRESHNESS = 0.3
# Очень важное (балл от 60) не опускается ниже середины ленты из-за возраста: старое важное выше свежего фона.
IMPORTANT_SCORE = 60
IMPORTANT_MIN_FRESHNESS = 0.6


def freshness(published_at: Any, now: Optional[datetime] = None) -> dict[str, Any]:
    """Множитель свежести для сортировки ленты; на объяснимый балл 0–100 не влияет."""
    if not published_at:
        # Без даты (вставленный пользователем текст) — считаем событие свежим.
        return {"factor": 1.0, "age_days": None}
    moment = published_at if isinstance(published_at, datetime) else datetime.fromisoformat(str(published_at))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, ((now or datetime.now(timezone.utc)) - moment).total_seconds() / 3600)
    if age_hours <= FRESH_HOURS:
        factor = 1.0
    else:
        factor = max(MIN_FRESHNESS, 0.5 ** ((age_hours - FRESH_HOURS) / 24 / HALF_LIFE_DAYS))
    return {"factor": round(factor, 3), "age_days": round(age_hours / 24, 1)}


def feed_freshness(score: int, published_at: Any, reference: Optional[datetime] = None) -> dict[str, Any]:
    """Свежесть для ленты: возраст отсчитывается от самой новой новости (reference), а не от «сейчас».

    Если свежих новостей давно не поступало, лента не «стареет» целиком: порядок остаётся по важности,
    а старое, но очень важное событие держится наверху.
    """
    fresh = freshness(published_at, now=reference)
    if score >= IMPORTANT_SCORE and fresh["factor"] < IMPORTANT_MIN_FRESHNESS:
        fresh = {**fresh, "factor": IMPORTANT_MIN_FRESHNESS, "important": True}
    return fresh


def _okved_class(code: Optional[str]) -> Optional[str]:
    head = (code or "").strip().split(".")[0]
    return head if head.isdigit() else None


def _countries(value: Optional[str]) -> set[str]:
    return {part.strip().casefold() for part in (value or "").split(",") if part.strip()}


def _best(options: list[tuple[int, str, Certainty]]) -> Optional[tuple[int, str, Certainty]]:
    return max(options, key=lambda option: option[0]) if options else None


def _industry(profile: dict, event_codes: set[str]) -> Optional[tuple[int, str, Certainty]]:
    code = (profile.get("industry") or {}).get("code")
    company_class = _okved_class(code)
    if company_class and company_class in event_codes:
        name = (profile.get("industry") or {}).get("name") or code
        return 30, f"событие касается отрасли компании: {name} (ОКВЭД {company_class})", "confirmed"
    return None


def _company_countries(profile: dict, user: dict) -> set[str]:
    return _countries((profile.get("risk_indicators") or {}).get("fts_country")) | {
        country.casefold() for country in user.get("trade_countries") or []
    }


def _channels(
    profile: dict,
    payments: dict,
    channels: set[str],
    event_countries: set[str],
    user: dict,
    event_type: Optional[str] = None,
) -> Optional[tuple[int, str, Certainty]]:
    products = profile.get("products") or {}
    risk = profile.get("risk_indicators") or {}
    has_fts = bool(risk.get("fts_data_available") and risk.get("fts_country"))
    company_class = _okved_class((profile.get("industry") or {}).get("code"))
    options: list[tuple[int, str, Certainty]] = []

    # Ставка чужого центробанка («ЦБ Турции снизил ставку») не меняет стоимость кредита в рублях.
    if event_type == "monetary_policy" and event_countries:
        channels = channels - {"interest_rate", "leasing_cost", "deposit_yield"}
    if "interest_rate" in channels:
        if products.get("loa"):
            options.append((25, "ставка → у компании кредиты", "potential"))
        if products.get("lea"):
            options.append((20, "ставка → у компании лизинг", "potential"))
        if products.get("dep"):
            options.append((15, "ставка → доходность депозитов компании", "potential"))
    if "leasing_cost" in channels and products.get("lea"):
        options.append((25, "стоимость лизинга → у компании лизинг", "potential"))
    if "deposit_yield" in channels and products.get("dep"):
        options.append((20, "доходность размещения → у компании депозиты", "potential"))
    # Событие про конкретные страны касается внешней торговли компании, только если страны совпадают.
    countries_match = not event_countries or bool(_company_countries(profile, user) & event_countries)
    if "international_trade" in channels and has_fts and countries_match:
        if event_countries:
            options.append((20, f"внешняя торговля → по ФТС компания торгует с: {risk['fts_country']}", "confirmed"))
        else:
            # Страна в новости не названа: связь с торговлей компании слабее (визы, саммиты, общие санкции).
            options.append((10, f"внешняя торговля (страна в новости не названа) → у компании ВЭД: {risk['fts_country']}", "potential"))
    if "currency" in channels and has_fts:
        points = 20 if countries_match else 15
        options.append((points, "валютный курс → у компании внешнеторговые расчёты", "potential"))
    # Со слов пользователя: долг с плавающей ставкой, валюты контрактов и страны торговли.
    if channels & {"interest_rate", "inflation"} and user.get("floating_debt_rub"):
        options.append((25, "ставка → у компании долг с плавающей ставкой (со слов пользователя)", "confirmed"))
    export = user.get("export_share_pct")
    if export is not None and export >= MIN_EXPORT_SHARE and channels & {"currency", "international_trade"}:
        options.append((20, f"экспорт → {export:g}% выручки компании (со слов пользователя)", "confirmed"))
    foreign_revenue = [code for code in user.get("revenue_currencies") or [] if code != "RUB"]
    if "currency" in channels and foreign_revenue:
        options.append((20, f"валютный курс → выручка в {', '.join(foreign_revenue)} (со слов пользователя)", "confirmed"))
    if "currency" in channels and user.get("contract_currencies"):
        currencies = ", ".join(user["contract_currencies"])
        options.append((20, f"валютный курс → контракты в валютах: {currencies} (со слов пользователя)", "confirmed"))
    if "international_trade" in channels and user.get("trade_countries") and countries_match:
        options.append((20, "внешняя торговля → страны торговли со слов пользователя", "confirmed"))
    if "inflation" in channels and products.get("loa"):
        options.append((10, "инфляция → влияет на ставки по кредитам компании", "potential"))
    if "revenue" in channels and company_class in CONSUMER_CLASSES:
        options.append((15, "потребительский спрос → выручка компании зависит от спроса", "potential"))
    if risk.get("factoring_product") and channels & {"interest_rate", "supply_chain"}:
        options.append((10, "условия расчётов → у компании факторинг", "potential"))
    if products.get("gar") and "regulation" in channels and company_class in {"41", "42", "43"}:
        options.append((10, "требования к стройке → у компании банковские гарантии", "potential"))
    for direction, label in (("incoming", "покупателей"), ("outgoing", "поставщиков")):
        if f"{direction}_concentration" in channels and (payments.get(direction) or {}).get("concentration") == "high":
            options.append((15, f"высокая концентрация {label} у компании", "confirmed"))
    return _combine_channels(options)


def _combine_channels(options: list[tuple[int, str, Certainty]]) -> Optional[tuple[int, str, Certainty]]:
    """Лучший канал целиком, остальные — наполовину; один продукт засчитывается один раз."""
    if not options:
        return None
    ranked = sorted(options, key=lambda option: option[0], reverse=True)
    seen: set[str] = set()
    distinct = []
    for option in ranked:
        product = option[1].split("→")[-1].strip()
        if product in seen:
            continue
        seen.add(product)
        distinct.append(option)
    best = distinct[0]
    points = best[0] + sum(round(option[0] * EXTRA_CHANNEL_SHARE) for option in distinct[1:])
    reason = "; ".join(option[1] for option in distinct[:3])
    certainty = "confirmed" if any(option[2] == "confirmed" for option in distinct) else best[2]
    return min(points, GROUP_MAX["channels"]), reason, certainty


def _geography(
    profile: dict, event_countries: set[str], event_regions: set[str], user: dict
) -> Optional[tuple[int, str, Certainty]]:
    options: list[tuple[int, str, Certainty]] = []
    common = _company_countries(profile, user) & event_countries
    if common:
        options.append((20, f"страна события в торговле компании: {', '.join(sorted(common)).upper()}", "confirmed"))
    region = ((profile.get("location") or {}).get("region") or "").casefold().strip()
    if region and any(region in item or item in region for item in event_regions):
        options.append((12, f"событие в регионе компании: {profile['location']['region']}", "confirmed"))
    return _best(options)


def _supply_chain(counterparties: dict, event_codes: set[str]) -> tuple[Optional[tuple[int, str, Certainty]], float]:
    shares: dict[str, float] = {}
    for item in counterparties.get("industries") or []:
        if item["okved_class"] in event_codes:
            shares[item["okved_class"]] = shares.get(item["okved_class"], 0.0) + item["share"]
    share = min(1.0, sum(shares.values()))
    if share < MIN_SUPPLY_SHARE:
        return None, share
    points = max(1, round(share * GROUP_MAX["supply_chain"]))
    classes = ", ".join(sorted(shares))
    return (points, f"{share:.0%} платежей — контрагенты из отрасли события (ОКВЭД {classes})", "hypothesis"), share


def _user_chain(user: dict, event_codes: set[str]) -> Optional[tuple[int, str, Certainty]]:
    """Отрасли покупателей и поставщиков со слов пользователя → разделы ОКВЭД события."""
    from app.modules.news.extraction import INDUSTRY_RULES

    options: list[tuple[int, str, Certainty]] = []
    for key, label in (("customer_industries", "покупатели"), ("supplier_industries", "поставщики")):
        for name in user.get(key) or []:
            codes = {code for _, pattern, rule_codes in INDUSTRY_RULES if re.search(pattern, name.casefold()) for code in rule_codes}
            if codes & event_codes:
                options.append((12, f"{label} компании — {name} (со слов пользователя)", "confirmed"))
    return _best(options)


def _same_stem(left: str, right: str) -> bool:
    """«юаня» и «юаню», «металл» и «металлопрокат» — одно слово; общая основа хотя бы 3 буквы."""
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    return common >= max(3, min(len(left), len(right)) - 1)


def _interests(user: dict, event: dict) -> Optional[tuple[int, str, Certainty]]:
    """Тема, которую компания назвала важной, есть в событии: все основные слова темы в заголовке или тексте."""
    from app.research.search import tokenize

    words = tokenize(f"{event.get('title') or ''} {event.get('summary') or ''}")
    for interest in user.get("interests") or []:
        stems = tokenize(interest)[:4]
        if stems and all(any(_same_stem(stem, word) for word in words) for stem in stems):
            return 15, f"тема важна компании: «{interest}» (со слов пользователя)", "confirmed"
    return None


def _related(related: list[dict], event_codes: set[str]) -> Optional[tuple[int, str, Certainty]]:
    options: list[tuple[int, str, Certainty]] = []
    for item in related:
        if _okved_class(item.get("okved_code")) in event_codes:
            if item["certainty"] == "confirmed":
                options.append((10, f"событие касается компании группы {item['company_id']}", "confirmed"))
            else:
                options.append((6, f"событие касается возможно связанной компании {item['company_id']}", "hypothesis"))
    return _best(options)


MAX_SCORE = 100
# Доля экспорта, с которой курс и внешняя торговля касаются выручки компании.
MIN_EXPORT_SHARE = 10


def _fit_to_scale(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сумма максимумов групп больше 100: если событие задело почти всё, баллы уменьшаются
    пропорционально, чтобы шкала оставалась 0–100, а сумма составляющих — равной баллу."""
    total = sum(item["points"] for item in components)
    if total <= MAX_SCORE:
        return components
    scaled = [{**item, "points": item["points"] * MAX_SCORE // total, "scaled": True} for item in components]
    remainder = MAX_SCORE - sum(item["points"] for item in scaled)
    for item in sorted(scaled, key=lambda part: part["points"], reverse=True)[:remainder]:
        item["points"] += 1
    return scaled


def score_event(context: dict[str, Any], event: dict[str, Any], role: Optional[str] = None) -> dict[str, Any]:
    role = normalize_role(role)
    profile = context.get("company_profile") or {}
    user = context.get("user_data") or {}
    entities = event.get("entities") or {}
    event_codes = {code[:2] for code in entities.get("okved_codes") or [] if isinstance(code, str)}
    channels = {channel for channel in event.get("impact_channels") or [] if isinstance(channel, str)}
    event_countries = {item.casefold().strip() for item in entities.get("countries") or [] if isinstance(item, str)}
    event_regions = {item.casefold().strip() for item in entities.get("regions") or [] if isinstance(item, str)}

    supply, supply_share = _supply_chain(context.get("counterparty_industries") or {}, event_codes)
    supply = _best([option for option in (supply, _user_chain(user, event_codes)) if option])
    raw = {
        "industry": _industry(profile, event_codes),
        "channels": _channels(
            profile, context.get("payment_exposures") or {}, channels, event_countries, user, event.get("event_type")
        ),
        "geography": _geography(profile, event_countries, event_regions, user),
        "supply_chain": supply,
        "related": _related(context.get("related_companies") or [], event_codes),
        "interests": _interests(user, event),
    }
    sector_specific = bool(event_codes) and event.get("event_type") not in MACRO_TYPES
    confirmed_related = bool(raw["related"]) and raw["related"][2] == "confirmed"
    if sector_specific and not (raw["industry"] or raw["supply_chain"] or confirmed_related):
        raw["channels"] = None

    direct = any(raw[group] for group in ("industry", "channels", "geography", "related", "interests"))
    significance = SIGNIFICANCE.get(event.get("event_type") or "", DEFAULT_SIGNIFICANCE)
    if event.get("event_type") == "monetary_policy" and not RATE_DECISION.search(event.get("title") or ""):
        significance = RATE_COMMENTARY_SIGNIFICANCE
    low_information = is_low_information(event.get("title") or "")
    if low_information:
        significance = min(significance, LOW_INFO_SIGNIFICANCE)
    # Надёжность источника (quality.py): развлекательная лента весит меньше делового издания.
    trust = source_trust(event.get("url"), event.get("source"))
    significance = round(significance * trust, 3)
    components: list[dict[str, Any]] = []
    if direct or supply_share >= MIN_SUPPLY_SHARE_ALONE:
        for group, found in raw.items():
            if not found:
                continue
            points, reason, certainty = found
            weighted = round(points * significance)
            if weighted:
                components.append(
                    {
                        "group": group,
                        "label": GROUP_LABELS[group],
                        "points": weighted,
                        "max": GROUP_MAX[group],
                        "reason": reason,
                        "certainty": certainty,
                    }
                )

    # Роль поднимает событие, уже связанное с компанией, а сама по себе добавляет в ленту только
    # общие события, важные этой роли в любой компании (налоги — бухгалтеру).
    found_role = role_match(role, event.get("event_type"), channels)
    # Общее событие роли (налоги — бухгалтеру) показывается и ниже порога: ролевой балл сам по себе мал.
    role_universal = bool(found_role) and not components and is_universal_for_role(role, event.get("event_type"), event_codes)
    if found_role and (components or role_universal):
        points, reason = found_role
        weighted = round(points * significance)
        if weighted:
            components.append(
                {
                    "group": "role",
                    "label": GROUP_LABELS["role"],
                    "points": weighted,
                    "max": GROUP_MAX["role"],
                    "reason": reason,
                    "certainty": "potential",
                }
            )

    components = _fit_to_scale(components)
    score = sum(item["points"] for item in components)
    level = next((name for threshold, name in LEVELS if score >= threshold), "low" if role_universal and score else "none")
    explanation = (
        "; ".join(f"{item['label'].lower()} +{item['points']}: {item['reason']}" for item in components)
        if components
        else "нет признаков компании, на которые влияет событие"
    )
    if components and trust < 1:
        explanation += f"; надёжность источника ×{trust:g}"
    if components and low_information:
        explanation += f"; заявление или трансляция без новой меры ×{LOW_INFO_SIGNIFICANCE:g}"
    fresh = freshness(event.get("published_at"))
    return {
        "score": score,
        "level": level,
        # Порядок в ленте: балл × свежесть (сам балл объясним и от даты не зависит).
        "freshness": fresh,
        "rank": round(score * fresh["factor"], 2),
        "significance": significance,
        "source_trust": trust,
        "role": role,
        "role_universal": role_universal,
        "components": components,
        "explanation": explanation,
    }
