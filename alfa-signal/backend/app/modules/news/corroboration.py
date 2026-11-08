"""Cross-checking figures between publications about the same event.

Склейка собирает несколько изданий об одном событии (clustering.py). Здесь из каждой
публикации берутся ключевые цифры — проценты и суммы с указанием показателя («ставка 14%»,
«инфляция 6,1%», «пошлина 10%») — и сравниваются между независимыми изданиями:
- цифру назвали два и больше изданий — подтверждено;
- для одного показателя издания называют разные цифры и ни одной общей — расхождение.
Подтверждения и расхождения становятся доказательствами разбора (evidence.py), а проверка
не даёт подать спорную цифру как факт без оговорки (verify.py).
"""
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

# Показатель — по слову рядом с числом (до четырёх слов перед ним).
MEASURES: tuple[tuple[str, str], ...] = (
    ("ключевая ставка", r"ставк"),
    ("инфляция", r"инфляц|цен\w*\s+выросл|подорожан"),
    ("курс", r"курс|рубл\w*\s+к\s+(доллар|юан|евро)"),
    ("ВВП", r"\bввп\b"),
    ("пошлина", r"пошлин"),
    ("налог", r"налог|ндс|ндфл"),
    ("выручка", r"выручк|продаж"),
    ("экспорт", r"экспорт"),
    ("импорт", r"импорт"),
    ("доходность", r"доходност"),
)
FIGURE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|процент\w*|п\.\s?п\.|млрд|млн|трлн|руб\w*|долл\w*|юан\w*)",
    re.IGNORECASE,
)
CONTEXT_WORDS = 6


@dataclass(frozen=True)
class Figure:
    measure: str
    value: str
    unit: str


@dataclass
class Publication:
    outlet: str
    url: str
    title: str
    text: str
    figures: set[Figure] = field(default_factory=set)


def _value(raw: str) -> str:
    return raw.replace(",", ".").rstrip("0").rstrip(".") if "." in raw.replace(",", ".") else raw


def _unit(raw: str) -> str:
    lowered = raw.lower()
    if lowered.startswith(("%", "процент")):
        return "%"
    if lowered.startswith("п"):
        return "п.п."
    return lowered[:4]


def extract_figures(text: str) -> set[Figure]:
    """Цифры с показателем: «ставку на уровне 14%» → (ключевая ставка, 14, %)."""
    figures: set[Figure] = set()
    lowered = text.casefold()
    for match in FIGURE.finditer(lowered):
        # Контекст — в пределах предложения, показатель — ближайший к числу.
        sentence = re.split(r"[.!?;]\s", lowered[: match.start()])[-1]
        before = " ".join(sentence.split()[-CONTEXT_WORDS:])
        positions = [
            (max(found.end() for found in re.finditer(pattern, before)), name)
            for name, pattern in MEASURES
            if re.search(pattern, before)
        ]
        measure = max(positions)[1] if positions else None
        if measure:
            figures.add(Figure(measure, _value(match.group(1)), _unit(match.group(2))))
    return figures


def outlet_of(url: str, source: str) -> str:
    """Издание — по домену: перепечатки одного издания под разными адресами не подтверждают друг друга."""
    host = urlsplit(url).netloc.lower().removeprefix("www.")
    return host or source.lower()


def publications(event: dict[str, Any]) -> list[Publication]:
    """Все публикации события: исходная и приклеенные, у каждой свой текст."""
    items: list[Publication] = []
    seen: set[str] = set()
    sources = event.get("sources") or []
    first = {
        "url": event.get("url"),
        "source": event.get("source") or "",
        "title": event.get("title") or "",
        "summary": event.get("summary") or event.get("text") or "",
    }
    for raw in [first, *sources]:
        url = str(raw.get("url") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        text = f"{raw.get('title') or ''}. {raw.get('summary') or ''}"
        items.append(
            Publication(
                outlet=outlet_of(url, str(raw.get("source") or "")),
                url=url,
                title=str(raw.get("title") or ""),
                text=text,
                figures=extract_figures(text),
            )
        )
    return items


def _fmt(figure: Figure) -> str:
    value = figure.value.replace(".", ",")
    return f"{value}{figure.unit}" if figure.unit == "%" else f"{value} {figure.unit}"


def corroborate(event: dict[str, Any]) -> dict[str, Any]:
    """Подтверждённые и спорные цифры события по независимым изданиям."""
    items = publications(event)
    by_outlet: dict[str, set[Figure]] = {}
    for item in items:
        by_outlet.setdefault(item.outlet, set()).update(item.figures)

    confirmed = []
    counted: dict[Figure, list[str]] = {}
    for outlet, figures in by_outlet.items():
        for figure in figures:
            counted.setdefault(figure, []).append(outlet)
    for figure, outlets in sorted(counted.items(), key=lambda pair: (pair[0].measure, pair[0].value)):
        if len(outlets) >= 2:
            confirmed.append({"measure": figure.measure, "value": _fmt(figure), "outlets": sorted(outlets)})

    conflicts = []
    measures = {figure.measure for figures in by_outlet.values() for figure in figures}
    for measure in sorted(measures):
        values = {
            outlet: {figure for figure in figures if figure.measure == measure}
            for outlet, figures in by_outlet.items()
        }
        values = {outlet: figures for outlet, figures in values.items() if figures}
        if len(values) < 2:
            continue
        common = set.intersection(*values.values())
        if not common:
            conflicts.append(
                {
                    "measure": measure,
                    "values": {outlet: sorted(_fmt(figure) for figure in figures) for outlet, figures in sorted(values.items())},
                    "numbers": sorted({figure.value for figures in values.values() for figure in figures}),
                }
            )
    return {
        "publications": len(items),
        "outlets": sorted(by_outlet),
        "confirmed": confirmed,
        "conflicts": conflicts,
    }


def conflict_numbers(evidence: Iterable[Any]) -> set[str]:
    """Спорные числа из доказательств event.conflict.* (для проверки выводов)."""
    numbers: set[str] = set()
    for item in evidence:
        identifier = getattr(item, "id", "")
        if identifier.startswith("event.conflict."):
            numbers.update(re.findall(r"\d+(?:[.,]\d+)?", getattr(item, "text", "")))
    return {number.replace(",", ".").rstrip("0").rstrip(".") if "." in number.replace(",", ".") else number for number in numbers}


def describe_conflict(conflict: dict[str, Any]) -> str:
    parts = "; ".join(f"{outlet} — {', '.join(values)}" for outlet, values in conflict["values"].items())
    return f"Издания расходятся в цифрах ({conflict['measure']}): {parts}"


def describe_confirmed(item: dict[str, Any]) -> str:
    return (
        f"{item['measure'].capitalize()} {item['value']} — подтверждено {len(item['outlets'])} изданиями: "
        f"{', '.join(item['outlets'])}"
    )


def summary_line(result: dict[str, Any]) -> Optional[str]:
    if result["publications"] < 2:
        return None
    return (
        f"Публикаций: {result['publications']} ({len(result['outlets'])} изд.); подтверждено цифр: "
        f"{len(result['confirmed'])}; расхождений: {len(result['conflicts'])}"
    )
