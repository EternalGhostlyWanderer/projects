from typing import Any, Optional

from app.modules.personalization.scoring import score_event


def _casefold_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [value.casefold().strip() for value in values if isinstance(value, str) and value.strip()]


def _match_entities(
    context: dict[str, Any],
    entities: Any,
) -> dict[str, str]:
    """Match event entities (from extraction) against the company profile."""
    if not isinstance(entities, dict):
        return {}

    profile = context.get("company_profile") or {}
    matches: dict[str, str] = {}

    okved_code = ((profile.get("industry") or {}).get("code") or "").strip()
    if okved_code and okved_code[:2] in {code[:2] for code in _casefold_values(entities.get("okved_codes"))}:
        matches["industry"] = okved_code

    region = ((profile.get("location") or {}).get("region") or "").casefold().strip()
    if region and any(
        region in event_region or event_region in region
        for event_region in _casefold_values(entities.get("regions"))
    ):
        matches["region"] = profile["location"]["region"]

    # В данных ФТС бывает несколько стран через запятую: «КИРГИЗИЯ, КАЗАХСТАН».
    fts_country = (profile.get("risk_indicators") or {}).get("fts_country") or ""
    company_countries = {part.casefold().strip() for part in fts_country.split(",") if part.strip()}
    event_countries = set(_casefold_values(entities.get("countries")))
    if company_countries & event_countries:
        matches["trade_country"] = fts_country

    return matches


def assess_relevance(
    context: dict[str, Any],
    event: dict[str, Any],
    role: Optional[str] = None,
) -> dict[str, Any]:
    company_factors = {
        item.get("factor")
        for item in context.get("sensitivity_factors", [])
        if isinstance(item, dict) and isinstance(item.get("factor"), str)
    }
    impact_channels = event.get("impact_channels", [])
    matched_factors = list(
        dict.fromkeys(
            channel
            for channel in impact_channels
            if isinstance(channel, str) and channel in company_factors
        )
    )
    matched_entities = _match_entities(context, event.get("entities"))
    matched_factors.extend(
        factor for factor in matched_entities if factor not in matched_factors
    )

    scoring = score_event(context, event, role=role)
    return {
        "company_id": context.get("company_id"),
        "event_id": event.get("event_id"),
        "matched_factors": matched_factors,
        "matched_entities": matched_entities,
        "match_count": len(matched_factors),
        "has_direct_matches": bool(matched_factors),
        # Объяснимый балл 0–100: им сортируется лента (scoring.py, docs/scoring.md).
        **scoring,
    }
