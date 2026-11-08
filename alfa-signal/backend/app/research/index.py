"""Split extracted pages into retrievable chunks and store the bank research index."""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional

from pydantic import BaseModel

from app.llm import LLMClient
from app.research.pages import (
    ExtractedPage,
    OcrRun,
    extract_document_pages,
    load_pages,
    page_count,
    save_pages,
)
from app.research.forecasts import extract_forecasts
from app.research.registry import DOCUMENTS_BY_ID, BankDocument, find_document_files

PROJECT_ROOT = Path(__file__).resolve().parents[3]
# PDF банка ищутся во всей папке data/raw (с подпапками) и в data/bank. Другую папку можно задать
# переменной BANK_DIR (относительный путь — от корня репозитория).
BANK_DIRS: tuple[Path, ...] = (
    (PROJECT_ROOT / os.environ["BANK_DIR"],)
    if os.getenv("BANK_DIR")
    else (PROJECT_ROOT / "data" / "raw", PROJECT_ROOT / "data" / "bank")
)
MANUAL_DIR = PROJECT_ROOT / "data" / "raw" / "bank_manual"
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
INDEX_PATH = PROCESSED_DIR / "bank_index.json"

INDEX_VERSION = 1
MIN_CHUNK_CHARS = 350
MAX_CHUNK_CHARS = 1400

# Строка графика из одних чисел, дат и знаков — это подпись деления оси или шкалы, не содержание.
AXIS_LABEL_LINE = re.compile(r"^[\d\s.,:%/–—+-]+$")
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+(?=[А-ЯЁA-Z0-9«\"])")


class BankChunk(BaseModel):
    chunk_id: str
    doc_id: str
    doc_title: str
    doc_date: str
    page: int
    section: Optional[str] = None
    kind: Literal["text", "table", "chart"]
    text: str


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]

    parts: list[str] = []
    current = ""
    for sentence in SENTENCE_END.split(text):
        if current and len(current) + len(sentence) + 1 > MAX_CHUNK_CHARS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_document(document: BankDocument, pages: list[ExtractedPage]) -> list[BankChunk]:
    chunks: list[BankChunk] = []
    section: Optional[str] = None

    def add(page: int, kind: str, text: str) -> None:
        for part in _split_long(text):
            chunks.append(
                BankChunk(
                    chunk_id=f"{document.doc_id}-p{page}-{len(chunks) + 1:02d}",
                    doc_id=document.doc_id,
                    doc_title=document.title,
                    doc_date=document.date,
                    page=page,
                    section=section,
                    kind=kind,  # type: ignore[arg-type]
                    text=part,
                )
            )

    for page in pages:
        buffer = ""

        def flush() -> None:
            nonlocal buffer
            if buffer:
                add(page.page, "text", buffer)
                buffer = ""

        for block in page.blocks:
            text = " ".join(block.text.split())
            heading = " ".join((block.heading or "").split())

            if block.kind == "footer":
                continue
            if block.kind == "title":
                # Модель иногда склеивает с заголовком документа первый абзац — его нельзя терять.
                if len(text) <= 200:
                    continue
                block = block.model_copy(update={"kind": "paragraph", "heading": None})
            if block.kind == "heading":
                flush()
                section = text or heading or section
                continue
            if block.kind == "chart":
                text = " ".join(
                    line.strip()
                    for line in block.text.splitlines()
                    if line.strip() and not AXIS_LABEL_LINE.match(line.strip())
                )
            if block.kind in {"table", "chart"}:
                flush()
                label = (
                    "График (распознан с изображения, значения приблизительные)"
                    if block.kind == "chart"
                    else "Таблица"
                )
                if text or heading:
                    add(page.page, block.kind, f"{label}: {heading} {text}".strip())
                continue

            piece = f"{heading}: {text}" if heading and text else heading or text
            if not piece:
                continue
            if heading:
                flush()
            if buffer and len(buffer) + len(piece) > MAX_CHUNK_CHARS:
                flush()
            buffer = f"{buffer}\n{piece}".strip()
            if len(buffer) >= MIN_CHUNK_CHARS:
                flush()

        flush()

    return chunks


def build_bank_index(
    *,
    bank_dirs: Iterable[Path] = BANK_DIRS,
    manual_dir: Path = MANUAL_DIR,
    processed_dir: Path = PROCESSED_DIR,
    use_vision: bool = False,
    force: bool = False,
    only: Optional[set[str]] = None,
    max_pages: Optional[int] = None,
    llm: Optional[LLMClient] = None,
) -> dict:
    """Extract pages (cached per document), chunk them and write the index file."""
    files, unknown = find_document_files(bank_dirs)
    pages_dir = processed_dir / "bank_pages"
    report: dict = {"documents": [], "unknown_files": [str(path.name) for path in unknown]}
    chunks: list[BankChunk] = []

    report["errors"] = []
    forecasts: list[dict] = []
    run = OcrRun()
    for doc_id, path in files.items():
        document = DOCUMENTS_BY_ID[doc_id]
        pages_path = pages_dir / f"{doc_id}.json"
        total = page_count(path)
        limit = min(total, max_pages) if max_pages else total
        cached = load_pages(pages_path) if pages_path.is_file() else []
        errors: list[str] = []

        if only is not None and doc_id not in only:
            # Документ не выбран через --doc: берём только сохранённое.
            if not cached:
                continue
            pages, new = cached, []
        else:
            # --doc / --force перераспознают страницы в пределах limit; остальное из сохранённого.
            redo = force or only is not None
            keep = [page for page in cached if not (redo and page.page <= limit)]
            collected: list[ExtractedPage] = []

            def save_progress(page: ExtractedPage, keep=keep, collected=collected, pages_path=pages_path) -> None:
                # Сохраняем после каждой страницы: прерывание не теряет уже оплаченные распознавания.
                collected.append(page)
                save_pages(sorted([*keep, *collected], key=lambda item: item.page), pages_path)

            new = extract_document_pages(
                document,
                path,
                manual_dir=manual_dir,
                use_vision=use_vision,
                max_pages=max_pages,
                llm=llm,
                skip_pages={page.page for page in keep},
                errors=errors,
                run=run,
                on_page=save_progress,
            )
            pages = sorted([*keep, *new], key=lambda page: page.page)

        document_chunks = chunk_document(document, pages)
        chunks.extend(document_chunks)
        forecasts.extend(extract_forecasts(document, pages))
        report["errors"].extend(errors)
        report["documents"].append(
            {
                "doc_id": doc_id,
                "file": path.name,
                "pages": len(pages),
                "total_pages": total,
                "new_pages": len(new),
                "methods": sorted({page.method for page in pages}),
                "chunks": len(document_chunks),
                "source": "extracted" if new and len(new) == len(pages) else "cache+new" if new else "cache",
            }
        )

    # Документы без PDF, но с распознанными страницами (data/processed/bank_pages в репозитории):
    # чистый клон собирает индекс без PDF и без модели.
    for doc_id, document in DOCUMENTS_BY_ID.items():
        pages_path = pages_dir / f"{doc_id}.json"
        if doc_id in files or not pages_path.is_file():
            continue
        if only is not None and doc_id not in only:
            continue
        pages = load_pages(pages_path)
        document_chunks = chunk_document(document, pages)
        chunks.extend(document_chunks)
        forecasts.extend(extract_forecasts(document, pages))
        report["documents"].append(
            {
                "doc_id": doc_id,
                "file": "—",
                "pages": len(pages),
                "total_pages": len(pages),
                "new_pages": 0,
                "methods": sorted({page.method for page in pages}),
                "chunks": len(document_chunks),
                "source": "pages",
            }
        )

    built = {item["doc_id"] for item in report["documents"]}
    report["missing_documents"] = sorted(set(DOCUMENTS_BY_ID) - built)
    index = {
        "version": INDEX_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "chunks": [chunk.model_dump() for chunk in chunks],
        # Прогнозы из таблиц обзоров — для сравнения позиций банка разных дат (forecasts.py).
        "forecasts": forecasts,
    }
    processed_dir.mkdir(parents=True, exist_ok=True)
    (processed_dir / INDEX_PATH.name).write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["chunks"] = len(chunks)
    report["forecasts"] = len(forecasts)
    return report


def load_chunks(path: Path = INDEX_PATH) -> list[BankChunk]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [BankChunk.model_validate(item) for item in data.get("chunks", [])]


def load_forecasts(path: Path = INDEX_PATH) -> list[dict]:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("forecasts", [])
