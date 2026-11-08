"""Quality of publications: clickbait headlines and trust in the source.

Ключевые слова не отличают деловую новость от развлекательной: «Россиянам рассказали о средневековом
параллельном импорте» содержит «импорт», «Постсоветской стране предрекли повышение налогов» — «налог».
Две простые и объяснимые меры:
- **заголовки-кликбейт** («Россиянам рассказали/назвали/объяснили…», «предрекли», «раскрыли способ»)
  отсеиваются при сборе, как публикации не про бизнес;
- **надёжность источника** — множитель балла в ленте, как значимость события: официальные источники и
  деловые издания — 1,0, платные издания с одним анонсом в ленте — 0,95, общие ленты — 0,9,
  развлекательные — 0,6 (NEWS_SOURCE_TRUST — переопределить).
"""
import os
import re
from typing import Optional
from urllib.parse import urlsplit

CLICKBAIT = re.compile(
    r"^(россиян\w*|жител\w*|москвич\w*|граждан\w*)\s+(рассказал\w*|назвал\w*|объяснил\w*|посоветовал\w*|"
    r"напомнил\w*|предупредил\w*|раскрыл\w*|дал\w*\s+совет\w*|дали\s+\w*\s*совет\w*)"
    r"|\b(стран\w*|миру|россиянам|европейц\w*|американц\w*)\s+предрекл\w*|\bраскрыл\w*\s+(способ|секрет)|\bназван\w*\s+(способ|секрет|неочевидн)"
    r"|\bнеочевидн\w*\s+(совет|способ|причин)|\bлайфхак|\bсредневеков|\bэксперт\w*\s+рассказал\w*\s+о\s+том"
    r"|\bраскрыт\w*\s+секрет|\bназвал\w*\s+(главн\w*\s+)?ошибк\w*\s+(россиян|при)",
    re.IGNORECASE,
)

# Домен → доверие. Не указан — DEFAULT_TRUST.
DEFAULT_TRUST = 1.0
SOURCE_TRUST = {
    "cbr.ru": 1.0,
    "moex.com": 1.0,
    "interfax.ru": 1.0,
    "tass.ru": 1.0,
    "vedomosti.ru": 1.0,
    "kommersant.ru": 1.0,
    "rbc.ru": 0.9,
    "rssexport.rbc.ru": 0.9,
    "ria.ru": 0.9,
    "lenta.ru": 0.6,
    # Иностранные издания без платного доступа (foreign.py): официальные и деловые — 1,0, отраслевые — 0,9.
    "federalreserve.gov": 1.0,
    "ecb.europa.eu": 1.0,
    "bbc.co.uk": 1.0,
    "feeds.bbci.co.uk": 1.0,
    "theguardian.com": 1.0,
    "cnbc.com": 1.0,
    "oilprice.com": 0.9,
    "mining.com": 0.9,
}
# Платные издания: в ленте только анонс, по нему не всегда можно судить о сути — доверие чуть ниже.
PAYWALL_TRUST = 0.95
PAYWALL_DOMAINS = (
    "bloomberg.com",
    "ft.com",
    "wsj.com",
    "economist.com",
    "barrons.com",
    "nikkei.com",
    "asia.nikkei.com",
    "reuters.com",
)
SOURCE_TRUST.update({domain: PAYWALL_TRUST for domain in PAYWALL_DOMAINS})
OFFICIAL_SOURCE_NAMES = {"Банк России": "cbr.ru", "Московская биржа": "moex.com"}


def is_clickbait(title: str) -> bool:
    return bool(CLICKBAIT.search(title.strip()))


def _domain(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _overrides() -> dict[str, float]:
    """NEWS_SOURCE_TRUST=lenta.ru:0.5,rbc.ru:1 — поправить доверие без изменения кода."""
    result = {}
    for item in os.getenv("NEWS_SOURCE_TRUST", "").split(","):
        if ":" not in item:
            continue
        domain, value = item.rsplit(":", 1)
        try:
            result[domain.strip().lower()] = max(0.0, min(1.0, float(value)))
        except ValueError:
            continue
    return result


def source_trust(url: Optional[str], source: Optional[str] = None) -> float:
    domain = OFFICIAL_SOURCE_NAMES.get(source or "") or _domain(url or "")
    table = {**SOURCE_TRUST, **_overrides()}
    while domain:
        if domain in table:
            return table[domain]
        domain = domain.partition(".")[2] if domain.count(".") > 1 else ""
    return DEFAULT_TRUST
