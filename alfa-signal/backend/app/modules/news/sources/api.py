import json
import logging
import threading
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.modules.news.sources.base import RawNewsItem

logger = logging.getLogger(__name__)

GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


class GDELTNewsSource:

    _cache: dict[tuple, tuple[float, list[RawNewsItem]]] = {}
    _blocked_until: dict[str, float] = {}
    _lock = threading.Lock()
    _request_lock = threading.Lock()
    _last_request_at = 0.0

    REQUEST_INTERVAL = 6.0

    def __init__(
        self,
        query: str,
        max_records: int = 50,
        timespan: str = "7d",
        timeout: int = 20,
        cache_ttl: int = 300,
    ) -> None:
        if not query.strip():
            raise ValueError("Поисковый запрос не должен быть пустым")

        self.query = query.strip()
        self.max_records = max(1, min(max_records, 250))
        self.timespan = timespan
        self.timeout = timeout
        self.cache_ttl = max(1, cache_ttl)

    def fetch(self) -> list[RawNewsItem]:
        cls = type(self)
        key = (self.query, self.max_records, self.timespan)

        with cls._lock:
            cached = cls._cache.get(key)
            if cached and cached[0] > time.monotonic():
                logger.info("GDELT: возвращаем новости из кэша")
                return list(cached[1])

            if cls._blocked_until.get(GDELT_DOC_API, 0) > time.monotonic():
                logger.warning("GDELT временно заблокирован после HTTP 429")
                return []

        params = urlencode({
            "query": self.query,
            "mode": "ArtList",
            "format": "json",
            "maxrecords": self.max_records,
            "timespan": self.timespan,
            "sort": "DateDesc",
        })

        request = Request(
            f"{GDELT_DOC_API}?{params}",
            headers={"User-Agent": "Alfa-Signal/0.1"},
        )


        with cls._request_lock:
            with cls._lock:
                cached = cls._cache.get(key)
                if cached and cached[0] > time.monotonic():
                    return list(cached[1])

                if cls._blocked_until.get(GDELT_DOC_API, 0) > time.monotonic():
                    logger.warning("GDELT всё ещё на паузе после HTTP 429")
                    return []

            elapsed = time.monotonic() - cls._last_request_at
            wait = cls.REQUEST_INTERVAL - elapsed

            if wait > 0:
                time.sleep(wait)

            with cls._lock:
                if cls._blocked_until.get(GDELT_DOC_API, 0) > time.monotonic():
                    return []

            cls._last_request_at = time.monotonic()

            try:
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.loads(response.read(5_000_000))

            except HTTPError as exc:
                if exc.code == 429:
                    delay = self._retry_delay(exc.headers.get("Retry-After"))
                    with cls._lock:
                        cls._blocked_until[GDELT_DOC_API] = (
                            time.monotonic() + delay
                        )
                    logger.warning(
                        "GDELT вернул 429; пауза %.0f секунд", delay
                    )
                else:
                    logger.warning("HTTP-ошибка GDELT: %s", exc)
                return []

            except (
                URLError,
                TimeoutError,
                OSError,
                json.JSONDecodeError,
            ) as exc:
                logger.warning("Ошибка запроса к GDELT: %s", exc)
                return []

        if not isinstance(payload, dict):
            logger.warning("GDELT вернул неожиданный формат JSON")
            return []

        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            logger.warning("В ответе GDELT поле articles не является списком")
            return []

        items: list[RawNewsItem] = []

        for article in articles:
            if not isinstance(article, dict):
                continue

            title = article.get("title")
            url = article.get("url")

            if not isinstance(title, str) or not title.strip():
                continue

            if not isinstance(url, str) or not url.startswith(
                ("https://", "http://")
            ):
                continue

            items.append(
                RawNewsItem(
                    title=title.strip(),
                    url=url,
                    source=article.get("domain") or self.name,
                    published_at=self._parse_date(article.get("seendate")),
                    summary=None,
                )
            )

        with cls._lock:
            cls._cache[key] = (
                time.monotonic() + self.cache_ttl,
                items,
            )
            cls._blocked_until.pop(GDELT_DOC_API, None)

        logger.info("GDELT: получено статей — %d", len(items))
        return list(items)

    @staticmethod
    def _retry_delay(value: Optional[str]) -> float:
        if value:
            try:
                return max(60.0, min(float(value), 3600.0))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(value)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=timezone.utc)

                    seconds = (
                        retry_at - datetime.now(timezone.utc)
                    ).total_seconds()

                    return max(60.0, min(seconds, 3600.0))
                except (ValueError, TypeError, OverflowError):
                    pass

        return 60.0

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None

        try:
            return datetime.strptime(
                value, "%Y%m%dT%H%M%SZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            try:
                result = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if result.tzinfo is None:
                    result = result.replace(tzinfo=timezone.utc)
                return result
            except ValueError:
                return None

    @classmethod
    def clear_cache(cls) -> None:
        with cls._lock:
            cls._cache.clear()

    @property
    def name(self) -> str:
        return "GDELT"
