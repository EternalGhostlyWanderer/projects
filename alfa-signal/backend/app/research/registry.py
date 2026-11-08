"""Registry of Alfa-Bank research materials provided with the case."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional, Union

from app.schemas.event import ImpactChannel


@dataclass(frozen=True)
class BankDocument:
    doc_id: str
    title: str
    date: str
    file_hints: tuple[str, ...]
    channels: tuple[ImpactChannel, ...]
    topics: tuple[str, ...] = field(default_factory=tuple)


# Названия и даты — из шапок документов и списка материалов кейса (стр. 17).
# file_hints — фрагменты имени файла; регистр и префиксы при загрузке не важны.
DOCUMENTS: tuple[BankDocument, ...] = (
    BankDocument(
        doc_id="policy_rate_2026_09_11",
        title="Ключевая ставка ЦБ РФ: ставка без изменения на 14,0%, риторика стала жестче",
        date="2026-09-11",
        file_hints=("Policy_Rate_11Sep",),
        channels=("interest_rate", "deposit_yield", "leasing_cost", "inflation"),
        topics=("ключевая ставка", "денежно-кредитная политика", "инфляционные ожидания"),
    ),
    BankDocument(
        doc_id="bond_brief_2026_09_14",
        title="Бонд Бриф: итоги недели",
        date="2026-09-14",
        file_hints=("14092026", "Bond_Brief", "Бонд"),
        channels=("interest_rate", "deposit_yield"),
        topics=("облигации", "ОФЗ", "доходность", "долговой рынок"),
    ),
    BankDocument(
        doc_id="inflation_2026_09_02",
        title="Инфляция 25–31 августа: основные выводы",
        date="2026-09-02",
        file_hints=("Inflation_tracker",),
        channels=("inflation", "interest_rate"),
        topics=("инфляция", "цены", "потребительские цены"),
    ),
    BankDocument(
        doc_id="macro_7m26_2026_09_07",
        title="Макростатистика 7М26: данные по рынку труда не подтверждают охлаждения экономики",
        date="2026-09-07",
        file_hints=("7M26",),
        channels=("revenue", "interest_rate", "inflation"),
        topics=("макростатистика", "рынок труда", "зарплаты", "безработица", "розничная торговля"),
    ),
    BankDocument(
        doc_id="macro_1h26_2026_07_31",
        title="Макростатистика 1П26: слабый рост 1П26 смещает прогноз роста ВВП на 0,1% за год",
        date="2026-07-31",
        file_hints=("macro_stat1H26", "1H26"),
        channels=("revenue", "industry"),
        topics=("ВВП", "экономический рост", "макростатистика", "промышленность"),
    ),
    BankDocument(
        doc_id="consumption_2026_08_05",
        title="Потребление на пике",
        date="2026-08-05",
        file_hints=("consumption",),
        channels=("revenue", "inflation", "interest_rate"),
        topics=("потребление", "потребительский спрос", "розничная торговля", "спрос", "автомобили", "кредитование"),
    ),
    BankDocument(
        doc_id="gold_2026_08",
        title="Обзор рынка золота, август 2026",
        date="2026-08-01",
        file_hints=("Gold_digest",),
        channels=("currency", "international_trade"),
        topics=("золото", "драгоценные металлы", "сырьё"),
    ),
    BankDocument(
        doc_id="fi_strategy_3q26_2026_07_22",
        title="Тактический взгляд на 3-й квартал 2026 года: время собирать камни",
        date="2026-07-22",
        file_hints=("FI_Strategy_3Q26",),
        channels=("interest_rate", "deposit_yield", "currency"),
        topics=("стратегия", "облигации", "ставки", "долговой рынок"),
    ),
    BankDocument(
        doc_id="russian_steel_2021_04_15",
        title="Российская сталь. Ралли цен продолжается; прогноз результатов за 1К21",
        date="2021-04-15",
        file_hints=("Russian_Steels",),
        channels=("industry", "international_trade", "supply_chain"),
        topics=("металлургия", "сталь", "сырьё", "экспорт"),
    ),
)

DOCUMENTS_BY_ID = {document.doc_id: document for document in DOCUMENTS}


def match_document(path: Path) -> Optional[BankDocument]:
    name = path.name.casefold()
    for document in DOCUMENTS:
        if any(hint.casefold() in name for hint in document.file_hints):
            return document
    return None


def find_document_files(
    bank_dirs: Union[Path, Iterable[Path]],
) -> tuple[dict[str, Path], list[Path]]:
    """Return {doc_id: pdf} for known documents and the list of unknown PDFs.

    PDF ищутся во всех указанных папках, включая подпапки; документ узнаётся по имени файла.
    """
    dirs = [bank_dirs] if isinstance(bank_dirs, Path) else list(bank_dirs)
    paths = sorted(
        {path.resolve() for directory in dirs if directory.is_dir() for path in directory.rglob("*")
         if path.suffix.lower() == ".pdf"}
    )
    found: dict[str, Path] = {}
    unknown: list[Path] = []

    for path in paths:
        document = match_document(path)
        if document is None:
            unknown.append(path)
        elif document.doc_id not in found:
            found[document.doc_id] = path

    return found, unknown
