from typing import List, Optional, Tuple

from app.modules.companies.repository import (
    find_companies,
    find_company_by_id,
)
from app.schemas.company import Company


def search_companies(
    query: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Tuple[List[Company], int]:
    return find_companies(
        query=query,
        limit=limit,
        offset=offset,
    )


def get_company_profile(company_id: str) -> Optional[Company]:
    return find_company_by_id(company_id)
