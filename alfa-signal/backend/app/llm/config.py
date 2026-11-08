"""LLM gateway settings read from backend/.env."""
import copy
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")
logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://changellenge.up.railway.app/v1"
DEFAULT_MODEL = "qwen/qwen3.6-35b-a3b"


@dataclass(frozen=True)
class ProviderPreset:
    base_url: str
    model: str
    think_style: str
    key_required: bool = True


# Готовые настройки OpenAI-совместимых провайдеров с бесплатным доступом (LLM_PROVIDER).
# LLM_BASE_URL, LLM_MODEL и LLM_THINK_STYLE, если заданы, имеют приоритет над пресетом.
# Списки бесплатных моделей у провайдеров часто меняются — сверяйтесь с docs/free-llm-providers.md.
PROVIDER_PRESETS: dict[str, ProviderPreset] = {
    # Шлюз организаторов хакатона (ключ команды истёк вместе с хакатоном).
    "hackathon": ProviderPreset(DEFAULT_BASE_URL, DEFAULT_MODEL, "openrouter"),
    # openrouter/free сам выбирает доступную бесплатную модель; можно указать конкретную ...:free.
    "openrouter": ProviderPreset("https://openrouter.ai/api/v1", "openrouter/free", "openrouter"),
    # llama-3.3-70b-versatile Groq убрал (октябрь 2026); Qwen хорошо пишет по-русски и отвечает в JSON.
    "groq": ProviderPreset("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b", "none"),
    # Бесплатный ключ: у gemini-3.8-flash всего 20 запросов в сутки (октябрь 2026), у Flash-Lite лимит
    # в разы больше — основной Flash-Lite (псевдоним на актуальную версию), Flash — в LLM_FALLBACKS.
    # Параметр отключения рассуждений не отправляется: Flash-Lite отвечает на reasoning_effort=none
    # «invalid argument», Gemma — «Thinking budget is not supported».
    "gemini": ProviderPreset(
        "https://generativelanguage.googleapis.com/v1beta/openai/", "gemini-flash-lite-latest", "none"
    ),
    "mistral": ProviderPreset("https://api.mistral.ai/v1", "mistral-small-latest", "none"),
    # DeepSeek напрямую — платный, но дешёвый (оплата по факту); deepseek-chat — псевдоним на актуальную
    # модель без рассуждений. Бесплатно DeepSeek доступен через OpenRouter (модели с суффиксом :free).
    "deepseek": ProviderPreset("https://api.deepseek.com/v1", "deepseek-chat", "none"),
    # Локальная модель без ключа и лимитов; из Docker — http://host.docker.internal:11434/v1.
    "ollama": ProviderPreset("http://localhost:11434/v1", "qwen3:14b", "none", key_required=False),
}
DEFAULT_STATE_DB = BACKEND_DIR / "var" / "llm.sqlite3"

ModelRole = Literal["extract", "analyze", "verify", "vision"]

# Единственная разрешённая модель для изображений; остальные роли по умолчанию — LLM_MODEL.
ROLE_DEFAULT_MODELS: dict[str, str] = {
    "vision": "qwen/qwen3-vl-30b-a3b-instruct",
}

# Способы отключить рассуждения; рабочий стиль для шлюза организаторов
# определяется через scripts/test_connection.py --try-all.
THINK_OFF_STYLES: dict[str, dict] = {
    "openrouter": {"reasoning": {"enabled": False}},
    "effort": {"reasoning": {"effort": "none"}},
    "qwen": {"chat_template_kwargs": {"enable_thinking": False}},
    "flat": {"enable_thinking": False},
    # Стандартный параметр OpenAI API: Gemini (2.5 Flash), Groq (Qwen3) и др.
    "reasoning_effort": {"reasoning_effort": "none"},
}


def _optional_float(name: str) -> Optional[float]:
    value = os.getenv(name, "").strip()
    return float(value) if value else None


def _optional_int(name: str, default: Optional[int]) -> Optional[int]:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    number = int(value)
    return number if number > 0 else None


@dataclass(frozen=True)
class ProviderRoute:
    """Запасной провайдер или модель (LLM_FALLBACKS): куда уходит запрос, если основной не ответил."""

    provider: str
    base_url: str
    model: str
    think_style: str
    api_key: str = field(repr=False)

    @property
    def key(self) -> str:
        return f"{self.provider}|{self.base_url}|{self.model}"


class LLMConfigError(RuntimeError):
    """Ключ или настройки LLM не заданы."""


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    base_url: str = DEFAULT_BASE_URL
    default_model: str = DEFAULT_MODEL
    role_models: dict[str, str] = field(default_factory=dict)
    think_style: str = "openrouter"
    json_mode: bool = True
    timeout: float = 90.0
    state_db: Path = DEFAULT_STATE_DB
    daily_cost_limit: Optional[float] = None
    daily_request_limit: Optional[int] = 300
    provider: str = "custom"
    fallbacks: tuple[ProviderRoute, ...] = ()

    def model_for(self, role: ModelRole) -> str:
        return (
            self.role_models.get(role)
            or ROLE_DEFAULT_MODELS.get(role)
            or self.default_model
        )

    def think_off_body(self) -> Optional[dict]:
        style = THINK_OFF_STYLES.get(self.think_style)
        return copy.deepcopy(style) if style else None


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def provider_key_env(provider: str) -> str:
    """Ключ запасного провайдера: GEMINI_API_KEY, GROQ_API_KEY, OPENROUTER_API_KEY, MISTRAL_API_KEY."""
    return f"{provider.upper()}_API_KEY"


def parse_fallbacks(raw: str, *, primary_provider: str, primary_key: str) -> tuple[ProviderRoute, ...]:
    """LLM_FALLBACKS=gemini:gemini-flash-latest,groq,openrouter — по порядку, после основного.

    Элемент — провайдер из PROVIDER_PRESETS и, через двоеточие, модель (иначе модель пресета).
    Ключ — <ПРОВАЙДЕР>_API_KEY, для того же провайдера, что основной, — LLM_API_KEY.
    Провайдер без ключа пропускается: запасной вариант не должен ломать запуск.
    """
    routes: list[ProviderRoute] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider, _, model = item.partition(":")
        provider = provider.strip().lower()
        preset = PROVIDER_PRESETS.get(provider)
        if preset is None:
            logger.warning("LLM_FALLBACKS: неизвестный провайдер %r пропущен", provider)
            continue
        key = _env(provider_key_env(provider)) or (primary_key if provider == primary_provider else "")
        if not key:
            if preset.key_required:
                logger.warning("LLM_FALLBACKS: для %s нет %s — пропущен", provider, provider_key_env(provider))
                continue
            key = provider
        base_url = (_env("OLLAMA_BASE_URL") if provider == "ollama" else "") or preset.base_url
        routes.append(ProviderRoute(provider, base_url, model.strip() or preset.model, preset.think_style, key))
    return tuple(routes)


def get_settings() -> LLMSettings:
    provider = (_env("LLM_PROVIDER") or "openrouter").lower()
    preset = PROVIDER_PRESETS.get(provider)
    if preset is None:
        raise LLMConfigError(
            "LLM_PROVIDER должен быть одним из: " + ", ".join(PROVIDER_PRESETS)
        )

    api_key = _env("LLM_API_KEY")
    if api_key == "PASTE_TEAM_KEY_HERE":
        api_key = ""
    if not api_key:
        if preset.key_required:
            raise LLMConfigError(
                "LLM_API_KEY не настроен: получите бесплатный ключ провайдера "
                f"({provider}) и укажите его в .env или выберите LLM_PROVIDER=ollama "
                "(см. docs/free-llm-providers.md)"
            )
        # OpenAI SDK требует непустой ключ; локальный сервер его не проверяет.
        api_key = provider

    role_models = {
        role: _env(f"LLM_MODEL_{role.upper()}")
        for role in ("extract", "analyze", "verify", "vision")
    }

    think_style = _env("LLM_THINK_STYLE") or preset.think_style
    if think_style != "none" and think_style not in THINK_OFF_STYLES:
        raise LLMConfigError(
            "LLM_THINK_STYLE должен быть none или одним из: "
            + ", ".join(THINK_OFF_STYLES)
        )

    default_model = _env("LLM_MODEL") or preset.model
    # Qwen3-VL по умолчанию есть только у шлюза организаторов; у остальных — основная модель.
    if provider != "hackathon" and not role_models["vision"]:
        role_models["vision"] = default_model

    return LLMSettings(
        api_key=api_key,
        base_url=_env("LLM_BASE_URL") or preset.base_url,
        default_model=default_model,
        role_models={role: model for role, model in role_models.items() if model},
        think_style=think_style,
        json_mode=os.getenv("LLM_JSON_MODE", "1").strip() != "0",
        timeout=float(_env("LLM_TIMEOUT") or "90"),
        state_db=Path(_env("LLM_STATE_DB") or DEFAULT_STATE_DB),
        daily_cost_limit=_optional_float("LLM_DAILY_COST_LIMIT"),
        daily_request_limit=_optional_int("LLM_DAILY_REQUEST_LIMIT", 300),
        provider=provider,
        fallbacks=parse_fallbacks(_env("LLM_FALLBACKS"), primary_provider=provider, primary_key=api_key),
    )
