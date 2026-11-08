"""Facts about the company provided by the user (webinar answers 28 and 33).

Только понятные и оправданные поля, без лишнего трения: долг с плавающей ставкой нужен для
сценарных расчётов по ставке, валюты контрактов и страны — для оценки валютных и торговых новостей,
доля экспорта, отрасли покупателей и поставщиков, планы и интересующие темы — для ленты и выводов.
Поля можно заполнить вручную или из документа (договор, отчётность, описание компании:
documents.py) — тогда у поля сохраняется источник и цитата. В доказательствах такие факты
помечаются «со слов пользователя» или «из документа пользователя».
"""
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.schemas import Evidence


class FieldSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: Literal["manual", "document"] = "manual"
    document: Optional[str] = Field(default=None, max_length=200, description="Название документа")
    quote: Optional[str] = Field(default=None, max_length=400, description="Цитата из документа")
    updated_at: Optional[str] = None
    user_id: Optional[str] = Field(default=None, max_length=100)


class CompanyUserData(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    floating_debt_rub: Optional[float] = Field(
        default=None, ge=0, le=1e13, description="Долг с плавающей ставкой, руб."
    )
    fixed_debt_rub: Optional[float] = Field(default=None, ge=0, le=1e13, description="Долг с фиксированной ставкой, руб.")
    contract_currencies: list[str] = Field(
        default_factory=list, max_length=6, description="Валюты контрактов: CNY, USD, EUR, AED…"
    )
    trade_countries: list[str] = Field(
        default_factory=list, max_length=10, description="Страны поставщиков и покупателей"
    )
    key_inputs: Optional[str] = Field(default=None, max_length=200, description="Основные закупки: сырьё, топливо…")
    export_share_pct: Optional[float] = Field(default=None, ge=0, le=100, description="Доля экспорта в выручке, %")
    revenue_currencies: list[str] = Field(default_factory=list, max_length=6, description="Валюты выручки")
    customer_industries: list[str] = Field(
        default_factory=list, max_length=8, description="Отрасли основных покупателей"
    )
    supplier_industries: list[str] = Field(
        default_factory=list, max_length=8, description="Отрасли основных поставщиков"
    )
    investment_plans: Optional[str] = Field(default=None, max_length=300, description="Планы инвестиций")
    borrowing_plans: Optional[str] = Field(default=None, max_length=300, description="Планы заимствований")
    covenants: Optional[str] = Field(default=None, max_length=300, description="Ковенанты по кредитам")
    interests: list[str] = Field(
        default_factory=list, max_length=10, description="Темы, которые важны компании: «курс юаня», «пошлины на металл»"
    )
    note: Optional[str] = Field(default=None, max_length=500)
    # Откуда взято поле: вручную или из документа (с цитатой). Ключ — имя поля.
    field_sources: dict[str, "FieldSource"] = Field(default_factory=dict)

    @field_validator("contract_currencies", "trade_countries", "revenue_currencies", mode="before")
    @classmethod
    def _upper(cls, values: Any) -> Any:
        if isinstance(values, str):
            values = values.split(",")
        if isinstance(values, list):
            return list(dict.fromkeys(str(item).strip().upper() for item in values if str(item).strip()))[:10]
        return values

    @field_validator("customer_industries", "supplier_industries", "interests", mode="before")
    @classmethod
    def _items(cls, values: Any) -> Any:
        if isinstance(values, str):
            values = values.split(",")
        if isinstance(values, list):
            return list(dict.fromkeys(str(item).strip()[:80] for item in values if str(item).strip()))[:10]
        return values


CompanyUserData.model_rebuild()


def _fact(evidence_id: str, text: str, origin: Optional[dict[str, Any]] = None) -> Evidence:
    if origin and origin.get("source") == "document":
        document = origin.get("document") or "документ"
        return Evidence(
            id=evidence_id,
            type="FACT",
            text=f"Из документа пользователя «{document}»: {text}",
            source_kind="company_data",
            source_id="user_document",
            source_title=f"Документ пользователя: {document}",
        )
    return Evidence(
        id=evidence_id,
        type="FACT",
        text=f"Со слов пользователя: {text}",
        source_kind="company_data",
        source_id="user_input",
        source_title="Данные от пользователя",
    )


def user_data_evidence(data: dict[str, Any]) -> list[Evidence]:
    if not data:
        return []
    items: list[Evidence] = []
    sources = data.get("field_sources") or {}

    def origin(*keys: str) -> Optional[dict[str, Any]]:
        return next((sources[key] for key in keys if key in sources), None)

    debt = []
    if data.get("floating_debt_rub") is not None:
        debt.append(f"долг с плавающей ставкой — {data['floating_debt_rub']:.0f} руб.")
    if data.get("fixed_debt_rub") is not None:
        debt.append(f"долг с фиксированной ставкой — {data['fixed_debt_rub']:.0f} руб.")
    if debt:
        items.append(_fact("company.user.debt", "; ".join(debt), origin("floating_debt_rub", "fixed_debt_rub")))
    if data.get("contract_currencies"):
        items.append(
            _fact("company.user.currencies", "валюты контрактов — " + ", ".join(data["contract_currencies"]), origin("contract_currencies"))
        )
    if data.get("trade_countries"):
        items.append(
            _fact("company.user.countries", "страны поставщиков и покупателей — " + ", ".join(data["trade_countries"]), origin("trade_countries"))
        )
    if data.get("key_inputs"):
        items.append(_fact("company.user.inputs", f"основные закупки — {data['key_inputs']}", origin("key_inputs")))
    if data.get("export_share_pct") is not None:
        items.append(
            _fact("company.user.export", f"доля экспорта в выручке — {data['export_share_pct']:g}%", origin("export_share_pct"))
        )
    if data.get("revenue_currencies"):
        items.append(
            _fact("company.user.revenue_currencies", "валюты выручки — " + ", ".join(data["revenue_currencies"]), origin("revenue_currencies"))
        )
    for key, label, evidence_id in (
        ("customer_industries", "отрасли основных покупателей", "company.user.customers"),
        ("supplier_industries", "отрасли основных поставщиков", "company.user.suppliers"),
        ("interests", "темы, важные компании", "company.user.interests"),
    ):
        if data.get(key):
            items.append(_fact(evidence_id, f"{label} — " + ", ".join(data[key]), origin(key)))
    for key, label, evidence_id in (
        ("investment_plans", "планы инвестиций", "company.user.investments"),
        ("borrowing_plans", "планы заимствований", "company.user.borrowing"),
        ("covenants", "ковенанты по кредитам", "company.user.covenants"),
    ):
        if data.get(key):
            items.append(_fact(evidence_id, f"{label} — {data[key]}", origin(key)))
    return items
