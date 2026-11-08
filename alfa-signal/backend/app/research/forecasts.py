"""Alfa-Bank forecasts from research tables and their revisions between documents.

Обзоры банка повторяют таблицу прогнозов, но цифры в ней меняются от выпуска к выпуску:
31 июля банк ждал ставку 13,5% на конец 2026 года, 11 сентября — 14,0%. Если агент возьмёт
старый фрагмент, он выдаст устаревшую позицию банка за текущую. Здесь прогнозы извлекаются
из таблиц (столбцы вида «2026П»), и для каждого показателя берётся самый свежий документ;
расхождение со старыми документами помечается как пересмотр.
"""
import re
from typing import Any, Iterable, Optional

from app.research.pages import ExtractedPage
from app.research.registry import BankDocument

# Показатель → (название для людей, единица, шаблон названия строки таблицы).
INDICATORS: dict[str, tuple[str, str, str]] = {
    "key_rate_end": ("ключевая ставка на конец года", "%", r"ставка.*конец\s+года"),
    "key_rate_avg": ("средняя ключевая ставка за год", "%", r"ставка.*среднегод"),
    "inflation_dec": ("инфляция (декабрь к декабрю)", "%", r"инфляция.*дек"),
    "inflation_avg": ("среднегодовая инфляция", "%", r"инфляция.*среднегод"),
    "usd_rub_end": ("курс рубля к доллару на конец года", "руб./$", r"курс.*руб\./\$"),
    "cny_rub_end": ("курс рубля к юаню на конец года", "руб./юань", r"курс.*юан"),
    "gdp_growth": ("рост ВВП", "%", r"темпы роста ввп"),
    "retail_growth": ("рост оборота розничной торговли", "%", r"оборот розничной торговли"),
}
# Каналы влияния события → какие прогнозы банка относятся к делу.
CHANNEL_INDICATORS = {
    "interest_rate": ("key_rate_end", "key_rate_avg"),
    "deposit_yield": ("key_rate_end", "key_rate_avg"),
    "leasing_cost": ("key_rate_end",),
    "inflation": ("inflation_dec", "inflation_avg", "key_rate_end"),
    "currency": ("usd_rub_end", "cny_rub_end"),
    "international_trade": ("usd_rub_end", "cny_rub_end"),
    "revenue": ("retail_growth", "gdp_growth"),
}
FORECAST_COLUMN = re.compile(r"^(\d{4})\s*П$", re.IGNORECASE)
NUMBER = re.compile(r"^-?\d+(?:[.,]\d+)?")


def _value(cell: str) -> Optional[float]:
    match = NUMBER.match(cell.strip().replace(" ", ""))
    return float(match.group(0).replace(",", ".")) if match else None


def _indicator(label: str) -> Optional[str]:
    lowered = label.casefold()
    return next((key for key, (_, _, pattern) in INDICATORS.items() if re.search(pattern, lowered)), None)


def extract_forecasts(document: BankDocument, pages: Iterable[ExtractedPage]) -> list[dict[str, Any]]:
    """Прогнозы из таблиц: строка «показатель», столбцы «2026П», «2027П»."""
    forecasts: list[dict[str, Any]] = []
    for page in pages:
        for block in page.blocks:
            if block.kind != "table":
                continue
            rows = [[cell.strip() for cell in line.split("|")] for line in block.text.splitlines() if "|" in line]
            if not rows:
                continue
            header = rows[0]
            columns = {index: FORECAST_COLUMN.match(cell) for index, cell in enumerate(header)}
            periods = {index: match.group(1) for index, match in columns.items() if match}
            if not periods:
                continue
            for row in rows[1:]:
                indicator = _indicator(row[0]) if row else None
                if indicator is None:
                    continue
                for index, period in periods.items():
                    value = _value(row[index]) if index < len(row) else None
                    if value is None:
                        continue
                    forecasts.append(
                        {
                            "indicator": indicator,
                            "period": period,
                            "value": value,
                            "doc_id": document.doc_id,
                            "doc_title": document.title,
                            "doc_date": document.date,
                            "page": page.page,
                        }
                    )
    return forecasts


def forecast_table(forecasts: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Для каждого «показатель:период» — актуальный прогноз (самый свежий документ) и история."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in forecasts:
        grouped.setdefault(f"{item['indicator']}:{item['period']}", []).append(item)

    table: dict[str, dict[str, Any]] = {}
    for key, items in grouped.items():
        # Один документ мог повторить таблицу дважды — берём по одному значению на документ.
        by_doc = {item["doc_id"]: item for item in sorted(items, key=lambda item: item["page"])}
        history = sorted(by_doc.values(), key=lambda item: item["doc_date"])
        latest = history[-1]
        previous = [item for item in history[:-1] if item["value"] != latest["value"]]
        table[key] = {
            "indicator": latest["indicator"],
            "label": INDICATORS[latest["indicator"]][0],
            "unit": INDICATORS[latest["indicator"]][1],
            "period": latest["period"],
            "latest": latest,
            "history": history,
            "revised": bool(previous),
            "previous": previous[-1] if previous else None,
        }
    return table


def _fmt(value: float, unit: str) -> str:
    number = f"{value:.1f}".replace(".", ",")
    return f"{number}%" if unit == "%" else f"{number} {unit}"


def describe(entry: dict[str, Any]) -> str:
    latest, unit = entry["latest"], entry["unit"]
    text = (
        f"Прогноз Альфа-Банка: {entry['label']} {entry['period']} — {_fmt(latest['value'], unit)} "
        f"(«{latest['doc_title']}», {latest['doc_date']}, стр. {latest['page']})"
    )
    if entry["previous"]:
        old = entry["previous"]
        text += (
            f". Прогноз пересмотрен: ранее {_fmt(old['value'], unit)} "
            f"(«{old['doc_title']}», {old['doc_date']}); актуален более свежий"
        )
    return text


def relevant_forecasts(table: dict[str, dict[str, Any]], channels: Iterable[str]) -> list[dict[str, Any]]:
    indicators = {indicator for channel in channels for indicator in CHANNEL_INDICATORS.get(channel, ())}
    return sorted(
        (entry for entry in table.values() if entry["indicator"] in indicators),
        key=lambda entry: (entry["indicator"], entry["period"]),
    )
