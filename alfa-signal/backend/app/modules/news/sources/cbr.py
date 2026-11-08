"""Official Bank of Russia data: key rate and exchange rates as feed events and agent facts.

Новости о ставке и курсе пересказывают цифры ЦБ — иногда с опозданием или ошибкой. Здесь цифры
берутся из первоисточника:
- ключевая ставка — веб-сервис DailyInfoWebServ (метод KeyRate, SOAP);
- официальные курсы — XML_daily.asp.
Изменение ставки и движение курса сильнее порога (CBR_FX_ALERT_PCT, по умолчанию 1%) становятся
событиями ленты с точными цифрами. Агент берёт отсюда текущую ставку и курсы как факты.
Оба сервиса открытые, без ключа; адреса фиксированы в коде — произвольные URL сюда не попадают.
"""
import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.modules.news.sources.base import RawNewsItem

logger = logging.getLogger(__name__)

SOURCE_NAME = "Банк России"
DAILY_INFO_URL = "https://www.cbr.ru/DailyInfoWebServ/DailyInfo.asmx"
XML_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
KEY_RATE_PAGE = "https://www.cbr.ru/hd_base/KeyRate/"
FX_PAGE = "https://www.cbr.ru/currency_base/daily/"
MOSCOW = timezone(timedelta(hours=3))

# Валюты расчётов клиентов: юань — основная для импорта из Китая, доллар и евро — для остальных.
CURRENCIES = {
    "CNY": ("юаня", "юань"),
    "USD": ("доллара", "доллар США"),
    "EUR": ("евро", "евро"),
}
KEY_RATE_LOOKBACK_DAYS = 120
SNAPSHOT_TTL = 3600

KEY_RATE_SOAP = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRate xmlns="http://web.cbr.ru/">
      <fromDate>{start}T00:00:00</fromDate>
      <ToDate>{end}T00:00:00</ToDate>
    </KeyRate>
  </soap:Body>
</soap:Envelope>"""


class CBRDataError(Exception):
    """Сервис ЦБ недоступен или ответил в неожиданном формате."""


def enabled() -> bool:
    return os.getenv("CBR_DATA_ENABLED", "1") == "1"


def fx_alert_pct() -> float:
    try:
        return float(os.getenv("CBR_FX_ALERT_PCT", "") or 1.0)
    except ValueError:
        return 1.0


def _request(url: str, *, data: Optional[bytes] = None, headers: Optional[dict[str, str]] = None, timeout: int = 15) -> bytes:
    request = Request(url, data=data, headers={"User-Agent": "Alfa-Signal/0.1", **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read(2_000_000)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CBRDataError(f"{url}: {exc}") from exc


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _number(value: Optional[str]) -> Optional[float]:
    try:
        return float((value or "").replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def parse_key_rates(payload: bytes) -> list[tuple[date, float]]:
    """Ответ KeyRate: строки <KR><DT>2026-09-12T00:00:00+03:00</DT><Rate>14.00</Rate></KR>."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise CBRDataError(f"KeyRate: некорректный XML: {exc}") from exc
    rates: dict[date, float] = {}
    for row in root.iter():
        if _local(row.tag) != "KR":
            continue
        fields = {_local(child.tag): (child.text or "").strip() for child in row}
        rate = _number(fields.get("Rate"))
        try:
            day = datetime.fromisoformat(fields.get("DT", "")).date()
        except ValueError:
            continue
        if rate is not None:
            rates[day] = rate
    return sorted(rates.items())


def parse_fx(payload: bytes) -> tuple[date, dict[str, float]]:
    """XML_daily: <ValCurs Date="25.10.2026"><Valute><CharCode>CNY</CharCode><Nominal>1</Nominal><Value>11,45</Value>."""
    try:
        root = ET.fromstring(payload)
        day = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise CBRDataError(f"XML_daily: неожиданный ответ: {exc}") from exc
    rates: dict[str, float] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").strip()
        value, nominal = _number(valute.findtext("Value")), _number(valute.findtext("Nominal")) or 1
        if code in CURRENCIES and value:
            rates[code] = round(value / nominal, 4)
    return day, rates


def parse_fx_all(payload: bytes) -> tuple[date, dict[str, dict[str, Any]]]:
    """Все валюты XML_daily: код → курс за номинал, номинал и название («Шведских крон» за 10)."""
    try:
        root = ET.fromstring(payload)
        day = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
    except (ET.ParseError, KeyError, ValueError) as exc:
        raise CBRDataError(f"XML_daily: неожиданный ответ: {exc}") from exc
    rates: dict[str, dict[str, Any]] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").strip().upper()
        value, nominal = _number(valute.findtext("Value")), _number(valute.findtext("Nominal")) or 1
        if code and value:
            rates[code] = {"value": value, "nominal": int(nominal), "name": (valute.findtext("Name") or code).strip()}
    return day, rates


_all_fx: Optional[tuple[float, tuple[date, dict[str, dict[str, Any]]]]] = None


def official_fx_facts(
    codes: Iterable[str], *, fetch: Callable[[], bytes] = lambda: _request(XML_DAILY_URL)
) -> list[dict[str, Any]]:
    """Официальные курсы ЦБ по кодам валют (любой из публикуемых ЦБ) — факты для ответа в чате.

    Валюты, которой нет в списке ЦБ (например, вона КНДР), в ответе просто не будет. Кеш — на час.
    """
    global _all_fx
    with _snapshot_lock:
        cached = _all_fx if _all_fx and _all_fx[0] > time.monotonic() else None
    if cached is None:
        parsed = parse_fx_all(fetch())
        with _snapshot_lock:
            _all_fx = (time.monotonic() + SNAPSHOT_TTL, parsed)
    else:
        parsed = cached[1]
    day, rates = parsed
    facts = []
    for code in dict.fromkeys(code.strip().upper() for code in codes if code.strip()):
        item = rates.get(code)
        if item is None:
            continue
        per_unit = item["value"] / item["nominal"]
        text = f"Официальный курс ЦБ на {day:%d.%m.%Y}: {_fmt(item['value'], 4)} руб. за {item['nominal']} {item['name']} ({code})"
        if item["nominal"] != 1:
            text += f", то есть {_fmt(per_unit, 4)} руб. за 1"
        facts.append({"id": f"market.fx.{code}", "text": text, "url": FX_PAGE, "date": day.isoformat()})
    return facts


def fetch_key_rates(today: Optional[date] = None, days: int = KEY_RATE_LOOKBACK_DAYS) -> list[tuple[date, float]]:
    today = today or datetime.now(MOSCOW).date()
    body = KEY_RATE_SOAP.format(start=(today - timedelta(days=days)).isoformat(), end=today.isoformat())
    payload = _request(
        DAILY_INFO_URL,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '"http://web.cbr.ru/KeyRate"'},
    )
    rates = parse_key_rates(payload)
    if not rates:
        raise CBRDataError("KeyRate: в ответе нет значений ставки")
    return rates


def fetch_fx(on: Optional[date] = None) -> tuple[date, dict[str, float]]:
    url = XML_DAILY_URL if on is None else f"{XML_DAILY_URL}?date_req={on:%d/%m/%Y}"
    return parse_fx(_request(url))


def fetch_fx_pair() -> tuple[tuple[date, dict[str, float]], tuple[date, dict[str, float]]]:
    """Последние два разных набора курсов: ЦБ не устанавливает курсы на выходные."""
    latest = fetch_fx()
    probe = latest[0]
    for _ in range(7):
        probe -= timedelta(days=1)
        previous = fetch_fx(probe)
        if previous[0] < latest[0]:
            return latest, previous
    raise CBRDataError("XML_daily: не найден предыдущий набор курсов")


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _moment(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=MOSCOW)


def key_rate_items(rates: list[tuple[date, float]]) -> list[RawNewsItem]:
    """Каждое изменение ставки за период — событие с датой вступления в силу."""
    items = []
    for (_, before), (day, after) in zip(rates, rates[1:]):
        if after == before:
            continue
        verb = "снизил" if after < before else "повысил"
        items.append(
            RawNewsItem(
                title=f"Банк России {verb} ключевую ставку до {_fmt(after)}% годовых",
                url=f"{KEY_RATE_PAGE}?UniDbQuery.Posted=True&UniDbQuery.From={day:%d.%m.%Y}&UniDbQuery.To={day:%d.%m.%Y}",
                source=SOURCE_NAME,
                published_at=_moment(day),
                summary=(
                    f"Официальные данные Банка России: ключевая ставка с {day:%d.%m.%Y} — {_fmt(after)}% "
                    f"годовых, до этого {_fmt(before)}%. Изменение {_fmt(after - before)} п.п."
                ),
            )
        )
    return items


def fx_items(latest: tuple[date, dict[str, float]], previous: tuple[date, dict[str, float]], threshold: float) -> list[RawNewsItem]:
    """Движение официального курса сильнее порога — событие с обеими цифрами."""
    (day, now), (before_day, before) = latest, previous
    items = []
    for code, (genitive, name) in CURRENCIES.items():
        if code not in now or code not in before:
            continue
        change = (now[code] / before[code] - 1) * 100
        if abs(change) < threshold:
            continue
        verb = "вырос" if change > 0 else "снизился"
        items.append(
            RawNewsItem(
                title=f"Официальный курс {genitive} {verb} на {_fmt(abs(change), 1)}% — до {_fmt(now[code], 2)} руб.",
                url=f"{FX_PAGE}?UniDbQuery.Posted=True&UniDbQuery.To={day:%d.%m.%Y}&currency={code}",
                source=SOURCE_NAME,
                published_at=_moment(day),
                summary=(
                    f"Официальный курс Банка России на {day:%d.%m.%Y}: {_fmt(now[code], 4)} руб. за 1 {name}; "
                    f"на {before_day:%d.%m.%Y} — {_fmt(before[code], 4)} руб. Изменение {change:+.1f}%."
                ),
            )
        )
    return items


class CBRSource:
    """Источник для сбора новостей: события из официальных данных, без LLM."""

    name = SOURCE_NAME

    # Источник данных, а не новостей: пустой ответ — норма (ставка и курс не менялись).
    kind = "data"

    def __init__(self, threshold: Optional[float] = None) -> None:
        self.threshold = fx_alert_pct() if threshold is None else threshold
        self.last_error: Optional[str] = None

    def fetch(self) -> list[RawNewsItem]:
        self.last_error = None
        items: list[RawNewsItem] = []
        errors = []
        try:
            items += key_rate_items(fetch_key_rates())
        except CBRDataError as exc:
            logger.warning("Ключевая ставка ЦБ недоступна: %s", exc)
            errors.append(f"KeyRate: {exc}")
        try:
            items += fx_items(*fetch_fx_pair(), self.threshold)
        except CBRDataError as exc:
            logger.warning("Курсы ЦБ недоступны: %s", exc)
            errors.append(f"XML_daily: {exc}")
        if errors:
            kind = "format" if all("неожиданн" in error or "некорректн" in error or "нет " in error for error in errors) else "network"
            self.last_error = f"{kind}: " + "; ".join(errors)
        return items


_snapshot: Optional[tuple[float, dict[str, Any]]] = None
_snapshot_lock = threading.Lock()


def market_snapshot(
    *,
    key_rates: Callable[[], list[tuple[date, float]]] = fetch_key_rates,
    fx_pair: Callable[[], Any] = fetch_fx_pair,
) -> dict[str, Any]:
    """Текущая ставка и курсы ЦБ для агента; кешируется на час."""
    global _snapshot
    with _snapshot_lock:
        if _snapshot and _snapshot[0] > time.monotonic():
            return _snapshot[1]
    rates = key_rates()
    (day, now), (before_day, before) = fx_pair()
    current_day, current = rates[-1]
    changed = next((day for day, rate in reversed(rates) if rate != current), None)
    since = next((d for d, rate in rates if rate == current and (changed is None or d > changed)), current_day)
    snapshot = {
        "key_rate": {"value": current, "since": since.isoformat(), "as_of": current_day.isoformat()},
        "fx": {
            code: {
                "value": now[code],
                "date": day.isoformat(),
                "previous": before.get(code),
                "previous_date": before_day.isoformat(),
            }
            for code in CURRENCIES
            if code in now
        },
    }
    with _snapshot_lock:
        _snapshot = (time.monotonic() + SNAPSHOT_TTL, snapshot)
    return snapshot


def clear_snapshot_cache() -> None:
    global _snapshot
    with _snapshot_lock:
        _snapshot = None


def snapshot_facts(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Факты для доказательной базы инсайта: формулировка, ссылка на страницу ЦБ, дата."""
    key = snapshot["key_rate"]
    since = date.fromisoformat(key["since"])
    facts = [
        {
            "id": "market.key_rate",
            "text": f"Ключевая ставка Банка России — {_fmt(key['value'])}% годовых (действует с {since:%d.%m.%Y})",
            "url": KEY_RATE_PAGE,
            "date": key["as_of"],
        }
    ]
    for code, item in snapshot["fx"].items():
        day = date.fromisoformat(item["date"])
        text = f"Официальный курс ЦБ на {day:%d.%m.%Y}: {_fmt(item['value'], 4)} руб. за 1 {CURRENCIES[code][1]}"
        if item.get("previous"):
            change = (item["value"] / item["previous"] - 1) * 100
            # Словами, а не знаком: модель теряла минус и писала «вырос» вместо «снизился».
            direction = "вырос" if change > 0 else "снизился" if change < 0 else "не изменился"
            amount = f" на {_fmt(abs(change), 1)}%" if change else ""
            previous_day = date.fromisoformat(item["previous_date"])
            text += (
                f"; по сравнению с {previous_day:%d.%m.%Y} курс {direction}{amount} "
                f"(было {_fmt(item['previous'], 4)} руб.)"
            )
        facts.append({"id": f"market.fx.{code}", "text": text, "url": FX_PAGE, "date": item["date"]})
    return facts
