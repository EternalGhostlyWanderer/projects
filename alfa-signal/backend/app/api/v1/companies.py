
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from pydantic import BaseModel, Field, ValidationError

from app.api.deps import (
    UserContext,
    allowed_companies,
    check_company_access,
    current_user,
    require_company,
    store_dependency,
)
from app.db.store import AppStore
from app.modules.companies.links import counterparty_industries, group_summary, related_companies
from app.modules.companies.documents import (
    EXTRACTABLE,
    MAX_DOCUMENT_CHARS,
    MAX_FILE_BYTES,
    DocumentError,
    extract_from_document,
    merge_with_sources,
    read_document,
)
from app.modules.companies.user_data import CompanyUserData

from app.modules.companies.service import (
    get_company_profile as get_company,
    search_companies,
)
from app.modules.companies.profiling import (
    build_company_profile,
)
from app.modules.companies.relationships import (
    get_company_relationships,
    RelationshipDataError,
)
from app.modules.companies.exposures import (
    calculate_company_exposures,
)
from app.schemas.company import Company


router = APIRouter(prefix="/companies", tags=["Companies"], dependencies=[Depends(current_user)])


@router.get("")
def list_companies(
    q: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    items, total = search_companies(
        query=q,
        limit=limit,
        offset=offset,
    )
    allowed = allowed_companies()
    if allowed is not None:
        # Строгий режим: в списке только компании демо-доступа (DEMO_COMPANY_IDS), без перебора выборки.
        items = [company for company in (get_company(company_id) for company_id in sorted(allowed)) if company]
        total = len(items)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/{company_id}", response_model=Company)
def company_details(
    company_id: str, x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id")
) -> Company:
    check_company_access(company_id, x_company_id)
    company = get_company(company_id)

    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Компания не найдена",
        )

    return company


@router.get("/{company_id}/profile")
def company_profile(
    company_id: str, x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id")
) -> dict[str, Any]:
    check_company_access(company_id, x_company_id)
    company = get_company(company_id)

    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Компания не найдена",
        )

    return build_company_profile(company)


@router.get("/{company_id}/relationships")
def company_relationships(
    company_id: str,
    direction: str = Query(default="both", pattern="^(incoming|outgoing|both)$"),
    limit: int = Query(default=50, ge=1, le=100),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    check_company_access(company_id, x_company_id)
    company = get_company(company_id)

    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Компания не найдена",
        )

    try:
        items = get_company_relationships(
            company_id=company_id,
            direction=direction,  # type: ignore[arg-type]
            limit=limit,
        )
    except RelationshipDataError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc

    return {
        "company_id": company_id,
        "direction": direction,
        "items": items,
        "count": len(items),
    }


@router.get("/{company_id}/exposures")
def company_exposures(
    company_id: str, x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id")
) -> dict[str, Any]:
    check_company_access(company_id, x_company_id)
    company = get_company(company_id)

    if company is None:
        raise HTTPException(
            status_code=404,
            detail="Компания не найдена",
        )

    try:
        return calculate_company_exposures(company_id)
    except RelationshipDataError as exc:
        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc


@router.get("/{company_id}/links")
def company_links(
    company_id: str,
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    """Группа, связанные компании (группа — подтверждено, общее физлицо — гипотеза) и отрасли контрагентов."""
    require_company(company_id, x_company_id)
    company = get_company(company_id)
    return {
        "company_id": company_id,
        "group": group_summary(company),
        "related_companies": related_companies(company),
        "counterparty_industries": counterparty_industries(company_id),
    }


@router.get("/{company_id}/user-data")
def get_company_user_data(
    company_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    require_company(company_id, x_company_id)
    return {"company_id": company_id, "data": store.get_user_data(company_id)}


@router.put("/{company_id}/user-data")
def put_company_user_data(
    company_id: str,
    body: CompanyUserData,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    """Сведения от пользователя: учитываются в ленте, анализе и чате с пометкой «со слов пользователя».

    Изменённые вручную поля получают источник «вручную»; источник «из документа» сохраняется, пока
    значение не меняли. Каждое изменение пишется в журнал (кто, когда, какие поля).
    """
    require_company(company_id, x_company_id)
    current = {key: value for key, value in store.get_user_data(company_id).items() if key != "updated_at"}
    data = body.model_dump(exclude_none=True)
    sources = {**(current.get("field_sources") or {}), **data.get("field_sources", {})}
    changed = sorted(
        key
        for key in set(data) | set(current)
        if key != "field_sources" and _empty_as_none(data.get(key)) != _empty_as_none(current.get(key))
    )
    now = datetime.now(timezone.utc).isoformat()
    for key in changed:
        submitted = data.get("field_sources", {}).get(key)
        if not submitted or submitted.get("source") != "document":
            sources[key] = {"source": "manual", "updated_at": now, "user_id": user.user_id or None}
    data["field_sources"] = {key: value for key, value in sources.items() if key in data}
    store.save_user_data(company_id, CompanyUserData.model_validate(data).model_dump(exclude_none=True))
    if changed:
        store.log_user_data_change(company_id, user_id=user.user_id, source="manual", fields=changed)
    return {"company_id": company_id, "data": store.get_user_data(company_id)}


def _empty_as_none(value: Any) -> Any:
    return None if value in ([], "", None) else value


class DocumentRequest(BaseModel):
    filename: str = Field(default="", max_length=200)
    text: Optional[str] = Field(default=None, max_length=MAX_DOCUMENT_CHARS * 2)
    file_base64: Optional[str] = Field(default=None, max_length=MAX_FILE_BYTES * 2)


@router.post("/{company_id}/user-data/extract")
def extract_company_user_data(
    company_id: str,
    body: DocumentRequest,
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    """Предпросмотр: поля сведений о компании из документа с дословными цитатами. Ничего не сохраняет (платно)."""
    require_company(company_id, x_company_id)
    try:
        text = read_document(text=body.text, file_base64=body.file_base64, filename=body.filename)
    except DocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"company_id": company_id, **extract_from_document(text, document=body.filename or "вставленный текст")}


class ApplyField(BaseModel):
    field: str = Field(min_length=1, max_length=60)
    value: Any
    quote: Optional[str] = Field(default=None, max_length=400)


class ApplyDocumentRequest(BaseModel):
    document: str = Field(default="документ", max_length=200)
    fields: list[ApplyField] = Field(min_length=1, max_length=20)


@router.post("/{company_id}/user-data/apply-document")
def apply_document_fields(
    company_id: str,
    body: ApplyDocumentRequest,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    """Сохранить подтверждённые пользователем поля из документа: с источником и цитатой."""
    require_company(company_id, x_company_id)
    unknown = [item.field for item in body.fields if item.field not in EXTRACTABLE]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Поля нельзя заполнить из документа: {', '.join(unknown)}")
    try:
        merged = merge_with_sources(
            store.get_user_data(company_id),
            [item.model_dump() for item in body.fields],
            document=body.document,
            user_id=user.user_id,
            now=datetime.now(timezone.utc).isoformat(),
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Значения не прошли проверку: {exc.errors()[0]['msg']}") from exc
    store.save_user_data(company_id, merged)
    store.log_user_data_change(
        company_id, user_id=user.user_id, source="document", document=body.document, fields=[item.field for item in body.fields]
    )
    return {"company_id": company_id, "data": store.get_user_data(company_id)}


@router.get("/{company_id}/user-data/history")
def company_user_data_history(
    company_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    """Журнал изменений сведений о компании: кто, когда, какие поля, вручную или из документа."""
    require_company(company_id, x_company_id)
    return {"company_id": company_id, "items": store.user_data_history(company_id)}


@router.get("/{company_id}/requests")
def company_requests(
    company_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
) -> dict[str, Any]:
    require_company(company_id, x_company_id)
    return {"company_id": company_id, "items": store.list_requests(company_id)}
