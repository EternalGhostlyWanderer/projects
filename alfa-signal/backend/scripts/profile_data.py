"""Aggregated, anonymized summary of the organizers' data — to tune scoring weights (no rows printed).

Примеры:
    python backend/scripts/profile_data.py
    python backend/scripts/profile_data.py --out data_profile.json

Печатает только агрегаты: доли, распределения, топ отраслей и стран. Идентификаторы компаний
и физлиц не выводятся, поэтому отчётом можно делиться с командой.
"""
import argparse
import csv
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.companies.links import LARGE_BUSINESS_REVENUE_RUB, MAX_COMPANIES_PER_PERSON, PEOPLE_CSV, clean_revenue, okved_class  # noqa: E402
from app.modules.companies.relationships import PAYMENTS_CSV  # noqa: E402
from app.modules.companies.repository import COMPANIES_CSV, get_all_companies, get_company_data_quality  # noqa: E402


def share(part: float, total: float) -> float:
    return round(part / total, 4) if total else 0.0


def companies_summary() -> dict:
    companies = get_all_companies()
    total = len(companies)
    clients = [company for company in companies if company.client_type == "CLIENT"]
    groups: dict[str, list] = {}
    for company in companies:
        if company.group_id:
            groups.setdefault(company.group_id, []).append(company)

    def group_revenue(company) -> float:
        members = groups.get(company.group_id, [company]) if company.group_id else [company]
        return sum(clean_revenue(member.revenue) or 0.0 for member in members)

    revenues = [clean_revenue(company.revenue) for company in companies]
    known = sorted(value for value in revenues if value is not None)
    countries = Counter(
        part.strip()
        for company in companies
        if company.fts_flag == 1 and company.fts_country
        for part in company.fts_country.split(",")
        if part.strip()
    )
    classes = Counter(okved_class(company.main_okved_code) for company in clients)
    products = {
        name: share(sum(1 for company in clients if getattr(company, field) == 1), len(clients))
        for name, field in (
            ("rko", "product_rko_mark"), ("gar", "product_gar_mark"), ("loa", "product_loa_mark"),
            ("lea", "product_lea_mark"), ("dep", "product_dep_mark"), ("zpp", "product_zpp_mark"),
            ("factoring", "factoring_mark"),
        )
    }
    group_sizes = Counter(min(len(members), 10) for members in groups.values())
    return {
        "file": str(COMPANIES_CSV),
        "companies": total,
        **get_company_data_quality(),
        "client_type": dict(Counter(company.client_type or "—" for company in companies)),
        "revenue": {
            "placeholder_or_missing_share": share(total - len(known), total),
            "median_rub": statistics.median(known) if known else None,
            "p90_rub": known[int(0.9 * (len(known) - 1))] if known else None,
            "companies_over_15bn": sum(1 for value in known if value >= LARGE_BUSINESS_REVENUE_RUB),
            "clients_with_group_revenue_over_15bn": sum(
                1 for company in clients if group_revenue(company) >= LARGE_BUSINESS_REVENUE_RUB
            ),
        },
        "groups": {
            "with_group_share": share(sum(1 for company in companies if company.group_id), total),
            "groups": len(groups),
            "group_size_distribution (10 = 10+)": dict(sorted(group_sizes.items())),
        },
        "fts": {
            "with_country_share": share(sum(1 for company in companies if company.fts_flag == 1 and company.fts_country), total),
            "top_countries": countries.most_common(15),
        },
        "clients_products_share": products,
        "clients_top_okved_classes": classes.most_common(20),
    }


def people_summary(company_ids: set[str]) -> dict:
    if not PEOPLE_CSV.is_file():
        return {"file": str(PEOPLE_CSV), "status": "нет файла"}
    by_person: dict[str, set[str]] = {}
    rows = 0
    with PEOPLE_CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            rows += 1
            person, company = (row.get("SYNTHETIC_F") or "").strip(), (row.get("SYNTHETIC_U") or "").strip()
            if person and company:
                by_person.setdefault(person, set()).add(company)
    sizes = Counter(min(len(companies), 11) for companies in by_person.values())
    linked = {company for companies in by_person.values() if 1 < len(companies) <= MAX_COMPANIES_PER_PERSON for company in companies}
    return {
        "file": str(PEOPLE_CSV),
        "rows": rows,
        "persons": len(by_person),
        "companies_per_person (11 = 11+)": dict(sorted(sizes.items())),
        "persons_over_limit": sum(1 for companies in by_person.values() if len(companies) > MAX_COMPANIES_PER_PERSON),
        "companies_with_person_links": len(linked),
        "linked_companies_in_profile_table_share": share(len(linked & company_ids), len(linked)),
    }


def payments_summary(company_ids: set[str]) -> dict:
    if not PAYMENTS_CSV.is_file():
        return {"file": str(PAYMENTS_CSV), "status": "нет файла"}
    rows = self_rows = 0
    amount = self_amount = known_counterparty_amount = 0.0
    count = self_count = 0.0
    with PAYMENTS_CSV.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file, delimiter=";"):
            rows += 1
            value, number = float(row["PAY_AMT"] or 0), float(row["PAY_CNT"] or 0)
            amount += value
            count += number
            if row["PAYER"] == row["BENEFICIARY"]:
                self_rows += 1
                self_amount += value
                self_count += number
            elif row["PAYER"] in company_ids and row["BENEFICIARY"] in company_ids:
                known_counterparty_amount += value
    external = amount - self_amount
    return {
        "file": str(PAYMENTS_CSV),
        "rows": rows,
        "self_transfers_amount_share": share(self_amount, amount),
        "self_transfers_count_share": share(self_count, count),
        "both_sides_have_profile_amount_share": share(known_counterparty_amount, external),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Обезличенная сводка по данным организаторов.")
    parser.add_argument("--out", type=Path, help="Сохранить сводку в JSON")
    args = parser.parse_args()

    companies = companies_summary()
    company_ids = {company.id for company in get_all_companies()}
    report = {
        "companies": companies,
        "people": people_summary(company_ids),
        "payments": payments_summary(company_ids),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    print(text)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\nСохранено: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
