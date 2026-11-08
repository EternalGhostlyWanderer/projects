
from typing import Any, Literal

from app.modules.companies.relationships import (
    get_company_relationships,
    get_company_self_transfers,
)


def _summarize_direction(
    relationships: list[dict[str, Any]],
    direction: Literal["incoming", "outgoing"],
) -> dict[str, Any]:
    edges = [
        edge for edge in relationships
        if edge["direction"] == direction
    ]

    total_amount = sum(edge["amount"] for edge in edges)
    total_count = sum(edge["count"] for edge in edges)
    counterparties: dict[str, dict[str, float]] = {}

    for edge in edges:
        counterparty_id = edge["counterparty_id"]
        item = counterparties.setdefault(
            counterparty_id,
            {"amount": 0.0, "count": 0.0},
        )
        item["amount"] += edge["amount"]
        item["count"] += edge["count"]

    ranked = sorted(
        (
            {
                "counterparty_id": counterparty_id,
                "amount": values["amount"],
                "count": values["count"],
                "share": (
                    values["amount"] / total_amount
                    if total_amount > 0
                    else 0.0
                ),
            }
            for counterparty_id, values in counterparties.items()
        ),
        key=lambda item: item["amount"],
        reverse=True,
    )

    top_5_share = sum(item["share"] for item in ranked[:5])

    if not ranked or total_amount <= 0:
        concentration = "unknown"
    elif len(counterparties) <= 5:
        concentration = "insufficient_counterparties"
    elif top_5_share >= 0.8:
        concentration = "high"
    elif top_5_share >= 0.5:
        concentration = "moderate"
    else:
        concentration = "low"

    return {
        "direction": direction,
        "total_amount": total_amount,
        "total_count": total_count,
        "counterparty_count": len(counterparties),
        "top_5_amount_share": round(top_5_share, 4),
        "concentration": concentration,
        "top_counterparties": ranked[:5],
    }


def calculate_company_exposures(
    company_id: str,
) -> dict[str, Any]:
    relationships = get_company_relationships(
        company_id=company_id,
        direction="both",
        limit=None,
    )
    self_transfers = get_company_self_transfers(company_id)

    outgoing = _summarize_direction(
        relationships,
        "outgoing",
    )
    incoming = _summarize_direction(
        relationships,
        "incoming",
    )

    warnings: list[str] = []

    if outgoing["concentration"] == "high":
        warnings.append(
            "Высокая концентрация исходящих платежей: "
            "значительная доля приходится на пять крупнейших получателей."
        )

    if incoming["concentration"] == "high":
        warnings.append(
            "Высокая концентрация входящих платежей: "
            "значительная доля поступлений приходится на пять крупнейших плательщиков."
        )

    if (
        outgoing["concentration"] == "unknown"
        and incoming["concentration"] == "unknown"
    ):
        warnings.append(
            "Недостаточно данных о платежах для оценки концентрации."
        )

    return {
        "company_id": company_id,
        "method": "top_5_counterparty_payment_share",
        "currency": "RUB",
        "period": "from_january",
        "outgoing": outgoing,
        "incoming": incoming,
        "self_transfers": {
            **self_transfers,
            "excluded_from_concentration": True,
        },
        "warnings": warnings,
        "limitations": [
            "Анализ основан на доступных агрегированных платёжных данных.",
            "Период начинается 1 января; дата окончания в наборе не указана.",
            "Концентрация платежей не доказывает наличие финансовых проблем.",
            "Данные не позволяют автоматически установить причинно-следственную связь.",
        ],
    }
