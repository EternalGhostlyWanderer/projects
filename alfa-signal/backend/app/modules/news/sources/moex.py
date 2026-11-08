"""Moscow Exchange news via the open ISS API (JSON, no key).

ISS отдаёт новости биржи (`/iss/sitenews.json`). Девять из десяти — служебные: ценовые коридоры,
риск-параметры, выпуски облигаций, технические работы. Они отсеиваются здесь, до классификации:
иначе «цена исполнения фьючерса на индекс ключевой ставки» выглядела бы как решение по ставке.
Остальное проходит общий фильтр «не про бизнес» при сборе (docs/news-collection.md).
"""
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.news.sources.base import RawNewsItem

logger = logging.getLogger(__name__)

SOURCE_NAME = "Московская биржа"
SITENEWS_URL = "https://iss.moex.com/iss/sitenews.json"
NEWS_PAGE = "https://www.moex.com/n{id}"
MOSCOW = timezone(timedelta(hours=3))

SERVICE_NEWS = re.compile(
    r"ценов\w*\s+коридор|риск-параметр|ставк\w*\s+риска|рыночн\w*\s+риск|проспект|"
    r"биржев\w*\s+облигац|облигаци|ценн\w*\s+бумаг|начал\w*\s+торгов|приостановк\w*\s+торгов|"
    r"технически\w*\s+работ|релиз|депозитн\w*\s+аукцион|цен\w*\s+исполнения|фьючерс|опцион|"
    r"дестабилизаци|колокаци|списк\w*\s+ценных|эксперт\s+ра\b",
    re.IGNORECASE,
)


def is_service_news(title: str) -> bool:
    """Служебное сообщение биржи: участникам торгов важно, для бизнеса клиента — нет."""
    return bool(SERVICE_NEWS.search(title))


def _parse_date(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=MOSCOW)
    except ValueError:
        return None


def parse_sitenews(payload: Any) -> list[RawNewsItem]:
    """Блок sitenews: {"columns": [...], "data": [[...], ...]}."""
    block = payload.get("sitenews") if isinstance(payload, dict) else None
    if not isinstance(block, dict) or not isinstance(block.get("data"), list):
        return []
    columns = block.get("columns") or []
    items = []
    for row in block["data"]:
        if not isinstance(row, list):
            continue
        record = dict(zip(columns, row))
        title = record.get("title")
        if not isinstance(title, str) or not title.strip() or record.get("id") is None:
            continue
        if is_service_news(title):
            continue
        items.append(
            RawNewsItem(
                title=title.strip(),
                url=NEWS_PAGE.format(id=record["id"]),
                source=SOURCE_NAME,
                published_at=_parse_date(record.get("published_at")),
            )
        )
    return items


class MOEXNewsSource:
    name = SOURCE_NAME

    def __init__(self, max_items: int = 50, timeout: int = 15) -> None:
        self.max_items = max(1, min(max_items, 100))
        self.timeout = timeout
        self.last_error: Optional[str] = None

    def fetch(self) -> list[RawNewsItem]:
        self.last_error = None
        request = Request(f"{SITENEWS_URL}?iss.meta=off&start=0", headers={"User-Agent": "Alfa-Signal/0.1"})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read(2_000_000))
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            logger.warning("Новости Мосбиржи (ISS) недоступны: %s", exc)
            self.last_error = f"network: {exc}"
            return []
        except json.JSONDecodeError as exc:
            logger.warning("Мосбиржа (ISS) вернула не JSON: %s", exc)
            self.last_error = f"format: {exc}"
            return []
        if not isinstance(payload, dict) or "sitenews" not in payload:
            self.last_error = "format: в ответе ISS нет блока sitenews"
            return []
        return parse_sitenews(payload)[: self.max_items]
