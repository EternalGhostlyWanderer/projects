
import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[4]
# Путь можно переопределить переменной окружения PAYMENTS_CSV (относительный — от корня репозитория).
PAYMENTS_CSV = PROJECT_ROOT / (
    os.getenv("PAYMENTS_CSV") or Path("data") / "raw" / "df_Uid_payment_hack.csv"
)


class RelationshipDataError(Exception):
    """Ошибка чтения или обработки платёжных связей."""


@lru_cache(maxsize=1)
def _load_payment_edges() -> tuple[dict[str, Any], ...]:
    if not PAYMENTS_CSV.exists():
        raise RelationshipDataError(
            f"Файл платежей не найден: {PAYMENTS_CSV}"
        )

    aggregated: dict[tuple[str, str], dict[str, float]] = {}

    try:
        with PAYMENTS_CSV.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file, delimiter=";")

            required = {"PAYER", "BENEFICIARY", "PAY_AMT", "PAY_CNT"}
            missing = required - set(reader.fieldnames or [])

            if missing:
                raise RelationshipDataError(
                    "В CSV отсутствуют колонки: "
                    + ", ".join(sorted(missing))
                )

            for row in reader:
                payer = (row.get("PAYER") or "").strip()
                beneficiary = (row.get("BENEFICIARY") or "").strip()

                if not payer or not beneficiary:
                    continue

                try:
                    amount = float(row["PAY_AMT"])
                    count = float(row["PAY_CNT"])
                except (ValueError, TypeError, KeyError) as exc:
                    raise RelationshipDataError(
                        f"Некорректные числовые данные "
                        f"в строке {reader.line_num}"
                    ) from exc

                if amount < 0 or count < 0:
                    raise RelationshipDataError(
                        f"Отрицательная сумма или количество "
                        f"в строке {reader.line_num}"
                    )

                key = (payer, beneficiary)
                totals = aggregated.setdefault(
                    key,
                    {"amount": 0.0, "count": 0.0},
                )
                totals["amount"] += amount
                totals["count"] += count

    except OSError as exc:
        raise RelationshipDataError(
            f"Не удалось прочитать платежи: {exc}"
        ) from exc

    return tuple(
        {
            "payer": payer,
            "beneficiary": beneficiary,
            "amount": values["amount"],
            "count": values["count"],
        }
        for (payer, beneficiary), values in aggregated.items()
    )


@lru_cache(maxsize=1)
def _edges_by_company() -> dict[str, tuple[dict[str, Any], ...]]:
    """Индекс «компания → её платежи»: без него каждый запрос просматривал бы весь файл."""
    index: dict[str, list[dict[str, Any]]] = {}
    for edge in _load_payment_edges():
        index.setdefault(edge["payer"], []).append(edge)
        if edge["beneficiary"] != edge["payer"]:
            index.setdefault(edge["beneficiary"], []).append(edge)
    return {company_id: tuple(edges) for company_id, edges in index.items()}


def get_company_relationships(
    company_id: str,
    direction: Literal["incoming", "outgoing", "both"] = "both",
    limit: Optional[int] = 50,
) -> list[dict[str, Any]]:
    company_id = company_id.strip()

    if not company_id:
        raise ValueError("company_id не должен быть пустым")

    if direction not in {"incoming", "outgoing", "both"}:
        raise ValueError(
            "direction должен быть incoming, outgoing или both"
        )

    if limit is not None and not 1 <= limit <= 100:
        raise ValueError("limit должен быть от 1 до 100 или None")

    results: list[dict[str, Any]] = []

    for edge in _edges_by_company().get(company_id, ()):
        payer = edge["payer"]
        beneficiary = edge["beneficiary"]

        if payer == beneficiary:
            continue

        if direction in {"outgoing", "both"} and payer == company_id:
            results.append(
                {
                    "company_id": company_id,
                    "counterparty_id": beneficiary,
                    "direction": "outgoing",
                    "amount": edge["amount"],
                    "count": edge["count"],
                }
            )

        if direction in {"incoming", "both"} and beneficiary == company_id:
            results.append(
                {
                    "company_id": company_id,
                    "counterparty_id": payer,
                    "direction": "incoming",
                    "amount": edge["amount"],
                    "count": edge["count"],
                }
            )

    results.sort(key=lambda item: item["amount"], reverse=True)

    if limit is None:
        return results

    return results[:limit]


def get_company_self_transfers(company_id: str) -> dict[str, float]:
    normalized_company_id = company_id.strip()

    if not normalized_company_id:
        raise ValueError("company_id не должен быть пустым")

    amount = 0.0
    count = 0.0

    for edge in _edges_by_company().get(normalized_company_id, ()):
        if (
            edge["payer"] == normalized_company_id
            and edge["beneficiary"] == normalized_company_id
        ):
            amount += edge["amount"]
            count += edge["count"]

    return {
        "amount": amount,
        "count": count,
    }


def clear_relationship_cache() -> None:
    _edges_by_company.cache_clear()
    _load_payment_edges.cache_clear()
