import hashlib
import html
import re
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from app.modules.news.sources.base import RawNewsItem
from app.schemas.event import NewsEvent


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                "utm_content", "gclid", "fbclid"}
    query_items = [
        part for part in parts.query.split("&")
        if part and part.split("=", 1)[0].lower() not in tracking
    ]
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path.rstrip("/") or "/",
        "&".join(query_items),
        "",
    ))


def clean_text(value: Optional[str]) -> Optional[str]:
    """Strip HTML tags and entities that RSS feeds often put into descriptions."""
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = " ".join(html.unescape(text).split())
    return text or None


def normalize_news_item(item: RawNewsItem) -> Optional[NewsEvent]:
    title = " ".join(html.unescape(item.title).split())
    url = normalize_url(item.url)

    if not title or not url:
        return None

    event_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:24]

    try:
        return NewsEvent(
            event_id=event_id,
            title=title,
            published_at=item.published_at,
            source=item.source,
            url=url,
            summary=clean_text(item.summary),
            impact_channels=[],
            evidence=[url],
        )
    except ValueError:
        return None