from typing import Any

from app.modules.companies.exposures import calculate_company_exposures
from app.modules.companies.links import counterparty_industries, related_companies
from app.modules.companies.profiling import get_analytics_profile
from app.modules.companies.relationships import RelationshipDataError
from app.modules.companies.repository import CompanyDataError, find_company_by_id


def _build_sensitivity_factors(
    profile: dict[str, Any],
    payments: dict[str, Any],
) -> list[dict[str, str]]:
    products = profile.get("products", {})
    risk_indicators = profile.get("risk_indicators", {})
    factors: list[dict[str, str]] = []

    product_factors = (
        ("loa", "interest_rate", "CL_PRODUCT_LOA_MARK", "Наличие кредитного продукта"),
        ("dep", "deposit_yield", "CL_PRODUCT_DEP_MARK", "Наличие депозитного продукта"),
        ("lea", "leasing_cost", "CL_PRODUCT_LEA_MARK", "Наличие лизингового продукта"),
    )

    for product, factor, source, reason in product_factors:
        if products.get(product) is True:
            factors.append(
                {
                    "factor": factor,
                    "source": source,
                    "reason": reason,
                    "certainty": "potential",
                }
            )

    if (
        risk_indicators.get("fts_data_available") is True
        and risk_indicators.get("fts_country")
    ):
        factors.append(
            {
                "factor": "international_trade",
                "source": "FTS_FLAG",
                "reason": "Есть данные ФТС о стране внешней торговли",
                "certainty": "potential",
            }
        )

    if payments.get("status") == "available":
        for direction in ("incoming", "outgoing"):
            summary = payments.get(direction, {})
            if summary.get("concentration") == "high":
                factors.append(
                    {
                        "factor": f"{direction}_concentration",
                        "source": "payment_edges",
                        "reason": (
                            "Высокая доля пяти крупнейших контрагентов "
                            f"в {direction} платежах"
                        ),
                        "certainty": "observed",
                    }
                )

    return factors


def build_personalization_context(
    company_id: str,
    user_data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    profile = get_analytics_profile(company_id)

    if profile is None:
        return None

    warnings: list[str] = []

    try:
        payment_exposures = {
            "status": "available",
            **calculate_company_exposures(company_id),
        }
    except RelationshipDataError:
        payment_exposures = {
            "status": "unavailable",
            "reason": "payment_data_unavailable",
        }
        warnings.append("Платёжные данные недоступны; контекст построен только по профилю.")

    client_type = profile.get("client_type")
    try:
        company = find_company_by_id(company_id)
        links = {
            "related_companies": related_companies(company) if company else [],
            "counterparty_industries": counterparty_industries(company_id),
        }
    except CompanyDataError:
        links = {
            "related_companies": [],
            "counterparty_industries": {"status": "unavailable", "industries": [], "unknown_share": None},
        }

    return {
        "context_version": "1.0",
        "company_id": company_id,
        "eligibility": {
            "client_type": client_type,
            "supported": client_type == "CLIENT",
        },
        "company_profile": profile,
        "payment_exposures": payment_exposures,
        # Связи и отрасли контрагентов: группа — подтверждённая связь, остальное — гипотезы.
        **links,
        # Сведения, которые компания сообщила сама (долг, валюты контрактов, страны).
        "user_data": user_data or {},
        "sensitivity_factors": _build_sensitivity_factors(
            profile,
            payment_exposures,
        ),
        "data_quality": {
            "missing_fields": profile.get("data_quality", {}).get(
                "missing_fields",
                [],
            ),
            "warnings": warnings,
        },
    }
