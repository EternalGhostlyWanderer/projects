from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

ImpactChannel = Literal[
    "interest_rate",
    "deposit_yield",
    "leasing_cost",
    "international_trade",
    "incoming_concentration",
    "outgoing_concentration",
    "revenue",
    "industry",
    "regulation",
    "currency",
    "inflation",
    "supply_chain",
]


class EventEntities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    organizations: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
    regions: List[str] = Field(default_factory=list)
    industries: List[str] = Field(default_factory=list)
    okved_codes: List[str] = Field(default_factory=list)


SOURCE_SUMMARY_CHARS = 600


class EventSource(BaseModel):
    """Одна публикация о событии: событие может собрать несколько изданий."""

    model_config = ConfigDict(extra="ignore")

    url: str
    source: str
    title: str
    # Начало текста этой публикации: у каждого издания свой текст, чтобы цитата не уходила
    # к чужой ссылке, а цифры можно было сверить между изданиями (corroboration.py).
    summary: Optional[str] = None
    published_at: Optional[datetime] = None
    method: Literal["original", "url", "text", "similarity", "llm"] = "original"
    similarity: Optional[float] = None

    @classmethod
    def from_event(cls, event: "NewsEvent", *, method: str, similarity: Optional[float] = None) -> "EventSource":
        return cls(
            url=str(event.url),
            source=event.source,
            title=event.title,
            summary=(event.summary or event.text or "")[:SOURCE_SUMMARY_CHARS] or None,
            published_at=event.published_at,
            method=method,  # type: ignore[arg-type]
            similarity=similarity,
        )


class NewsEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=500)
    published_at: Optional[datetime] = None

    source: str = Field(min_length=1)
    url: HttpUrl
    summary: Optional[str] = None
    text: Optional[str] = None

    event_type: Optional[str] = None
    impact_channels: List[ImpactChannel] = Field(default_factory=list)
    entities: EventEntities = Field(default_factory=EventEntities)
    facts: List[str] = Field(default_factory=list)
    extraction_method: Optional[Literal["llm", "keywords"]] = None

    evidence: List[str] = Field(default_factory=list)
    # Склейка публикаций: все издания, написавшие о событии, и признак новых фактов.
    sources: List[EventSource] = Field(default_factory=list)
    has_update: bool = False
    # Новость, которую прислал пользователь (ссылка или текст): видна только в ленте его компании,
    # пока ту же публикацию не соберут из общих источников.
    submitted_by: Optional[str] = None
    # Полнота текста присланной новости: full — статья, partial — фрагмент или платный доступ,
    # title_only — один заголовок. У собранных из лент — None.
    content: Optional[Literal["full", "partial", "title_only"]] = None
    # Иностранные издания (NEWS_RSS_URLS_FOREIGN): язык оригинала; title и summary — перевод на русский,
    # оригинал — в original_*. language="en" без original_title — перевод ещё не сделан.
    language: Optional[Literal["ru", "en"]] = None
    original_title: Optional[str] = None
    original_summary: Optional[str] = None

    def visible_to(self, company_id: str) -> bool:
        return self.submitted_by is None or self.submitted_by == company_id
