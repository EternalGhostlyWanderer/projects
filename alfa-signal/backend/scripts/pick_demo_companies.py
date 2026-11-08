"""Pick contrasting demo companies from the organizers' CSV (no API calls).

Примеры:
    python backend/scripts/pick_demo_companies.py
    python backend/scripts/pick_demo_companies.py --min-revenue 15000000   # если выручка в тысячах рублей

Печатает распределение выручки (чтобы понять единицы измерения) и 4–6 компаний
с разными признаками: кредит, депозит без кредита, лизинг, внешняя торговля, группа,
концентрация платежей.
"""
import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.companies.exposures import calculate_company_exposures  # noqa: E402
from app.modules.companies.links import group_summary, related_companies  # noqa: E402
from app.modules.companies.relationships import RelationshipDataError  # noqa: E402
from app.modules.companies.repository import COMPANIES_CSV, get_all_companies  # noqa: E402

PRODUCT_FIELDS = {
    "loa": "product_loa_mark",
    "dep": "product_dep_mark",
    "lea": "product_lea_mark",
    "gar": "product_gar_mark",
    "rko": "product_rko_mark",
    "zpp": "product_zpp_mark",
}


def products(company) -> list[str]:
    return [name for name, field in PRODUCT_FIELDS.items() if getattr(company, field) == 1]


def quantile(values: list[float], share: float) -> float:
    return values[min(len(values) - 1, int(share * len(values)))]


def main() -> int:
    parser = argparse.ArgumentParser(description="Подбор демо-компаний из CSV организаторов.")
    parser.add_argument("--min-revenue", type=float, default=15e9, help="Порог выручки (по умолчанию 15 млрд)")
    parser.add_argument("--scan", type=int, default=300, help="Сколько крупнейших компаний проверять по платежам")
    args = parser.parse_args()

    companies = get_all_companies()
    print(f"Файл: {COMPANIES_CSV}\nКомпаний: {len(companies)}")
    types: dict[str, int] = {}
    for company in companies:
        types[company.client_type or "—"] = types.get(company.client_type or "—", 0) + 1
    print("CL_TYPE:", types)

    revenues = sorted(company.revenue for company in companies if company.revenue and company.revenue != 1000)
    if revenues:
        print(
            "Выручка (без пустых и заглушки 1000): "
            f"медиана {statistics.median(revenues):,.0f}; p90 {quantile(revenues, 0.9):,.0f}; "
            f"p99 {quantile(revenues, 0.99):,.0f}; максимум {revenues[-1]:,.0f}".replace(",", " ")
        )
        for threshold in (15e9, 15e6):
            count = sum(1 for value in revenues if value >= threshold)
            print(f"  компаний с выручкой ≥ {threshold:,.0f}: {count}".replace(",", " "))
        print("  Если ≥ 15 млрд почти нет, а ≥ 15 млн много — выручка, вероятно, в тысячах рублей.")

    # Крупный бизнес — по выручке группы (ответ организаторов); сервис — для действующих клиентов.
    group_revenue = {
        company.id: group_summary(company)["revenue_rub"] or 0.0
        for company in companies
        if company.client_type == "CLIENT"
    }
    candidates = sorted(
        (
            company
            for company in companies
            if company.client_type == "CLIENT"
            and group_revenue.get(company.id, 0.0) >= args.min_revenue
            and company.main_okved_name
            and company.region
        ),
        key=lambda company: group_revenue[company.id],
        reverse=True,
    )[: args.scan]
    print(
        f"\nДействующих клиентов с выручкой группы ≥ {args.min_revenue:,.0f}: {len(candidates)} "
        f"(проверяем до {args.scan})".replace(",", " ")
    )
    if not candidates:
        print("Кандидатов нет: попробуйте меньший --min-revenue.")
        return 0

    concentration: dict[str, str] = {}
    try:
        for company in candidates:
            exposures = calculate_company_exposures(company.id)
            concentration[company.id] = exposures["outgoing"]["concentration"]
    except RelationshipDataError as exc:
        print(f"Платежи недоступны: {exc}")

    rules = [
        ("кредит", lambda c: "loa" in products(c)),
        ("депозит без кредита", lambda c: "dep" in products(c) and "loa" not in products(c)),
        ("лизинг", lambda c: "lea" in products(c)),
        ("внешняя торговля (ФТС)", lambda c: c.fts_flag == 1 and bool(c.fts_country)),
        ("входит в группу", lambda c: bool(c.group_id)),
        ("связи через физлиц", lambda c: any(item["link"] == "shared_person" for item in related_companies(c))),
        ("высокая концентрация платежей", lambda c: concentration.get(c.id) == "high"),
    ]
    chosen: dict[str, str] = {}
    used_industries: set[str] = set()
    for label, rule in rules:
        company = next(
            (
                c
                for c in candidates
                if rule(c) and c.id not in chosen and (c.main_okved_code or "")[:2] not in used_industries
            ),
            None,
        ) or next((c for c in candidates if rule(c) and c.id not in chosen), None)
        if company:
            chosen[company.id] = label
            used_industries.add((company.main_okved_code or "")[:2])

    by_id = {company.id: company for company in candidates}
    print(f"\n{'id':<12}{'почему':<32}{'выручка группы':>20}  продукты / ФТС / отрасль / регион")
    for company_id, label in chosen.items():
        company = by_id[company_id]
        print(
            f"{company_id:<12}{label:<32}{group_revenue[company_id]:>20,.0f}  ".replace(",", " ")
            + f"{','.join(products(company)) or '—'} / {company.fts_country or '—'} / "
            f"{(company.main_okved_name or '')[:45]} / {company.region}"
        )

    print("\nДля фронтенда (frontend/.env.local):")
    print("VITE_COMPANY_IDS=" + ",".join(chosen))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
