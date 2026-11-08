"""BM25 search over Alfa-Bank research chunks (no embeddings, no external services)."""
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from app.research.forecasts import forecast_table
from app.research.index import INDEX_PATH, BankChunk, load_chunks, load_forecasts
from app.research.registry import DOCUMENTS_BY_ID

K1 = 1.5
B = 0.75
CHANNEL_BOOST = 1.25
STALE_AFTER_DAYS = 365
# Мягкое предпочтение свежей аналитики вообще: до 30 дней вес 1,0, к 180 дням — 0,85.
RECENT_DAYS = 30
OLD_DAYS = 180
OLD_WEIGHT = 0.85
TITLE_BOOST = 1.2
# Свежесть по теме: если по запросу нашёлся документ новее (его лучший фрагмент не слабее 60% лучшего
# результата), фрагменты более старых документов теряют вес — 1% за каждые два дня разницы, не ниже 0,6.
# Июльский прогноз ставки уступает сентябрьскому, а единственный документ о стали (2021) не штрафуется:
# более свежего по этой теме нет. Абсолютный штраф за возраст убран — он прятал единственный профильный
# документ; возраст по-прежнему виден в поле stale.
TOPICAL_SHARE = 0.6
NEWER_PENALTY_PER_DAY = 0.005
NEWER_MIN_WEIGHT = 0.6
# Запрос совпал с темами документа из реестра (registry.py: topics, название) — документ по теме.
TOPIC_BOOST = 1.35
MIN_TOPIC_PREFIX = 5
# Однокоренные слова с разными основами («потребительский» — «потребление»): общее начало от 6 букв,
# вес 0,7 от точного совпадения.
RELATED_PREFIX = 6
RELATED_WEIGHT = 0.7

TOKEN = re.compile(r"[a-zа-я0-9]+")
STOPWORDS = {
    "и", "в", "во", "на", "по", "с", "со", "к", "ко", "о", "об", "от", "до", "за", "из",
    "для", "при", "не", "но", "а", "что", "как", "это", "так", "же", "ли", "бы", "его",
    "ее", "их", "мы", "вы", "он", "она", "они", "то", "все", "уже", "еще", "также",
    "который", "которые", "года", "году", "год", "г",
}
# Окончания по убыванию длины; основа после отсечения — не короче 4 букв.
ENDINGS = tuple(
    sorted(
        (
            "иями", "ями", "ами", "ией", "иях", "ях", "ах", "ов", "ев", "ей", "ий", "ый",
            "ой", "ая", "яя", "ое", "ее", "ые", "ие", "ых", "их", "ым", "им", "ом", "ем",
            "ую", "юю", "ам", "ям", "ии", "ию", "ия", "ья", "ье", "ьи", "ью", "ого", "его",
            "ому", "ему", "а", "я", "о", "е", "и", "ы", "у", "ю", "ь", "й",
        ),
        key=len,
        reverse=True,
    )
)

CHANNEL_QUERY_TERMS = {
    "interest_rate": "ключевая ставка денежно-кредитная политика кредитование",
    "deposit_yield": "доходность депозиты ОФЗ облигации",
    "leasing_cost": "лизинг ставка финансирование",
    "inflation": "инфляция цены инфляционные ожидания",
    "currency": "курс рубль валюта",
    "international_trade": "экспорт импорт внешняя торговля",
    "revenue": "спрос потребление продажи розничная торговля",
    "supply_chain": "поставки логистика сырьё",
    "industry": "отрасль производство промышленность",
    "regulation": "регулирование бюджет Минфин",
}


def stem(token: str) -> str:
    for ending in ENDINGS:
        if token.endswith(ending) and len(token) - len(ending) >= 4:
            return token[: -len(ending)]
    return token


def tokenize(text: str) -> list[str]:
    tokens = TOKEN.findall(text.casefold().replace("ё", "е"))
    return [stem(token) for token in tokens if token not in STOPWORDS and (len(token) > 1 or token.isdigit())]


@dataclass
class _Index:
    chunks: list[BankChunk]
    term_freqs: list[Counter]
    title_terms: list[set[str]]
    lengths: list[int]
    doc_freq: Counter
    avg_length: float


def _build(chunks: list[BankChunk]) -> _Index:
    term_freqs = [Counter(tokenize(f"{chunk.section or ''} {chunk.text}")) for chunk in chunks]
    title_terms = [set(tokenize(chunk.doc_title)) for chunk in chunks]
    lengths = [sum(counter.values()) for counter in term_freqs]
    doc_freq: Counter = Counter()
    for counter in term_freqs:
        doc_freq.update(counter.keys())
    return _Index(
        chunks=chunks,
        term_freqs=term_freqs,
        title_terms=title_terms,
        lengths=lengths,
        doc_freq=doc_freq,
        avg_length=(sum(lengths) / len(lengths)) if lengths else 0.0,
    )


@lru_cache(maxsize=4)
def _load_index(path: str) -> _Index:
    return _build(load_chunks(Path(path)))


@lru_cache(maxsize=4)
def _load_forecast_table(path: str) -> dict[str, dict[str, Any]]:
    return forecast_table(load_forecasts(Path(path)))


def bank_forecasts(index_path: Path = INDEX_PATH) -> dict[str, dict[str, Any]]:
    """Актуальные прогнозы банка по показателям с историей пересмотров (forecasts.py)."""
    return _load_forecast_table(str(index_path))


def reload_index() -> None:
    _load_index.cache_clear()
    _load_forecast_table.cache_clear()


def _is_stale(doc_date: str, as_of: date) -> bool:
    try:
        return (as_of - date.fromisoformat(doc_date)).days > STALE_AFTER_DAYS
    except ValueError:
        return False


def _stem_match(left: str, right: str) -> bool:
    """«потребительск» и «потреблен», «стал» и «стал»: общая основа от 5 букв или полное совпадение."""
    if left == right:
        return True
    common = 0
    for a, b in zip(left, right):
        if a != b:
            break
        common += 1
    return common >= MIN_TOPIC_PREFIX


@lru_cache(maxsize=64)
def _topic_terms(doc_id: str) -> frozenset[str]:
    document = DOCUMENTS_BY_ID.get(doc_id)
    if document is None:
        return frozenset()
    return frozenset(tokenize(" ".join((document.title, *document.topics))))


def _on_topic(doc_id: str, query_terms: set[str]) -> bool:
    topics = _topic_terms(doc_id)
    return any(_stem_match(term, topic) for term in query_terms for topic in topics)


def _days(older: str, newer: str) -> int:
    try:
        return (date.fromisoformat(newer) - date.fromisoformat(older)).days
    except ValueError:
        return 0


def _recency(doc_date: str, as_of: date) -> float:
    try:
        age = (as_of - date.fromisoformat(doc_date)).days
    except ValueError:
        return 1.0
    if age <= RECENT_DAYS:
        return 1.0
    return max(OLD_WEIGHT, 1.0 - (1.0 - OLD_WEIGHT) * (age - RECENT_DAYS) / (OLD_DAYS - RECENT_DAYS))


def search_chunks(
    chunks_index: _Index,
    query: str,
    channels: Iterable[str] = (),
    *,
    top_k: int = 5,
    max_per_doc: int = 3,
    min_matched_terms: Optional[int] = None,
    as_of: Optional[date] = None,
) -> list[dict[str, Any]]:
    channels = [channel for channel in channels if channel in CHANNEL_QUERY_TERMS]
    query_terms = set(tokenize(query))
    expansion_terms = set(
        tokenize(" ".join(CHANNEL_QUERY_TERMS[channel] for channel in channels))
    ) - query_terms
    if not query_terms and not expansion_terms:
        return []

    required = min_matched_terms if min_matched_terms is not None else min(2, len(query_terms) or 1)
    related = _related_terms(chunks_index, query_terms)
    as_of = as_of or date.today()
    total = len(chunks_index.chunks)
    scored: list[tuple[float, int, int]] = []

    for position, (counter, length) in enumerate(zip(chunks_index.term_freqs, chunks_index.lengths)):
        matched_query = [term for term in query_terms if term in counter]
        matched_related = [
            variant
            for term in query_terms
            if term not in counter
            for variant in related.get(term, ())
            if variant in counter
        ][:3]
        # Однокоренное слово засчитывается как совпадение терма запроса (для порога required).
        matched_count = len(matched_query) + len({term for term in query_terms if term not in counter and any(v in counter for v in related.get(term, ()))})
        matched_expansion = [term for term in expansion_terms if term in counter]
        if matched_count + (1 if not query_terms and matched_expansion else 0) < required:
            continue

        score = 0.0
        for term in (*matched_query, *matched_related, *matched_expansion):
            idf = math.log(1 + (total - chunks_index.doc_freq[term] + 0.5) / (chunks_index.doc_freq[term] + 0.5))
            tf = counter[term]
            norm = K1 * (1 - B + B * length / (chunks_index.avg_length or 1))
            weight = 1.0 if term in query_terms else RELATED_WEIGHT if term in matched_related else 0.5
            score += weight * idf * tf * (K1 + 1) / (tf + norm)

        chunk = chunks_index.chunks[position]
        document = DOCUMENTS_BY_ID.get(chunk.doc_id)
        if document and channels and set(document.channels) & set(channels):
            score *= CHANNEL_BOOST
        if query_terms and _on_topic(chunk.doc_id, query_terms):
            score *= TOPIC_BOOST
        score *= _recency(chunk.doc_date, as_of)
        title_matches = query_terms & chunks_index.title_terms[position]
        if title_matches:
            score *= TITLE_BOOST

        if score > 0:
            scored.append((score, len(matched_query), position))

    scored = _prefer_newer_on_topic(chunks_index, scored, query_terms)
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    results: list[dict[str, Any]] = []
    per_doc: Counter = Counter()

    for score, matched, position in scored:
        chunk = chunks_index.chunks[position]
        if per_doc[chunk.doc_id] >= max_per_doc:
            continue
        per_doc[chunk.doc_id] += 1
        text = f"{chunk.section}. {chunk.text}" if chunk.section and chunk.section not in chunk.text else chunk.text
        results.append(
            {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunk.doc_id,
                "doc_title": chunk.doc_title,
                "doc_date": chunk.doc_date,
                "page": chunk.page,
                "section": chunk.section,
                "kind": chunk.kind,
                "text": text,
                "score": round(score, 3),
                "matched_terms": matched,
                "stale": _is_stale(chunk.doc_date, as_of),
            }
        )
        if len(results) >= top_k:
            break

    return results


def _related_terms(chunks_index: _Index, query_terms: set[str]) -> dict[str, tuple[str, ...]]:
    """Термы словаря индекса с тем же корнем, что у терма запроса (во фрагменте без самого терма)."""
    result = {}
    for term in query_terms:
        if len(term) < RELATED_PREFIX:
            continue
        prefix = term[:RELATED_PREFIX]
        variants = tuple(sorted(word for word in chunks_index.doc_freq if word.startswith(prefix) and word != term))[:5]
        if variants:
            result[term] = variants
    return result


def _prefer_newer_on_topic(
    chunks_index: _Index, scored: list[tuple[float, int, int]], query_terms: set[str] = frozenset()
) -> list[tuple[float, int, int]]:
    """Если по запросу есть документ новее на ту же тему, старые документы уступают ему.

    Тема — по реестру (topics, название); если запрос не совпал ни с одной темой — документы,
    чей лучший фрагмент не слабее 60% лучшего результата.
    """
    if not scored:
        return scored
    best_by_doc: dict[str, float] = {}
    dates: dict[str, str] = {}
    for score, _, position in scored:
        chunk = chunks_index.chunks[position]
        best_by_doc[chunk.doc_id] = max(best_by_doc.get(chunk.doc_id, 0.0), score)
        dates[chunk.doc_id] = chunk.doc_date
    top = max(best_by_doc.values())
    topical = [doc_id for doc_id in best_by_doc if query_terms and _on_topic(doc_id, query_terms)]
    topical = topical or [doc_id for doc_id, best in best_by_doc.items() if best >= TOPICAL_SHARE * top]
    newest = max(dates[doc_id] for doc_id in topical)
    result = []
    for score, matched, position in scored:
        lag = _days(chunks_index.chunks[position].doc_date, newest)
        if lag > 0:
            score *= max(NEWER_MIN_WEIGHT, 1.0 - NEWER_PENALTY_PER_DAY * lag)
        result.append((score, matched, position))
    return result


def search_bank_research(
    query: str,
    channels: Iterable[str] = (),
    *,
    top_k: int = 5,
    as_of: Optional[date] = None,
    index_path: Path = INDEX_PATH,
) -> list[dict[str, Any]]:
    """Return the best chunks of bank research; an empty list means no relevant material."""
    return search_chunks(
        _load_index(str(index_path)),
        query,
        channels,
        top_k=top_k,
        as_of=as_of,
    )


def build_search_index(chunks: list[BankChunk]) -> _Index:
    return _build(chunks)
