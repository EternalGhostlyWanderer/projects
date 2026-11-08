"""Single entry point for structured LLM calls: cache, budget guard, repair, call log."""
import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Optional, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from app.llm.config import THINK_OFF_STYLES, LLMSettings, ModelRole, get_settings
from app.llm.parsing import drop_extra_fields, extract_json_text, format_validation_error
from app.llm.store import LLMStore

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger(__name__)

# Дополнительная проверка ответа: вернуть список ошибок, пустой список — ответ принят.
Validator = Callable[[Any], list[str]]

GATEWAY_BUDGET_MARKER = "budget has been exceeded"
# Бесплатные тарифы: 429 по минутному лимиту пережидаем, по дневному — останавливаемся.
RATE_LIMIT_RETRIES = 3
RATE_LIMIT_MAX_WAIT = 30.0
DAILY_QUOTA_MARKERS = ("perday", "daily")
# Сколько не обращаться к маршруту после сбоя (секунды): модель отключена или ключ не принят —
# час (это настройка, сама не починится), дневной лимит — час, сеть и 5xx — минута.
COOLDOWN_CONFIG = 3600.0
COOLDOWN_QUOTA = 3600.0
COOLDOWN_TRANSIENT = 60.0
# Провайдер не понимает параметр отключения рассуждений или JSON-режима: повторить без него.
THINK_PARAM_ERROR = re.compile(r"reasoning|thinking|enable_thinking|chat_template_kwargs", re.IGNORECASE)
JSON_MODE_ERROR = re.compile(r"response_format|json_object|json mode", re.IGNORECASE)
# Модели без системных инструкций (Gemma через Gemini API: «Developer instruction is not enabled»):
# инструкция переносится в начало первого сообщения пользователя.
# Google иногда отвечает на неподдерживаемый параметр общей фразой без его названия.
GENERIC_INVALID_ERROR = re.compile(r"invalid argument", re.IGNORECASE)
SYSTEM_ROLE_ERROR = re.compile(r"developer instruction|system instruction|system role|system message", re.IGNORECASE)


def _fold_system(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Системные сообщения → в начало первого сообщения пользователя (смысл запроса тот же)."""
    system = "\n\n".join(str(item["content"]) for item in messages if item.get("role") == "system")
    rest = [dict(item) for item in messages if item.get("role") != "system"]
    if not system:
        return rest
    for item in rest:
        if item.get("role") == "user":
            item["content"] = f"{system}\n\n{item['content']}"
            return rest
    return [{"role": "user", "content": system}, *rest]


def _is_rate_limited(exc: Exception) -> bool:
    message = str(exc).lower()
    return getattr(exc, "status_code", None) == 429 or "error code: 429" in message or "rate limit" in message


def _is_daily_quota(message: str) -> bool:
    letters = "".join(char for char in message.lower() if char.isalpha())
    return any(marker in letters for marker in DAILY_QUOTA_MARKERS)


def _retry_after(exc: Exception, attempt: int) -> float:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        wait = float(headers.get("retry-after", ""))
    except (TypeError, ValueError):
        wait = 5.0 * 2**attempt
    return min(max(wait, 1.0), RATE_LIMIT_MAX_WAIT)

REPAIR_PROMPT = (
    "Ответ не прошёл проверку:\n{errors}\n\n"
    "Верни исправленный JSON-объект целиком, без Markdown и пояснений."
)


class LLMError(Exception):
    """Базовая ошибка обращения к LLM."""


class BudgetExceededError(LLMError):
    """Дневной лимит запросов или стоимости исчерпан."""


class LLMRequestError(LLMError):
    """Шлюз вернул ошибку или пустой ответ."""


class LLMResponseError(LLMError):
    """Ответ модели не прошёл разбор или проверку после всех попыток."""

    def __init__(self, message: str, errors: list[str], content: str) -> None:
        super().__init__(message)
        self.errors = errors
        self.content = content


@dataclass
class LLMResult(Generic[T]):
    value: T
    model: str
    cached: bool
    attempts: int
    usage: list[dict[str, Any]] = field(default_factory=list)
    # Какой провайдер ответил: основной или запасной из LLM_FALLBACKS.
    provider: str = ""


class RouteFailure(Exception):
    """Маршрут (провайдер + модель) не ответил: запрос переходит к следующему маршруту."""

    def __init__(self, error: LLMError, cooldown: float, status: Optional[int] = None) -> None:
        super().__init__(str(error))
        self.error = error
        self.cooldown = cooldown
        self.status = status


@dataclass
class _Route:
    provider: str
    base_url: str
    model: str
    think_style: str
    api_key: str = field(repr=False)
    client: Any = field(default=None, repr=False)

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.base_url}|{self.model}"

    def think_off_body(self) -> Optional[dict]:
        style = THINK_OFF_STYLES.get(self.think_style)
        return copy.deepcopy(style) if style else None


def _status(exc: Exception) -> Optional[int]:
    status = getattr(exc, "status_code", None)
    if status is None:
        match = re.search(r"error code: (\d{3})", str(exc).lower())
        status = int(match.group(1)) if match else None
    return status


def _usage_summary(response: Any) -> dict[str, Any]:
    usage = getattr(response, "usage", None)
    if not usage:
        return {}
    data = usage.model_dump()
    details = data.get("completion_tokens_details") or {}
    return {
        "prompt_tokens": data.get("prompt_tokens"),
        "completion_tokens": data.get("completion_tokens"),
        "reasoning_tokens": details.get("reasoning_tokens"),
        "cost": data.get("cost"),
    }


def _cache_key(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class LLMClient:
    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        client: Optional[Any] = None,
        store: Optional[LLMStore] = None,
        fallback_clients: Optional[dict[str, Any]] = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or self._openai(self.settings.api_key, self.settings.base_url)
        self.store = store or LLMStore(self.settings.state_db)
        self._sleep = time.sleep
        self._clock = time.monotonic
        # Клиенты запасных маршрутов (provider → клиент); в тестах подменяются.
        self._fallback_clients = dict(fallback_clients or {})
        self._cooldown_until: dict[str, float] = {}
        # Маршруты, которым не отправляем параметр рассуждений или JSON-режим: провайдер их отверг.
        self._no_think: set[str] = set()
        self._no_json: set[str] = set()
        self._no_system: set[str] = set()

    def _openai(self, api_key: str, base_url: str) -> Any:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=self.settings.timeout, max_retries=0)

    def _redact(self, message: str) -> str:
        for key in {self.settings.api_key, *(route.api_key for route in self.settings.fallbacks)}:
            if key:
                message = message.replace(key, "[REDACTED_API_KEY]")
        return message

    def check_budget(self) -> None:
        usage = self.store.daily_usage()
        request_limit = self.settings.daily_request_limit
        cost_limit = self.settings.daily_cost_limit

        if request_limit is not None and usage["requests"] >= request_limit:
            raise BudgetExceededError(
                f"Дневной лимит запросов к LLM исчерпан: {usage['requests']}/{request_limit}"
            )
        if cost_limit is not None and usage["cost"] >= cost_limit:
            raise BudgetExceededError(
                f"Дневной лимит стоимости LLM исчерпан: {usage['cost']:.4f}/{cost_limit}"
            )

    def routes(self, role: ModelRole = "analyze", model: Optional[str] = None) -> list[_Route]:
        """Основной маршрут (модель по роли) и запасные из LLM_FALLBACKS — по порядку."""
        primary = _Route(
            self.settings.provider,
            self.settings.base_url,
            model or self.settings.model_for(role),
            self.settings.think_style,
            self.settings.api_key,
            self.client,
        )
        result = [primary]
        for fallback in self.settings.fallbacks:
            client = self._fallback_clients.get(fallback.provider)
            if client is None:
                client = self._fallback_clients[fallback.provider] = self._openai(fallback.api_key, fallback.base_url)
            route = _Route(
                fallback.provider, fallback.base_url, fallback.model, fallback.think_style, fallback.api_key, client
            )
            if route.key not in {item.key for item in result}:
                result.append(route)
        return result

    def _available(self, routes: list[_Route]) -> list[_Route]:
        """Маршруты не на паузе после сбоя; если на паузе все — пробуем все (могли восстановиться)."""
        now = self._clock()
        ready = [route for route in routes if self._cooldown_until.get(route.key, 0.0) <= now]
        return ready or routes

    def _create(
        self,
        route: _Route,
        request: dict[str, Any],
        *,
        task: str,
        attempt: int,
        started: float,
        can_wait: bool,
    ) -> Any:
        """Запрос к провайдеру маршрута. 429 по минутному лимиту без запасного маршрута — пауза и повтор;
        с запасным — сразу к нему. Любая ошибка запроса — RouteFailure с паузой для маршрута."""
        retries = RATE_LIMIT_RETRIES if can_wait else 0
        for retry in range(retries + 1):
            try:
                return route.client.chat.completions.create(**request)
            except Exception as exc:
                message = self._redact(f"{type(exc).__name__}: {exc}")
                seconds = round(time.perf_counter() - started, 2)
                daily = _is_daily_quota(message)
                limited = _is_rate_limited(exc)
                if limited and not daily and retry < retries:
                    wait = _retry_after(exc, retry)
                    self.store.log_call(
                        task=task, model=route.model, status="rate_limited", cached=False, attempt=attempt,
                        seconds=seconds, error=f"429, повтор через {wait:.0f} с: {message}"[:2000],
                    )
                    self._sleep(wait)
                    continue
                self.store.log_call(
                    task=task, model=route.model, status="request_error", cached=False, attempt=attempt,
                    seconds=seconds, error=message,
                )
                status = _status(exc)
                if GATEWAY_BUDGET_MARKER in message.lower():
                    error: LLMError = BudgetExceededError("Дневной бюджет шлюза исчерпан; сброс в 03:00 МСК")
                    cooldown = COOLDOWN_QUOTA
                elif limited and daily:
                    error = BudgetExceededError(f"Дневной лимит бесплатного тарифа провайдера исчерпан: {message}")
                    cooldown = COOLDOWN_QUOTA
                elif limited:
                    error = LLMRequestError(f"Ошибка запроса к LLM: {message}")
                    cooldown = _retry_after(exc, 0)
                elif status in (401, 403, 404) or "api key" in message.lower():
                    error = LLMRequestError(f"Ошибка запроса к LLM: {message}")
                    cooldown = COOLDOWN_CONFIG
                else:
                    error = LLMRequestError(f"Ошибка запроса к LLM: {message}")
                    cooldown = COOLDOWN_TRANSIENT
                # Исходное исключение — в __cause__: по нему распознают обрывы связи (bank research).
                error.__cause__ = exc
                raise RouteFailure(error, cooldown, status) from exc
        raise AssertionError("unreachable")  # pragma: no cover

    def _parse(
        self,
        content: str,
        response_model: type[T],
        validate: Optional[Validator],
    ) -> tuple[Optional[T], list[str]]:
        try:
            data = json.loads(extract_json_text(content))
        except json.JSONDecodeError as exc:
            return None, [f"$: Invalid JSON: {exc}"]
        try:
            value = response_model.model_validate(data)
        except ValidationError as exc:
            if not drop_extra_fields(data, exc):
                return None, format_validation_error(exc)
            try:
                value = response_model.model_validate(data)
            except ValidationError as retry_exc:
                return None, format_validation_error(retry_exc)
        errors = validate(value) if validate else []
        return (None, errors) if errors else (value, [])

    def chat_json(
        self,
        messages: list[dict[str, Any]],
        response_model: type[T],
        *,
        task: str,
        role: ModelRole = "analyze",
        model: Optional[str] = None,
        max_tokens: int = 3000,
        temperature: Optional[float] = 0.2,
        think: bool = False,
        use_cache: bool = True,
        validate: Optional[Validator] = None,
        max_repairs: int = 1,
        timeout: Optional[float] = None,
    ) -> LLMResult[T]:
        """Запрос с проверкой ответа; основной маршрут не ответил или не справился — следующий из LLM_FALLBACKS.

        Свой дневной лимит (check_budget) общий для всех маршрутов и останавливает сразу. Ответ, не
        прошедший проверку после исправления (LLMResponseError), тоже передаётся следующей модели:
        бесплатные модели нередко пропускают обязательные поля большого контракта.
        """
        routes = self._available(self.routes(role, model))
        last_error: Optional[LLMError] = None
        for index, route in enumerate(routes):
            has_next = index < len(routes) - 1
            try:
                return self._chat_on_route(
                    route, messages, response_model, task=task, max_tokens=max_tokens, temperature=temperature,
                    think=think, use_cache=use_cache, validate=validate,
                    # С запасной моделью — одна попытка исправления: слабая бесплатная модель редко
                    # исправляется со второго раза, а каждая попытка тратит дневной лимит.
                    max_repairs=min(max_repairs, 1) if has_next else max_repairs,
                    timeout=timeout, can_wait=not has_next,
                )
            except RouteFailure as exc:
                last_error = exc.error
                self._cooldown_until[route.key] = self._clock() + exc.cooldown
                reason = str(exc.error)
            except LLMResponseError as exc:
                # Модель ответила, но не по контракту и после исправления: разбор переходит к следующей.
                # Маршрут на паузу не ставится — с другим запросом эта модель может справиться.
                last_error = exc
                reason = f"{exc}: {'; '.join(exc.errors)}"
            if has_next:
                logger.warning(
                    "LLM %s/%s не справилась (%s), запрос уходит запасной: %s/%s",
                    route.provider, route.model, reason[:200], routes[index + 1].provider, routes[index + 1].model,
                )
        assert last_error is not None
        raise last_error

    def _request(self, route: _Route, messages: list[dict[str, Any]], *, max_tokens: int,
                 temperature: Optional[float], think: bool) -> dict[str, Any]:
        if route.key in self._no_system:
            messages = _fold_system(messages)
        request: dict[str, Any] = {"model": route.model, "messages": list(messages), "max_tokens": max_tokens}
        if temperature is not None:
            request["temperature"] = temperature
        if self.settings.json_mode and route.key not in self._no_json:
            request["response_format"] = {"type": "json_object"}
        if not think and route.key not in self._no_think:
            body = route.think_off_body()
            if body:
                request["extra_body"] = body
        return request

    def _chat_on_route(
        self,
        route: _Route,
        messages: list[dict[str, Any]],
        response_model: type[T],
        *,
        task: str,
        max_tokens: int,
        temperature: Optional[float],
        think: bool,
        use_cache: bool,
        validate: Optional[Validator],
        max_repairs: int,
        timeout: Optional[float],
        can_wait: bool,
    ) -> LLMResult[T]:
        model_id = route.model
        request = self._request(route, messages, max_tokens=max_tokens, temperature=temperature, think=think)
        cache_key = _cache_key(
            {
                **request,
                "response_model": response_model.__name__,
                "schema": response_model.model_json_schema(),
            }
        )
        # Таймаут не входит в ключ кеша: на ответ он не влияет.
        if timeout is not None:
            request["timeout"] = timeout

        if use_cache:
            cached = self.store.get_cached(cache_key)
            if cached is not None:
                value, errors = self._parse(cached, response_model, validate)
                if value is not None:
                    self.store.log_call(
                        task=task, model=model_id, status="ok", cached=True, attempt=0
                    )
                    return LLMResult(value=value, model=model_id, cached=True, attempts=0, provider=route.provider)

        usages: list[dict[str, Any]] = []
        content = ""
        errors: list[str] = []
        adjusted: set[str] = set()

        attempt = 1
        while attempt <= max_repairs + 1:
            self.check_budget()
            started = time.perf_counter()

            try:
                response = self._create(
                    route, request, task=task, attempt=attempt, started=started, can_wait=can_wait
                )
            except RouteFailure as exc:
                # Провайдер отверг параметр рассуждений, JSON-режим или системную инструкцию (400) —
                # повтор без этого (каждая поправка — один раз), поправка запоминается для маршрута.
                text = str(exc.error)
                if exc.status == 400:
                    generic = bool(GENERIC_INVALID_ERROR.search(text))
                    if "think" not in adjusted and "extra_body" in request and (
                        THINK_PARAM_ERROR.search(text) or generic
                    ):
                        request.pop("extra_body")
                        self._no_think.add(route.key)
                        adjusted.add("think")
                        continue
                    if "json" not in adjusted and "response_format" in request and (
                        JSON_MODE_ERROR.search(text) or generic
                    ):
                        request.pop("response_format")
                        self._no_json.add(route.key)
                        adjusted.add("json")
                        continue
                    if "system" not in adjusted and SYSTEM_ROLE_ERROR.search(text):
                        request["messages"] = _fold_system(request["messages"])
                        self._no_system.add(route.key)
                        adjusted.add("system")
                        continue
                raise

            seconds = round(time.perf_counter() - started, 2)
            usage = _usage_summary(response)
            usages.append(usage)
            choice = response.choices[0]
            content = choice.message.content or ""

            if not content.strip():
                reason = (
                    "ответ оборван по лимиту токенов"
                    if choice.finish_reason == "length"
                    else "пустой ответ"
                )
                self.store.log_call(
                    task=task,
                    model=model_id,
                    status="empty",
                    cached=False,
                    attempt=attempt,
                    seconds=seconds,
                    usage=usage,
                    error=reason,
                )
                # Пустой ответ — не повод ставить маршрут на паузу, но запасной может справиться.
                raise RouteFailure(LLMRequestError(f"LLM вернула {reason}"), 0.0)

            value, errors = self._parse(content, response_model, validate)
            self.store.log_call(
                task=task,
                model=model_id,
                status="ok" if value is not None else "invalid",
                cached=False,
                attempt=attempt,
                seconds=seconds,
                usage=usage,
                error="; ".join(errors)[:2000] or None,
            )

            if value is not None:
                if use_cache:
                    self.store.put_cached(cache_key, model_id, content)
                return LLMResult(
                    value=value,
                    model=model_id,
                    cached=False,
                    attempts=attempt,
                    usage=usages,
                    provider=route.provider,
                )

            request["messages"] = [
                *request["messages"],
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": REPAIR_PROMPT.format(
                        errors="\n".join(f"- {error}" for error in errors[:20])
                    ),
                },
            ]
            attempt += 1

        raise LLMResponseError(
            "Ответ LLM не соответствует контракту",
            errors=errors,
            content=content,
        )


_default_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
