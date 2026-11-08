import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.api.v1.auth import AuthConfigError, auth_required, auth_strict, verify_demo_token
from app.llm import BudgetExceededError, LLMError
from app.llm.config import LLMConfigError
from app.modules.companies.relationships import RelationshipDataError
from app.modules.companies.repository import CompanyDataError
from app.modules.news import activity
from app.modules.news.scheduler import get_scheduler

class UTF8JSONResponse(JSONResponse):
    # Явная кодировка: без неё PowerShell 5.1 (Invoke-RestMethod) показывает кириллицу кракозябрами.
    media_type = "application/json; charset=utf-8"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Сбор новостей по расписанию включается переменной NEWS_COLLECT_INTERVAL_MIN.
    scheduler = get_scheduler()
    scheduler.start()
    yield
    scheduler.stop()


# Swagger на внешнем сервере (AUTH_STRICT=1) по умолчанию выключен: API_DOCS=1 — включить.
DOCS_ENABLED = os.getenv("API_DOCS", "0" if auth_strict() else "1") == "1"

app = FastAPI(
    title="Alfa-signal API",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
    description="Backend новостей аналитики для бизнес-решений",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
)


@app.middleware("http")
async def track_activity(request: Request, call_next):
    """Отметить активную сессию: по ней плановый сбор решает, обновлять ли ленту (activity.py)."""
    if request.url.path.startswith("/api/v1/") and not request.url.path.startswith("/api/v1/system"):
        parts = request.url.path.split("/")
        company = (
            request.headers.get("x-company-id")
            or request.query_params.get("company_id")
            or (parts[4] if len(parts) > 4 and parts[3] == "companies" else None)
        )
        activity.touch(company, request.headers.get("x-user-id"))
    return await call_next(request)


PUBLIC_API_PATHS = {"/api/v1/auth/login", "/api/v1/auth/roles", "/api/v1/auth/options", "/api/v1/auth/register"}
# Файл PDF открывается обычной ссылкой, без заголовков: токен для него допускается в ?access_token=.
QUERY_TOKEN_PATH = re.compile(r"^/api/v1/research/documents/[^/]+/file$")


def _request_token(request: Request) -> str:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.casefold() == "bearer" and token:
        return token
    if request.method == "GET" and QUERY_TOKEN_PATH.match(request.url.path):
        return request.query_params.get("access_token", "")
    return ""


@app.middleware("http")
async def require_auth(request: Request, call_next):
    """AUTH_STRICT / AUTH_REQUIRED: весь API — только с действующей сессией.

    Раньше вход проверяли отдельные эндпоинты, и часть API (в том числе платный разбор новости)
    оставалась открытой. Здесь граница одна для всех путей /api/, кроме входа.
    """
    path = request.url.path
    if (
        auth_required()
        and request.method != "OPTIONS"
        and path.startswith("/api/")
        and path not in PUBLIC_API_PATHS
    ):
        try:
            verify_demo_token(_request_token(request))
        except (ValueError, AuthConfigError):
            return UTF8JSONResponse(status_code=401, content={"detail": "Войдите в аккаунт"})
    return await call_next(request)


# Порядок: последний добавленный middleware — внешний. CORS снаружи, чтобы и ответ 401
# пришёл с CORS-заголовками; проверка входа — до отметки активности.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BudgetExceededError)
def budget_exceeded(_: Request, exc: BudgetExceededError) -> JSONResponse:
    return UTF8JSONResponse(status_code=429, content={"detail": str(exc)})


@app.exception_handler(LLMError)
def llm_error(_: Request, exc: LLMError) -> JSONResponse:
    return UTF8JSONResponse(status_code=502, content={"detail": f"Модель не ответила: {exc}"})


@app.exception_handler(LLMConfigError)
def llm_not_configured(_: Request, exc: LLMConfigError) -> JSONResponse:
    return UTF8JSONResponse(status_code=503, content={"detail": f"LLM не настроена: {exc}"})


@app.exception_handler(CompanyDataError)
@app.exception_handler(RelationshipDataError)
def data_error(_: Request, exc: Exception) -> JSONResponse:
    return UTF8JSONResponse(status_code=503, content={"detail": f"Данные компаний недоступны: {exc}"})


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(api_router)
