"""Sign-in: demo accounts locally, protected accounts on a public server.

В настоящем интернет-банке пользователь входит как физлицо и получает доступ к нескольким компаниям;
проверка полномочий уже выполнена банком (вопрос 32). Здесь пользователи задаются в AUTH_USERS
(или DEMO_USERS) переменной окружения.

На внешнем сервере (AUTH_STRICT=1, docs/deployment.md):
- вход обязателен для всего API, кроме /auth/login и /auth/roles (middleware в main.py);
- пароли только в виде хеша pbkdf2_sha256 (scripts/hash_password.py), демо-учётки не действуют;
- DEMO_AUTH_SECRET обязателен и не короче 32 символов;
- после серии неверных паролей вход для логина и адреса блокируется на минуту.

Регистрация без администратора (AUTH_REGISTRATION=1, по умолчанию включена): POST /auth/register
создаёт учётную запись в базе (таблица accounts, пароль — хеш). Если задан AUTH_REGISTRATION_CODE,
без этого кода зарегистрироваться нельзя (закрытый круг пользователей). Профиль — имя, роль, пароль —
меняется через PATCH /auth/me; у пользователей из AUTH_USERS правки хранятся в базе, а удаление
из AUTH_USERS по-прежнему закрывает доступ.

Сессия скользящая: токен живёт AUTH_SESSION_HOURS (24 ч) и продлевается через /auth/refresh,
пока сайт открыт (фронт перезапрашивает ленту раз в 5 минут и продлевает токен после половины срока).
Без визитов дольше срока — снова вход; независимо от активности — вход не реже, чем раз в
AUTH_SESSION_MAX_DAYS (7) дней. Удалённый из AUTH_USERS пользователь не продлит сессию.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import deque
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import store_dependency
from app.db.store import AppStore
from app.modules.news import activity
from app.modules.news.scheduler import get_scheduler
from app.modules.personalization.roles import ROLE_LABELS, ROLES, normalize_role

router = APIRouter(prefix="/auth", tags=["Auth"])

# Формат: "логин:пароль:U_1|U_2:роль:Имя;…" — пустой список компаний = все из VITE_COMPANY_IDS,
# роль и имя необязательны (роль по умолчанию — cfo). user_id пользователя — его логин.
# По умолчанию — два сотрудника одной компании с разными ролями: у них разная лента.
DEFAULT_DEMO_USERS = (
    "demo:alfa-signal::cfo:Пример Примерович;"
    "buh:alfa-signal::accountant:Ольга Бухгалтерова;"
    "owner:alfa-signal::owner:Игорь Собственников"
)
DEFAULT_ROLE = "cfo"
SESSION_HOURS_DEFAULT = 24
SESSION_MAX_DAYS_DEFAULT = 7
LOCAL_SECRET = "local-demo-secret-change-me"
EXAMPLE_SECRETS = {LOCAL_SECRET, "change-this-to-a-random-secret"}
MIN_SECRET_LENGTH = 32

HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 390_000

# Защита от подбора: не больше LOGIN_MAX_FAILURES неверных паролей за окно на логин и на адрес.
LOGIN_WINDOW_SECONDS = 60
# Регистрация: не больше REGISTER_MAX_PER_IP новых учётных записей с одного адреса за час.
REGISTER_WINDOW_SECONDS = 3600
REGISTER_MAX_PER_IP = 5
LOGIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")
MIN_PASSWORD_LENGTH = 10
LOGIN_MAX_FAILURES = 5
IP_MAX_FAILURES = 20

logger = logging.getLogger(__name__)


class AuthConfigError(RuntimeError):
    """Вход на сервере не настроен безопасно (AUTH_STRICT=1)."""


def auth_strict() -> bool:
    return os.getenv("AUTH_STRICT", "0") == "1"


def auth_required() -> bool:
    """Без входа API не отвечает: AUTH_STRICT=1, AUTH_REQUIRED=1 или (как раньше) DEMO_AUTH_REQUIRED=1."""
    return auth_strict() or "1" in (os.getenv("AUTH_REQUIRED", "0"), os.getenv("DEMO_AUTH_REQUIRED", "0"))


def _auth_secret() -> bytes:
    secret = os.getenv("DEMO_AUTH_SECRET", "").strip()
    if auth_strict() and (len(secret) < MIN_SECRET_LENGTH or secret in EXAMPLE_SECRETS):
        raise AuthConfigError(
            f"DEMO_AUTH_SECRET должен быть случайной строкой не короче {MIN_SECRET_LENGTH} символов "
            "(openssl rand -hex 32)"
        )
    return (secret or LOCAL_SECRET).encode()


def hash_password(password: str, *, iterations: int = HASH_ITERATIONS) -> str:
    """Хеш пароля для AUTH_USERS: pbkdf2_sha256.итерации.соль.хеш (base64url).

    Разделитель — точка, а не «$»: Docker Compose подставляет переменные по «$» в .env.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    encode = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip("=")  # noqa: E731
    return f"{HASH_SCHEME}.{iterations}.{encode(salt)}.{encode(digest)}"


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def is_password_hash(value: str) -> bool:
    return value.startswith(f"{HASH_SCHEME}.")


def verify_password(password: str, stored: str) -> bool:
    """Сравнение за постоянное время; хранимое значение — хеш или (только локально) открытый пароль."""
    if is_password_hash(stored):
        try:
            _, iterations, salt, digest = stored.split(".")
            candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), _b64decode(salt), int(iterations))
            return hmac.compare_digest(candidate, _b64decode(digest))
        except (ValueError, TypeError):
            return False
    if auth_strict():
        return False
    return hmac.compare_digest(stored.encode(), password.encode())


class LoginThrottle:
    """Счётчик неверных паролей в памяти процесса (backend запускается одним процессом)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str, now: float) -> deque[float]:
        items = self._failures.setdefault(key, deque())
        while items and now - items[0] > LOGIN_WINDOW_SECONDS:
            items.popleft()
        return items

    def retry_after(self, login: str, ip: str) -> int:
        now = time.monotonic()
        with self._lock:
            waits = [
                int(LOGIN_WINDOW_SECONDS - (now - items[0])) + 1
                for key, limit in ((f"login:{login}", LOGIN_MAX_FAILURES), (f"ip:{ip}", IP_MAX_FAILURES))
                if len(items := self._recent(key, now)) >= limit
            ]
        return max(waits, default=0)

    def failed(self, login: str, ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            for key in (f"login:{login}", f"ip:{ip}"):
                self._recent(key, now).append(now)

    def succeeded(self, login: str) -> None:
        with self._lock:
            self._failures.pop(f"login:{login}", None)

    def reset(self) -> None:
        with self._lock:
            self._failures.clear()


login_throttle = LoginThrottle()


def client_ip(request: Request) -> str:
    """Адрес клиента: Nginx фронтенда передаёт его в X-Real-IP (порт backend наружу не открыт)."""
    return request.headers.get("x-real-ip") or (request.client.host if request.client else "unknown")


def _env_number(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def session_ttl_seconds() -> int:
    """Сколько живёт токен без продления (AUTH_SESSION_HOURS)."""
    return int(_env_number("AUTH_SESSION_HOURS", SESSION_HOURS_DEFAULT) * 3600)


def session_max_seconds() -> int:
    """Предел сессии с момента входа, сколько ни продлевай (AUTH_SESSION_MAX_DAYS)."""
    return int(_env_number("AUTH_SESSION_MAX_DAYS", SESSION_MAX_DAYS_DEFAULT) * 86400)


def _encode_token(user: "DemoUser", auth_time: Optional[int] = None) -> tuple[str, int]:
    now = int(time.time())
    auth_time = auth_time or now
    expires_at = min(now + session_ttl_seconds(), auth_time + session_max_seconds())
    payload = {
        "sub": user.login,
        "role": user.role,
        "companies": user.companies,
        "auth": auth_time,
        "exp": expires_at,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_auth_secret(), body, hashlib.sha256).digest()
    token = body + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    return token.decode(), expires_at


def verify_demo_token(token: str) -> dict[str, Any]:
    try:
        if not token or len(token) > 4096:
            raise ValueError
        body, encoded_signature = token.split(".", 1)
        expected = hmac.new(_auth_secret(), body.encode(), hashlib.sha256).digest()
        signature = base64.urlsafe_b64decode(encoded_signature + "=" * (-len(encoded_signature) % 4))
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if int(payload["exp"]) <= int(time.time()):
            raise ValueError
        if not isinstance(payload.get("sub"), str) or not isinstance(payload.get("role"), str):
            raise ValueError
        if not isinstance(payload.get("companies"), list):
            raise ValueError
        return payload
    except (KeyError, TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError("Недействительная demo-сессия") from None


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class DemoUser(BaseModel):
    login: str
    password: str
    companies: list[str]
    role: str
    name: str


def registration_enabled() -> bool:
    return os.getenv("AUTH_REGISTRATION", "1") != "0"


def _users_spec() -> str:
    spec = (os.getenv("AUTH_USERS") or os.getenv("DEMO_USERS") or "").strip()
    if spec:
        return spec
    if auth_strict():
        if registration_enabled():
            return ""  # пользователи регистрируются сами
        raise AuthConfigError(
            "AUTH_USERS не задан и регистрация выключена: на сервере демо-учётки отключены "
            "(scripts/hash_password.py или AUTH_REGISTRATION=1)"
        )
    return DEFAULT_DEMO_USERS


def _demo_users() -> dict[str, DemoUser]:
    users: dict[str, DemoUser] = {}
    # В хеше нет «:» и «;» — формат строки прежний.
    for entry in _users_spec().split(";"):
        if not entry.strip():
            continue
        parts = [part.strip() for part in entry.strip().split(":")] + ["", "", ""]
        login, password, companies, role, name = parts[:5]
        if login and password:
            users[login] = DemoUser(
                login=login,
                password=password,
                companies=[item.strip() for item in companies.split("|") if item.strip()],
                role=normalize_role(role) or DEFAULT_ROLE,
                name=name or login,
            )
    return users


def find_user(store: AppStore, login: str) -> Optional[DemoUser]:
    """Пользователь из AUTH_USERS (с правками профиля из базы) или зарегистрированный на сайте.

    Пользователь из AUTH_USERS, которого администратор удалил, не входит, даже если правки остались.
    """
    env_user = _demo_users().get(login)
    account = store.get_account(login)
    if env_user is not None:
        if account and account["origin"] == "env":
            return env_user.model_copy(
                update={"password": account["password_hash"], "name": account["name"], "role": account["role"]}
            )
        return env_user
    if account and account["origin"] == "self":
        return DemoUser(
            login=account["login"],
            password=account["password_hash"],
            companies=account["companies"],
            role=normalize_role(account["role"]) or DEFAULT_ROLE,
            name=account["name"],
        )
    return None


class RegisterThrottle:
    """Сколько учётных записей создано с адреса за последний час (в памяти процесса)."""

    def __init__(self) -> None:
        self._created: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allowed(self, ip: str) -> bool:
        now = time.monotonic()
        with self._lock:
            items = self._created.setdefault(ip, deque())
            while items and now - items[0] > REGISTER_WINDOW_SECONDS:
                items.popleft()
            return len(items) < REGISTER_MAX_PER_IP

    def created(self, ip: str) -> None:
        with self._lock:
            self._created.setdefault(ip, deque()).append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._created.clear()


register_throttle = RegisterThrottle()


# Хеш для несуществующего логина: проверка занимает столько же времени, и логин не угадать по задержке.
_DUMMY_HASH = hash_password(secrets.token_hex(8))


@router.post("/login")
def demo_login(
    body: LoginRequest, request: Request, store: AppStore = Depends(store_dependency)
) -> dict[str, Any]:
    """Вход возвращает пользователя и подписанный токен (Authorization: Bearer)."""
    login = body.login.strip()
    ip = client_ip(request)
    wait = login_throttle.retry_after(login, ip)
    if wait:
        raise HTTPException(
            status_code=429,
            detail=f"Слишком много неверных попыток входа. Повторите через {wait} с.",
            headers={"Retry-After": str(wait)},
        )
    try:
        # Зарегистрированные логины — в нижнем регистре; «Ivan» и «ivan» — один пользователь.
        user = find_user(store, login) or find_user(store, login.lower())
        _auth_secret()
    except AuthConfigError as exc:
        logger.error("Вход не настроен: %s", exc)
        raise HTTPException(status_code=503, detail="Вход на сервере не настроен администратором") from exc
    if user is not None and auth_strict() and not is_password_hash(user.password):
        logger.error("У пользователя %s пароль не в виде хеша: при AUTH_STRICT=1 вход запрещён", user.login)
    valid = verify_password(body.password, user.password if user else _DUMMY_HASH)
    if user is None or not valid:
        login_throttle.failed(login, ip)
        logger.warning("Неудачный вход: логин=%r адрес=%s", login[:100], ip)
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    login_throttle.succeeded(login)
    # Сценарий «при входе»: сессия становится активной, и если лента старше
    # NEWS_REFRESH_ON_LOGIN_MIN минут, сбор запускается в фоне.
    for company_id in user.companies or [""]:
        activity.touch(company_id, user.login)
    refresh = get_scheduler().refresh_if_stale(trigger="login")
    return {"refresh": refresh, **_session_response(user)}


def _session_response(user: "DemoUser", auth_time: Optional[int] = None) -> dict[str, Any]:
    access_token, expires_at = _encode_token(user, auth_time)
    now = int(time.time())
    return {
        "login": user.login,
        "user_id": user.login,
        "name": user.name,
        "role": user.role,
        "role_label": ROLE_LABELS[user.role],
        "companies": user.companies,
        "demo": not auth_strict(),
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        # Фронт продлевает сессию после половины срока токена.
        "refresh_after": now + (expires_at - now) // 2,
    }


def _session_claims(request: Request) -> dict[str, Any]:
    scheme, _, token = (request.headers.get("authorization") or "").partition(" ")
    if scheme.casefold() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Войдите в аккаунт")
    try:
        return verify_demo_token(token)
    except (ValueError, AuthConfigError) as exc:
        raise HTTPException(status_code=401, detail="Сессия истекла, войдите снова") from exc


@router.get("/me")
def current_session(
    claims: dict[str, Any] = Depends(_session_claims), store: AppStore = Depends(store_dependency)
) -> dict[str, Any]:
    """Профиль текущего пользователя: имя, роль, компании, срок сессии."""
    user = find_user(store, claims["sub"])
    account = store.get_account(claims["sub"])
    return {
        "login": claims["sub"],
        "name": user.name if user else claims["sub"],
        "role": user.role if user else claims["role"],
        "role_label": ROLE_LABELS.get(user.role if user else claims["role"], ""),
        "companies": user.companies if user else claims["companies"],
        "registered": bool(account and account["origin"] == "self"),
        "expires_at": claims["exp"],
    }


@router.post("/refresh")
def refresh_session(
    claims: dict[str, Any] = Depends(_session_claims), store: AppStore = Depends(store_dependency)
) -> dict[str, Any]:
    """Продлить действующую сессию (скользящий срок); имя, роль и компании — текущие."""
    try:
        user = find_user(store, claims["sub"])
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail="Вход на сервере не настроен администратором") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Учётная запись отключена, войдите снова")
    # Токены, выданные до появления поля auth, отсчитывают предел от своего срока.
    auth_time = int(claims.get("auth") or int(claims["exp"]) - session_ttl_seconds())
    return _session_response(user, auth_time)


class RegisterRequest(BaseModel):
    login: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    role: str = Field(default=DEFAULT_ROLE, max_length=40)
    code: str = Field(default="", max_length=200)


def _check_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=422, detail=f"Пароль должен быть не короче {MIN_PASSWORD_LENGTH} символов")


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Укажите имя")
    return name


def _role(value: str) -> str:
    role = normalize_role(value)
    if role is None:
        raise HTTPException(status_code=422, detail=f"Неизвестная роль. Допустимо: {', '.join(ROLES)}")
    return role


@router.get("/options")
def auth_options() -> dict[str, Any]:
    """Что показать на экране входа: можно ли зарегистрироваться и нужен ли код приглашения."""
    return {
        "registration": registration_enabled(),
        "registration_code_required": bool(os.getenv("AUTH_REGISTRATION_CODE", "").strip()),
        "min_password_length": MIN_PASSWORD_LENGTH,
        "roles": [{"id": role, "label": ROLE_LABELS[role]} for role in ROLES],
    }


@router.post("/register", status_code=201)
def register(
    body: RegisterRequest, request: Request, store: AppStore = Depends(store_dependency)
) -> dict[str, Any]:
    """Регистрация без администратора: учётная запись сразу активна, ответ — как у входа."""
    if not registration_enabled():
        raise HTTPException(status_code=403, detail="Регистрация на этом сервере выключена")
    expected_code = os.getenv("AUTH_REGISTRATION_CODE", "").strip()
    if expected_code and not hmac.compare_digest(body.code.strip().encode(), expected_code.encode()):
        raise HTTPException(status_code=403, detail="Неверный код приглашения")
    ip = client_ip(request)
    if not register_throttle.allowed(ip):
        raise HTTPException(status_code=429, detail="Слишком много регистраций с вашего адреса, повторите через час")
    login = body.login.strip().lower()
    if not LOGIN_PATTERN.match(login):
        raise HTTPException(
            status_code=422,
            detail="Логин: 3–32 символа, латинские буквы, цифры, точка, дефис или подчёркивание",
        )
    _check_password(body.password)
    name, role = _clean_name(body.name), _role(body.role)
    try:
        _auth_secret()
        taken = find_user(store, login) is not None or store.get_account(login) is not None
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail="Вход на сервере не настроен администратором") from exc
    if taken:
        raise HTTPException(status_code=409, detail="Такой логин уже занят")
    # Компании не ограничены: пользователь выбирает свою в шапке сайта (как демо-учётки без списка).
    store.save_account(
        login=login, password_hash=hash_password(body.password), name=name, role=role, companies=[], origin="self"
    )
    register_throttle.created(ip)
    logger.info("Зарегистрирован пользователь %s (адрес %s)", login, ip)
    user = find_user(store, login)
    assert user is not None
    activity.touch("", login)
    return {"refresh": get_scheduler().refresh_if_stale(trigger="login"), **_session_response(user)}


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=80)
    role: Optional[str] = Field(default=None, max_length=40)
    current_password: str = Field(default="", max_length=200)
    new_password: str = Field(default="", max_length=200)


@router.patch("/me")
def update_profile(
    body: ProfileUpdate,
    claims: dict[str, Any] = Depends(_session_claims),
    store: AppStore = Depends(store_dependency),
) -> dict[str, Any]:
    """Изменить имя, роль или пароль; ответ — новая сессия с обновлёнными данными."""
    try:
        user = find_user(store, claims["sub"])
    except AuthConfigError as exc:
        raise HTTPException(status_code=503, detail="Вход на сервере не настроен администратором") from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Учётная запись отключена, войдите снова")
    password_hash = user.password if is_password_hash(user.password) else hash_password(user.password)
    if body.new_password:
        if not verify_password(body.current_password, user.password):
            raise HTTPException(status_code=403, detail="Текущий пароль указан неверно")
        _check_password(body.new_password)
        password_hash = hash_password(body.new_password)
    name = _clean_name(body.name) if body.name is not None else user.name
    role = _role(body.role) if body.role is not None else user.role
    account = store.get_account(user.login)
    origin = account["origin"] if account else ("env" if user.login in _demo_users() else "self")
    store.save_account(
        login=user.login, password_hash=password_hash, name=name, role=role, companies=user.companies, origin=origin
    )
    updated = find_user(store, user.login)
    assert updated is not None
    auth_time = int(claims.get("auth") or int(claims["exp"]) - session_ttl_seconds())
    return _session_response(updated, auth_time)


@router.get("/roles")
def list_roles() -> dict[str, Any]:
    """Роли для переключателя на фронте: роль можно сменить вручную (вебинар, вопрос 31)."""
    return {"items": [{"id": role, "label": ROLE_LABELS[role]} for role in ROLES], "default": DEFAULT_ROLE}
