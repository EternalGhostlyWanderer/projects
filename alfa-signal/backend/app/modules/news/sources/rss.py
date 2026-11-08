import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.news.sources.base import RawNewsItem

logger = logging.getLogger(__name__)


def _text(element: ET.Element, *paths: str) -> Optional[str]:
    for path in paths:
        node = element.find(path)
        if node is not None and node.text:
            value = node.text.strip()
            if value:
                return value
    return None


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            result = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None

    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)

    return result


def _atom_link(entry: ET.Element) -> Optional[str]:
    for link in entry.findall("{http://www.w3.org/2005/Atom}link"):
        rel = link.attrib.get("rel", "alternate")
        href = link.attrib.get("href")

        if href and rel == "alternate":
            return href

    return None


class RSSNewsSource:
    def __init__(
        self,
        name: str,
        url: str,
        timeout: int = 15,
        max_items: int = 100,
    ) -> None:
        if not url.startswith(("https://", "http://")):
            raise ValueError("RSS URL должна начинаться с http:// или https://")

        self.name = name
        self.url = url
        self.timeout = timeout
        self.max_items = max(1, min(max_items, 500))
        # Последняя ошибка: «network: …» — источник недоступен, «format: …» — ответ есть, но битый.
        # Её читает монитор источников (source_health.py).
        self.last_error: Optional[str] = None

    def fetch(self) -> List[RawNewsItem]:
        self.last_error = None
        request = Request(
            self.url,
            headers={"User-Agent": "Alfa-Signal/0.1"},
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                xml_data = response.read(5_000_000)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("Не удалось загрузить RSS %s: %s", self.name, exc)
            self.last_error = f"network: {exc}"
            return []

        try:
            root = ET.fromstring(xml_data)
        except ET.ParseError as exc:
            logger.warning("Некорректный XML в источнике %s: %s", self.name, exc)
            self.last_error = f"format: {exc}"
            return []

        # RSS 2.0
        entries = root.findall("./channel/item")

        # Atom
        if not entries:
            entries = root.findall(
                ".//{http://www.w3.org/2005/Atom}entry"
            )

        items: List[RawNewsItem] = []

        for entry in entries[: self.max_items]:
            is_atom = entry.tag.endswith("entry")

            if is_atom:
                title = _text(
                    entry,
                    "{http://www.w3.org/2005/Atom}title",
                )
                url = _atom_link(entry)
                summary = _text(
                    entry,
                    "{http://www.w3.org/2005/Atom}summary",
                    "{http://www.w3.org/2005/Atom}content",
                )
                published = _text(
                    entry,
                    "{http://www.w3.org/2005/Atom}published",
                    "{http://www.w3.org/2005/Atom}updated",
                )
            else:
                title = _text(entry, "title")
                url = _text(entry, "link")
                summary = _text(entry, "description")
                published = _text(
                    entry,
                    "pubDate",
                    "{http://purl.org/dc/elements/1.1/}date",
                )

            if not title or not url:
                continue

            items.append(
                RawNewsItem(
                    title=title,
                    url=url,
                    source=self.name,
                    published_at=_parse_date(published),
                    summary=summary,
                )
            )

        return items