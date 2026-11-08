from app.modules.news.normalization import normalize_url
from app.schemas.event import NewsEvent


def deduplicate_news(items: list[NewsEvent]) -> list[NewsEvent]:
    unique: dict[str, NewsEvent] = {}

    for item in items:
        normalized_url = normalize_url(str(item.url))
        normalized_title = " ".join(item.title.casefold().split())

        key = normalized_url or normalized_title
        if not key:
            continue

        existing = unique.get(key)
        if existing is None:
            unique[key] = item
        elif not existing.summary and item.summary:
            unique[key] = item

    return list(unique.values())
