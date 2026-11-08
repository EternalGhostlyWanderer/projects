"""Shared API dependencies: storage, company access control and the current user."""
import os
from typing import Optional

from fastapi import Header, HTTPException, Query
from pydantic import BaseModel

from app.db.store import AppStore, get_store
from app.modules.companies.service import get_company_profile
from app.modules.personalization.roles import ROLES, normalize_role


def store_dependency() -> AppStore:
    return get_store()


def strict_company_scope() -> bool:
    """API_REQUIRE_COMPANY_SCOPE=1 — без контекста компании (X-Company-Id) данные компании не отдаются.

    Для внешнего сервера: иначе любой, кто знает адрес API, перебирает компании. Локально по умолчанию
    выключено, чтобы Swagger и скрипты работали без заголовка.
    """
    return os.getenv("API_REQUIRE_COMPANY_SCOPE", "0") == "1"


def check_company_access(company_id: str, x_company_id: Optional[str]) -> None:
    """Prototype isolation: a client that sends X-Company-Id sees only that company.

    В строгом режиме заголовок обязателен. Полномочия пользователя в компании проверяет банк при входе
    (вебинар, вопрос 32); здесь — граница доступа между компаниями в API.
    """
    if not x_company_id and strict_company_scope():
        raise HTTPException(status_code=401, detail="Нужен контекст компании: заголовок X-Company-Id")
    if x_company_id and x_company_id != company_id:
        raise HTTPException(status_code=403, detail="Нет доступа к данным этой компании")


def allowed_companies() -> Optional[set[str]]:
    """Список компаний, видимых в строгом режиме (DEMO_COMPANY_IDS); None — без ограничения."""
    if not strict_company_scope():
        return None
    return {item.strip() for item in os.getenv("DEMO_COMPANY_IDS", "").split(",") if item.strip()}


def require_company(company_id: str, x_company_id: Optional[str] = None) -> None:
    check_company_access(company_id, x_company_id)
    if get_company_profile(company_id) is None:
        raise HTTPException(status_code=404, detail="Компания не найдена")



class UserContext(BaseModel):
    """Кто смотрит: пользователь компании и его роль (заголовки X-User-Id и X-User-Role).

    Оба необязательны: без них API работает как раньше, на уровне компании.
    Полномочия пользователя в компании считаются проверенными банком при входе (вебинар, вопрос 32).
    """

    user_id: str = ""
    role: Optional[str] = None
    companies: list[str] = []


def check_user_company(company_id: str, user: UserContext) -> None:
    if user.companies and company_id not in user.companies:
        raise HTTPException(status_code=403, detail="У пользователя нет доступа к этой компании")


def current_user(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id", max_length=100),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role", max_length=40),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    role: Optional[str] = Query(default=None, max_length=40, description="Роль; важнее заголовка X-User-Role"),
    # Ссылка на PDF первоисточника открывается без заголовков; где токен в адресе допустим,
    # решает middleware require_auth (только файл документа).
    access_token: Optional[str] = Query(default=None, max_length=4096, include_in_schema=False),
) -> UserContext:
    if not authorization and access_token:
        authorization = f"Bearer {access_token}"
    if authorization:
        from app.api.v1.auth import AuthConfigError, verify_demo_token

        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Нужна действующая demo-сессия")
        try:
            claims = verify_demo_token(token)
        except (ValueError, AuthConfigError) as exc:
            raise HTTPException(status_code=401, detail="Сессия истекла, войдите снова") from exc
        return UserContext(
            user_id=claims["sub"],
            role=claims["role"],
            companies=claims["companies"],
        )
    from app.api.v1.auth import auth_required

    if auth_required():
        raise HTTPException(status_code=401, detail="Войдите в аккаунт")
    raw_role = role or x_user_role
    normalized = normalize_role(raw_role)
    if raw_role and normalized is None:
        raise HTTPException(status_code=422, detail=f"Неизвестная роль. Допустимо: {', '.join(ROLES)}")
    return UserContext(user_id=(x_user_id or "").strip(), role=normalized)
