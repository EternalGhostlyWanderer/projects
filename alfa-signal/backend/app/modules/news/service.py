"""News service: ingest events from text, URL or RSS, classify them and store."""
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from app.db.store import AppStore
from app.modules.news.clustering import WINDOW, find_duplicate, merge_into
from app.modules.news.extraction import extract_event
from app.modules.news.foreign import configured_foreign_rss_urls, mark_language, translate_pending
from app.modules.news import source_health
from app.modules.news.quality import is_clickbait
from app.modules.news.deduplication import deduplicate_news
from app.modules.news.normalization import normalize_news_item
from app.modules.news.normalization import clean_text, normalize_url
from app.modules.news.sources.article import FULL_TEXT_CHARS, fetch_article
from app.modules.news.sources.base import NewsSource
from app.modules.news.sources.cbr import CBRSource
from app.modules.news.sources.moex import MOEXNewsSource
from app.modules.news.sources.rss import RSSNewsSource
from app.schemas.event import EventSource, NewsEvent

logger = logging.getLogger(__name__)

MANUAL_URL_BASE = "https://alfa-signal.local/manual/"


# Окно поиска дублей в хранилище чуть шире окна склейки: даты публикаций бывают неточными.
CANDIDATE_LOOKBACK = WINDOW + timedelta(days=4)


def _event_id(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def _candidates(store: AppStore, event: NewsEvent) -> list[NewsEvent]:
    moment = event.published_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return store.recent_events(moment - CANDIDATE_LOOKBACK)


def _merge_duplicate(store: AppStore, event: NewsEvent, *, use_llm: bool) -> Optional[NewsEvent]:
    """Если публикация — дубль уже известного события, добавить её в источники и вернуть событие."""
    decision = find_duplicate(event, _candidates(store, event), use_llm=use_llm)
    if decision.event is None:
        return None
    merged = merge_into(decision.event, event, decision)
    store.save_event(merged)
    store.add_event_alias(event.event_id, merged.event_id, decision.method or "similarity")
    return merged


def register_event(store: AppStore, event: NewsEvent, *, use_llm: bool) -> tuple[NewsEvent, bool]:
    """Сохранить классифицированное событие или приклеить его к существующему: (событие, склеено ли)."""
    canonical_id = store.resolve_event_id(event.event_id)
    if canonical_id != event.event_id:
        return store.get_event(canonical_id) or event, True
    if store.get_event(event.event_id) is None:
        merged = _merge_duplicate(store, event, use_llm=use_llm)
        if merged is not None:
            if merged.submitted_by and event.submitted_by is None:
                # Присланную пользователем новость собрали и из общих источников — она больше не личная.
                merged = merged.model_copy(update={"submitted_by": None})
                store.save_event(merged)
            return merged, True
    if not event.sources:
        event = event.model_copy(update={"sources": [EventSource.from_event(event, method="original")]})
    store.save_event(event)
    return event, False


def ingest_text(
    store: AppStore,
    *,
    title: str,
    text: str = "",
    url: Optional[str] = None,
    source: str = "manual",
    published_at: Optional[datetime] = None,
    use_llm: bool = True,
    submitted_by: Optional[str] = None,
    paywalled: bool = False,
) -> NewsEvent:
    """Store a news item pasted by the user (or loaded from a file) after classification.

    Присланная пользователем новость (submitted_by) не проходит фильтры сбора — «не про бизнес», кликбейт,
    давность: пользователь сам решил, что она важна. Полнота текста сохраняется в content, и проверка
    разбора честно помечает разбор по заголовку или фрагменту.
    """
    title = " ".join(title.split())
    if not title:
        raise ValueError("Нужен заголовок новости")
    text = clean_text(text) or ""

    if url:
        url = normalize_url(url)
        event_id = _event_id(url)
    else:
        event_id = _event_id(f"{title}\n{text}")
        url = f"{MANUAL_URL_BASE}{event_id}"

    event = NewsEvent(
        event_id=event_id,
        title=title[:500],
        published_at=published_at,
        source=source,
        url=url,
        summary=text[:600] or None,
        text=text or None,
        evidence=[url],
        submitted_by=submitted_by,
        content=content_completeness(text, paywalled=paywalled) if submitted_by else None,
    )
    canonical = store.get_event(event_id)
    if canonical is not None and canonical.event_id != event_id:
        return canonical  # эту публикацию уже приклеили к другому событию
    if canonical is not None:
        if len(text) <= len(canonical.text or "") or canonical.submitted_by != submitted_by:
            # Уже известна: без повторной классификации и запроса к LLM. Чужую новость не перезаписываем.
            return canonical
        # Прислали более полный текст той же публикации — переклассифицировать, сохранив склеенные издания.
        event = event.model_copy(update={"sources": canonical.sources, "published_at": canonical.published_at})
    event = extract_event(mark_language(event), use_llm=use_llm)
    event, _ = register_event(store, event, use_llm=use_llm)
    if use_llm and event.language == "en" and translate_pending(store, candidates=[event], include_stored=False):
        # Присланная англоязычная статья: заголовок и анонс — по-русски, как у собранных новостей.
        event = store.get_event(event.event_id) or event
    return event


def content_completeness(text: str, *, paywalled: bool = False) -> str:
    if not text.strip():
        return "title_only"
    return "partial" if paywalled or len(text) < FULL_TEXT_CHARS else "full"


def ingest_url(
    store: AppStore, url: str, *, use_llm: bool = True, submitted_by: Optional[str] = None
) -> NewsEvent:
    try:
        known = store.get_event(_event_id(normalize_url(url)))
    except ValueError:
        known = None
    if known is not None:
        return known  # ссылку уже присылали или собрали из лент — страницу заново не качаем
    article = fetch_article(url)
    return ingest_text(
        store,
        title=article.title,
        text=article.text,
        url=article.url,
        source=article.source,
        use_llm=use_llm,
        submitted_by=submitted_by,
        paywalled=article.paywalled,
    )


def max_news_age_days() -> int:
    """Публикации старше стольких дней при сборе RSS не сохраняются (0 — без ограничения)."""
    try:
        return int(os.getenv("NEWS_MAX_AGE_DAYS", "") or 7)
    except ValueError:
        return 7


def _too_old(event: NewsEvent, max_age_days: int) -> bool:
    if not max_age_days or event.published_at is None:
        return False  # без даты — сохраняем: дата сбора и есть лучшая оценка
    published = event.published_at if event.published_at.tzinfo else event.published_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - published > timedelta(days=max_age_days)


def keep_offtopic() -> bool:
    """NEWS_KEEP_OFFTOPIC=1 — сохранять и публикации без каналов влияния (политика, спорт, происшествия)."""
    return os.getenv("NEWS_KEEP_OFFTOPIC", "0") == "1"


def is_offtopic(event: NewsEvent) -> bool:
    """Не про бизнес: ни одного канала влияния на компанию (ставка, курс, спрос, торговля…)."""
    return not event.impact_channels


# Официальные источники с открытым API: адреса зашиты в коде, ключи не нужны.
OFFICIAL_SOURCES = {"cbr": "Банк России: ключевая ставка и курсы", "moex": "Московская биржа: новости ISS"}


def configured_official_sources() -> list[str]:
    """NEWS_OFFICIAL_SOURCES=cbr,moex (по умолчанию оба; пусто или none — выключить)."""
    raw = os.getenv("NEWS_OFFICIAL_SOURCES")
    names = ["cbr", "moex"] if raw is None else [item.strip() for item in raw.split(",") if item.strip()]
    return [name for name in names if name in OFFICIAL_SOURCES]


def official_sources(names: Iterable[str], limit_per_source: int = 50) -> list[NewsSource]:
    factories = {"cbr": CBRSource, "moex": lambda: MOEXNewsSource(max_items=limit_per_source)}
    return [factories[name]() for name in names if name in factories]


# Ленты по умолчанию (как в .env.example): Банк России, деловые издания, информагентства.
# Проверены на доступность 26.10.2026; banki.ru отдаёт пустую ленту, у Росстата нет доступной RSS.
DEFAULT_RSS_URLS = (
    "https://www.cbr.ru/rss/RssPress",
    "https://www.cbr.ru/rss/eventrss",
    "https://www.kommersant.ru/RSS/section-economics.xml",
    "https://www.vedomosti.ru/rss/rubric/economics",
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "https://www.interfax.ru/rss.asp",
    "https://tass.ru/rss/v2.xml",
    "https://www.kommersant.ru/RSS/section-business.xml",
)


def configured_rss_urls() -> list[str]:
    """Русские ленты (NEWS_RSS_URLS) и иностранные (NEWS_RSS_URLS_FOREIGN, foreign.py).

    Через запятую; не задано — ленты по умолчанию, «-» — без лент этой группы.
    """
    raw = os.getenv("NEWS_RSS_URLS")
    if raw is None or not raw.strip():
        russian = list(DEFAULT_RSS_URLS)
    else:
        russian = [url.strip() for url in raw.split(",") if url.strip() and url.strip() != "-"]
    return list(dict.fromkeys([*russian, *configured_foreign_rss_urls()]))


def collect_rss(
    store: AppStore,
    urls: Iterable[str],
    *,
    use_llm: bool = False,
    limit_per_source: int = 50,
    extra_sources: Iterable[NewsSource] = (),
) -> dict[str, Any]:
    """Fetch RSS feeds (and official API sources), merge duplicates, classify and store new events.

    Дубли отсекаются до классификации, чтобы не тратить запросы к LLM на перепечатки.
    """
    sources: list[NewsSource] = [
        RSSNewsSource(name=url.split("/")[2], url=url, max_items=limit_per_source)
        for url in urls
    ]
    sources += list(extra_sources)
    added: list[NewsEvent] = []
    merged: list[NewsEvent] = []
    skipped = old = offtopic = clickbait = 0
    max_age = max_news_age_days()
    keep_all = keep_offtopic()

    # Каждый источник опрашивается отдельно: так у монитора есть время ответа, ошибка и итог по нему.
    runs: dict[str, dict[str, Any]] = {}
    origin: dict[str, str] = {}
    normalized: list[NewsEvent] = []
    for source in sources:
        key = source_health.source_key(source)
        started = time.perf_counter()
        error: Optional[str] = None
        try:
            raw_items = source.fetch()
        except Exception as exc:  # noqa: BLE001 — сбой одного источника не останавливает сбор
            logger.warning("Ошибка источника новостей %s: %s", getattr(source, "name", key), exc)
            raw_items, error = [], f"network: {type(exc).__name__}: {exc}"
        error = error or getattr(source, "last_error", None)
        runs[key] = {
            "source": source,
            "items": len(raw_items),
            "error": error,
            "duration_ms": round((time.perf_counter() - started) * 1000),
            "added": 0, "merged": 0, "offtopic": 0, "old": 0, "known": 0, "clickbait": 0,
        }
        for raw in raw_items:
            event = normalize_news_item(raw)
            if event is not None:
                normalized.append(event)
                origin.setdefault(event.event_id, key)

    # Сначала свежие: если лента отдаёт сотни записей, новые не вытесняются старыми.
    items = sorted(
        deduplicate_news(normalized),
        key=lambda item: item.published_at.isoformat() if item.published_at else "9999",
        reverse=True,
    )
    for event in items:
        run = runs.get(origin.get(event.event_id, ""), {})
        if _too_old(event, max_age):
            old += 1
            run["old"] = run.get("old", 0) + 1
            continue
        if store.get_event(event.event_id) is not None or store.is_offtopic(event.event_id):
            skipped += 1  # та же ссылка уже собрана (в том числе как дубль другого события)
            run["known"] = run.get("known", 0) + 1
            continue
        if not keep_all and is_clickbait(event.title):
            # «Россиянам рассказали о средневековом импорте»: ключевые слова есть, деловой новости нет.
            store.mark_offtopic(event.event_id, event.title)
            clickbait += 1
            run["clickbait"] = run.get("clickbait", 0) + 1
            continue
        early = _merge_duplicate(store, event, use_llm=False)
        if early is not None:
            merged.append(early)
            run["merged"] = run.get("merged", 0) + 1
            continue
        # Язык — до классификации: английские публикации размечаются английскими ключевыми словами.
        extracted = extract_event(mark_language(event), use_llm=use_llm)
        if not keep_all and is_offtopic(extracted):
            # Общие ленты на две трети — политика и спорт: в ленту компании они всё равно не попадут
            # (балл 0), а склейку и предварительный анализ только замедляют.
            store.mark_offtopic(extracted.event_id, extracted.title)
            offtopic += 1
            run["offtopic"] = run.get("offtopic", 0) + 1
            continue
        event, was_merged = register_event(store, extracted, use_llm=use_llm)
        (merged if was_merged else added).append(event)
        run["merged" if was_merged else "added"] = run.get("merged" if was_merged else "added", 0) + 1

    # Иностранные публикации, прошедшие фильтр, — на русский пачками (и оставшиеся с прошлых сборов).
    translated = translate_pending(store, candidates=added)
    if translated:
        added = [store.get_event(event.event_id) or event for event in added]

    health = []
    now = datetime.now(timezone.utc).isoformat()
    for key, run in runs.items():
        source = run.pop("source")
        kind = getattr(source, "kind", "news")
        run.update(at=now, status=source_health.run_status(error=run["error"], items=run["items"], kind=kind))
        record = store.record_source_run(key, getattr(source, "name", key), kind, run)
        health.append({**record, "status": source_health.current_status(record)})
    return {
        "sources": health,
        "added": added,
        "merged": merged,
        "skipped_known_urls": skipped,
        "skipped_old": old,
        "skipped_offtopic": offtopic,
        "skipped_clickbait": clickbait,
        "translated": translated,
    }


def load_events_file(store: AppStore, path: Path, *, use_llm: bool = False) -> list[NewsEvent]:
    """Load events from a JSON list of {title, text, url?, source?, published_at?}."""
    items: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
    events: list[NewsEvent] = []
    for item in items:
        published = item.get("published_at")
        events.append(
            ingest_text(
                store,
                title=item["title"],
                text=item.get("text", ""),
                url=item.get("url"),
                source=item.get("source", "file"),
                published_at=datetime.fromisoformat(published) if published else None,
                use_llm=use_llm,
            )
        )
    return events
