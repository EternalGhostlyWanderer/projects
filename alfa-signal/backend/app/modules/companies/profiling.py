from typing import Any, Optional

from app.modules.companies.links import clean_revenue, group_summary
from app.modules.companies.position import industry_position
from app.modules.companies.repository import find_company_by_id
from app.schemas.company import Company


def _enabled(value: Optional[float]) -> bool:
    return value == 1


def _normalized_revenue(value: Optional[float]) -> Optional[float]:
    return clean_revenue(value)


def build_company_profile(company: Company) -> dict[str, Any]:
    revenue = _normalized_revenue(company.revenue)
    fts_data_available = _enabled(company.fts_flag)
    missing_fields: list[str] = []

    if revenue is None:
        missing_fields.append("financials.revenue_rub")
    if not company.main_okved_name:
        missing_fields.append("industry.name")
    if not company.region:
        missing_fields.append("location.region")
    if fts_data_available and not company.fts_country:
        missing_fields.append("foreign_trade.country")

    return {
        "id": company.id,
        "organization_type": company.org_type,
        "ownership_type": company.ownership_type,
        "age_group": company.age_group,
        "industry": {
            "code": company.main_okved_code,
            "name": company.main_okved_name,
        },
        "location": {
            "city": company.city,
            "region": company.region,
        },
        "financials": {
            "revenue_rub": revenue,
            "revenue_year": 2025,
            "employees_fns": company.employees_fns,
            "employees_spark": company.employees_spark,
        },
        "risk_indicators": {
            "key_owner_data_available": _enabled(company.negative_mark),
            "fts_data_available": fts_data_available,
            "fts_country": company.fts_country,
            "factoring_product": _enabled(company.factoring_mark),
        },
        "products": {
            "rko": _enabled(company.product_rko_mark),
            "gar": _enabled(company.product_gar_mark),
            "loa": _enabled(company.product_loa_mark),
            "lea": _enabled(company.product_lea_mark),
            "dep": _enabled(company.product_dep_mark),
            "zpp": _enabled(company.product_zpp_mark),
        },
        "group_id": company.group_id,
        # Крупный бизнес определяется по выручке группы, а не отдельного юрлица.
        "group": group_summary(company),
        # Положение в отрасли по выборке банка (п. 1 задания): место по выручке, доля, группа.
        "industry_position": industry_position(company),
        "eco_mark": company.eco_mark,
        "client_type": company.client_type,
        "data_quality": {
            "missing_fields": missing_fields,
        },
    }


def get_analytics_profile(company_id: str) -> Optional[dict[str, Any]]:
    company = find_company_by_id(company_id)

    if company is None:
        return None

    return build_company_profile(company)
