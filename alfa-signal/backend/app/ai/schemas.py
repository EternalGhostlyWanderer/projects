"""Insight contract v2 shared by the LLM, backend and frontend."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "2.0"

EvidenceType = Literal["FACT", "BANK_ANALYSIS", "AI_INFERENCE", "HYPOTHESIS"]
SourceKind = Literal["news", "company_data", "bank_research", "model"]
Level = Literal["low", "medium", "high"]
InsightKind = Literal["risk", "opportunity", "mixed"]
Direction = Literal["positive", "negative", "mixed", "uncertain"]
# verified — проверено автоматически: числа найдены в источниках, ссылки существуют, прогнозы банка
# актуальны, спорные цифры с оговоркой. Это не экспертная проверка правильности вывода.
# outdated — позиция банка из документа, по теме которого есть более свежий;
# conflicting — источники расходятся, а вывод подаёт спорную цифру как факт.
QualityStatus = Literal["unverified", "verified", "partial", "outdated", "conflicting", "failed"]

SOURCED_BASES = {"FACT", "BANK_ANALYSIS"}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Evidence(ContractModel):
    """Единица доказательства. Собирается кодом, а не моделью."""

    id: str = Field(min_length=1)
    type: EvidenceType
    text: str = Field(min_length=1)
    source_kind: SourceKind
    source_id: str | None = Field(
        default=None,
        description="event_id, поле CSV или chunk_id документа банка",
    )
    source_title: str | None = None
    source_url: str | None = None
    source_date: str | None = None
    source_page: int | None = Field(default=None, ge=1)


class Claim(ContractModel):
    text: str = Field(min_length=1)
    basis: EvidenceType = Field(
        description=(
            "FACT — подтверждено новостью или данными компании; "
            "BANK_ANALYSIS — тезис из материала Альфа-Банка; "
            "AI_INFERENCE — вывод модели; HYPOTHESIS — требует проверки"
        ),
    )
    evidence_ids: list[str] = Field(
        default_factory=list,
        description="id из переданного списка evidence; обязательны для FACT и BANK_ANALYSIS",
    )
    confidence: Level

    @model_validator(mode="after")
    def _require_sources(self) -> "Claim":
        if self.basis in SOURCED_BASES and not self.evidence_ids:
            raise ValueError(
                f"Утверждение с basis={self.basis} должно ссылаться на evidence_ids"
            )
        return self


class Risk(Claim):
    title: str = Field(min_length=1)
    severity: Level


class Opportunity(Claim):
    title: str = Field(min_length=1)
    potential: Level


class Relevance(ContractModel):
    score: int = Field(ge=0, le=100)
    level: Level
    reasons: list[Claim] = Field(
        min_length=1,
        description="Конкретные признаки компании, из-за которых событие важно",
    )


class Scenario(ContractModel):
    name: Literal["base", "negative", "positive"]
    condition: str = Field(min_length=1, description="При каком условии реализуется")
    outcome: Claim


class NextStep(ContractModel):
    action: str = Field(min_length=1)
    priority: Level


class BankView(ContractModel):
    status: Literal["found", "not_found"]
    claims: list[Claim] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_status(self) -> "BankView":
        if self.status == "found" and not self.claims:
            raise ValueError("bank_view.status=found требует хотя бы одно утверждение")
        if self.status == "not_found" and self.claims:
            raise ValueError("bank_view.status=not_found не допускает утверждений")
        if any(claim.basis != "BANK_ANALYSIS" for claim in self.claims):
            raise ValueError("В bank_view допускаются только утверждения BANK_ANALYSIS")
        return self


class InsightDraft(ContractModel):
    """Часть инсайта, которую формирует LLM."""

    schema_version: Literal["2.0"]
    kind: InsightKind
    relevance: Relevance
    event_summary: list[Claim] = Field(
        min_length=1,
        description="Что произошло: только факты из новости с basis=FACT",
    )
    mechanism: list[str] = Field(
        min_length=2,
        description="Причинная цепочка от события к эффекту, по шагу на элемент",
    )
    direction: Direction
    primary_effect: Claim
    risks: list[Risk] = Field(default_factory=list)
    opportunities: list[Opportunity] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    bank_view: BankView
    next_steps: list[NextStep] = Field(min_length=1)
    unknowns: list[str] = Field(
        default_factory=list,
        description="Каких данных не хватает для более точного вывода",
    )
    decision_question: str = Field(
        min_length=1,
        description="Главный вопрос, который стоит решить руководителю",
    )

    @model_validator(mode="after")
    def _check_event_summary(self) -> "InsightDraft":
        if any(claim.basis != "FACT" for claim in self.event_summary):
            raise ValueError("event_summary допускает только утверждения FACT")
        return self

    def claims(self) -> list[Claim]:
        result: list[Claim] = [
            *self.relevance.reasons,
            *self.event_summary,
            self.primary_effect,
            *self.risks,
            *self.opportunities,
            *(scenario.outcome for scenario in self.scenarios),
            *self.bank_view.claims,
        ]
        return result

    def referenced_evidence_ids(self) -> set[str]:
        return {
            evidence_id
            for claim in self.claims()
            for evidence_id in claim.evidence_ids
        }


class Insight(InsightDraft):
    """Полный инсайт, который backend отдаёт frontend."""

    insight_id: str = Field(min_length=1)
    company_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    evidence: list[Evidence]
    trace_id: str | None = None
    model: str
    created_at: str
    quality_status: QualityStatus
    quality_issues: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_evidence_links(self) -> "Insight":
        known = {item.id for item in self.evidence}
        missing = self.referenced_evidence_ids() - known
        if missing:
            raise ValueError(
                "Ссылки на несуществующие evidence: " + ", ".join(sorted(missing))
            )
        return self
