
import csv
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from app.schemas.company import Company


PROJECT_ROOT = Path(__file__).resolve().parents[4]
# Путь можно переопределить переменной окружения COMPANIES_CSV (относительный — от корня репозитория).
COMPANIES_CSV = PROJECT_ROOT / (
    os.getenv("COMPANIES_CSV") or Path("data") / "raw" / "df_Uid_data_hack.csv"
)


class CompanyDataError(Exception):
    """Ошибка чтения или структуры данных компаний."""


def _exclude_duplicate_companies(
    companies: list[Company],
) -> tuple[tuple[Company, ...], tuple[str, ...]]:
    companies_by_id: dict[str, Company] = {}
    duplicate_ids: set[str] = set()

    for company in companies:
        if company.id in duplicate_ids:
            continue
        if company.id in companies_by_id:
            if companies_by_id[company.id] != company:
                companies_by_id.pop(company.id)
                duplicate_ids.add(company.id)
            continue
        companies_by_id[company.id] = company

    return tuple(companies_by_id.values()), tuple(sorted(duplicate_ids))


@lru_cache(maxsize=1)
def _load_company_data() -> tuple[tuple[Company, ...], tuple[str, ...]]:

    if not COMPANIES_CSV.is_file():
        raise CompanyDataError(
            f"Файл компаний не найден: {COMPANIES_CSV}"
        )

    companies: list[Company] = []

    try:
        with COMPANIES_CSV.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file, delimiter=";")

            if (
                not reader.fieldnames
                or "SYNTHETIC_U" not in reader.fieldnames
            ):
                raise CompanyDataError(
                    "В CSV отсутствует колонка SYNTHETIC_U"
                )

            for row in reader:
                normalized = {
                    key: (
                        value.strip()
                        if value is not None and value.strip()
                        else None
                    )
                    for key, value in row.items()
                    if key is not None
                }

                company_id = normalized.get("SYNTHETIC_U")

                if not company_id:
                    continue

                try:
                    company = Company.model_validate(normalized)
                except Exception as exc:
                    raise CompanyDataError(
                        f"Ошибка в строке {reader.line_num}: {exc}"
                    ) from exc

                companies.append(company)

    except OSError as exc:
        raise CompanyDataError(
            f"Не удалось прочитать CSV: {exc}"
        ) from exc

    return _exclude_duplicate_companies(companies)


def get_all_companies() -> tuple[Company, ...]:
    companies, _duplicate_ids = _load_company_data()
    return companies


def get_company_data_quality() -> dict[str, int]:
    companies, duplicate_ids = _load_company_data()
    return {
        "available_company_count": len(companies),
        "excluded_duplicate_id_count": len(duplicate_ids),
    }


@lru_cache(maxsize=1)
def get_company_index() -> dict[str, Company]:

    return {
        company.id: company
        for company in get_all_companies()
    }


@lru_cache(maxsize=1)
def get_company_search_index() -> tuple[tuple[Company, str], ...]:

    searchable_fields = (
        "id",
        "group_id",
        "city",
        "region",
        "main_okved_code",
        "main_okved_name",
    )

    index = []

    for company in get_all_companies():
        values = (
            getattr(company, field, None)
            for field in searchable_fields
        )
        search_text = " ".join(
            str(value) for value in values if value is not None
        ).casefold()

        index.append((company, search_text))

    return tuple(index)


def find_companies(
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Company], int]:

    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    normalized_query = (query or "").strip().casefold()

    if not normalized_query:
        companies = get_all_companies()
        total = len(companies)
        return list(companies[offset:offset + limit]), total

    exact_company = get_company_index().get(query.strip())

    if exact_company is not None:
        return [exact_company], 1

    matches = [
        company
        for company, search_text in get_company_search_index()
        if normalized_query in search_text
    ]

    total = len(matches)
    return matches[offset:offset + limit], total


def find_company_by_id(company_id: str) -> Optional[Company]:

    return get_company_index().get(company_id.strip())


def clear_company_cache() -> None:

    get_company_search_index.cache_clear()
    get_company_index.cache_clear()
    _load_company_data.cache_clear()
