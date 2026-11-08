import logging

from app.modules.news.deduplication import deduplicate_news
from app.modules.news.normalization import normalize_news_item
from app.modules.news.sources.base import NewsSource
from app.schemas.event import NewsEvent

logger = logging.getLogger(__name__)


def collect_news(sources: list[NewsSource]) -> list[NewsEvent]:
    normalized: list[NewsEvent] = []

    for source in sources:
        try:
            raw_items = source.fetch()
        except Exception:
            logger.exception("Ошибка источника новостей: %s", source.name)
            continue

        for raw_item in raw_items:
            event = normalize_news_item(raw_item)
            if event is not None:
                normalized.append(event)

    return deduplicate_news(normalized)
