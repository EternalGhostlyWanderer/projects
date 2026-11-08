"""Build the search index of Alfa-Bank research PDFs (searched in data/raw and data/bank, with subfolders).

Примеры:
    python backend/scripts/build_bank_index.py                      # без API: только кеш, текстовый слой, ручные расшифровки
    python backend/scripts/build_bank_index.py --vision --max-pages 1 --doc policy_rate_2026_09_11   # проба на 1 странице
    python backend/scripts/build_bank_index.py --vision             # распознать все сканы (платно, спросит подтверждение)

Распознанные страницы сохраняются в data/processed/bank_pages/<doc_id>.json и повторно не распознаются.
Пересобрать документ: --doc <doc_id> (можно несколько раз). Перераспознать всё: --force.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.index import (  # noqa: E402
    BANK_DIRS,
    PROCESSED_DIR,
    build_bank_index,
)
from app.research.pages import (  # noqa: E402
    MIN_TEXT_LAYER_CHARS,
    GatewayUnavailableError,
    manual_page_path,
)
from app.research.registry import DOCUMENTS_BY_ID, find_document_files  # noqa: E402
from app.research.search import reload_index  # noqa: E402


def pages_needing_vision(args: argparse.Namespace) -> int:
    """Pages that will go to the vision model: no text layer, no manual transcript, not saved yet."""
    import pymupdf

    from app.research.pages import load_pages

    files, _ = find_document_files(args.bank_dirs)
    total = 0
    for doc_id, path in files.items():
        selected = bool(args.doc) and doc_id in args.doc
        if args.doc and not selected:
            continue
        pages_path = args.processed_dir / "bank_pages" / f"{doc_id}.json"
        saved = {page.page for page in load_pages(pages_path)} if pages_path.is_file() else set()
        with pymupdf.open(str(path)) as document:
            for index, page in enumerate(document):
                number = index + 1
                if args.max_pages and number > args.max_pages:
                    break
                if number in saved and not (args.force or selected):
                    continue
                has_text = len(page.get_text().strip()) >= MIN_TEXT_LAYER_CHARS
                has_manual = manual_page_path(args.processed_dir.parent / "raw" / "bank_manual", doc_id, number).is_file()
                total += 0 if has_text or has_manual else 1
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="Сборка индекса аналитики Альфа-Банка.")
    parser.add_argument(
        "--bank-dir",
        dest="bank_dirs",
        type=Path,
        action="append",
        help="Папка с PDF банка (можно несколько раз); по умолчанию data/raw и data/bank с подпапками",
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=PROCESSED_DIR,
        help="Каталог с кешем страниц и результатом индекса (по умолчанию data/processed)",
    )
    parser.add_argument("--vision", action="store_true", help="Распознавать сканы через Qwen3-VL (платно)")
    parser.add_argument("--doc", action="append", choices=sorted(DOCUMENTS_BY_ID), help="Перераспознать этот документ (можно несколько раз)")
    parser.add_argument("--max-pages", type=int, help="Ограничить число страниц на документ (для пробы)")
    parser.add_argument("--force", action="store_true", help="Игнорировать сохранённые страницы")
    parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение")
    args = parser.parse_args()

    args.bank_dirs = args.bank_dirs or list(BANK_DIRS)
    pages_dir = PROCESSED_DIR / "bank_pages"
    has_pages = pages_dir.is_dir() and any(pages_dir.glob("*.json"))
    if not any(directory.is_dir() for directory in args.bank_dirs) and not has_pages:
        print("Папки не найдены: " + ", ".join(map(str, args.bank_dirs)) + ". Положите PDF Альфа-Банка в data/raw/.")
        return 1
    if not any(directory.is_dir() for directory in args.bank_dirs):
        print(f"PDF нет — индекс собирается из распознанных страниц {pages_dir} (без модели).")

    if args.vision:
        count = pages_needing_vision(args)
        print(f"Страниц для распознавания через LLM: {count} (по одному запросу на страницу).")
        if count and not args.yes:
            answer = input("Запустить? Введите yes для подтверждения: ").strip().lower()
            if answer != "yes":
                print("Отменено; запросы к API не отправлялись.")
                return 0

    try:
        report = build_bank_index(
            bank_dirs=args.bank_dirs,
            manual_dir=args.processed_dir.parent / "raw" / "bank_manual",
            processed_dir=args.processed_dir,
            use_vision=args.vision,
            force=args.force,
            only=set(args.doc) if args.doc else None,
            max_pages=args.max_pages,
        )
    except GatewayUnavailableError as exc:
        print(f"\nОстановлено: {exc}")
        print("Повторный запуск с --vision продолжит с нераспознанных страниц.")
        return 1
    except KeyboardInterrupt:
        print("\nПрервано. Распознанные страницы сохранены; повторный запуск продолжит с остальных.")
        return 130
    reload_index()

    print(f"\n{'документ':<32}{'стр.':<8}{'новых':<7}{'фрагм.':<8}{'способ':<22}источник")
    for item in report["documents"]:
        print(
            f"{item['doc_id']:<32}{str(item['pages']) + '/' + str(item['total_pages']):<8}"
            f"{item['new_pages']:<7}{item['chunks']:<8}"
            f"{','.join(item['methods']) or '—':<22}{item['source']}"
        )
    print(f"\nВсего фрагментов: {report['chunks']}; прогнозов из таблиц: {report.get('forecasts', 0)}")
    if report["missing_documents"]:
        print("Нет файлов для:", ", ".join(report["missing_documents"]))
    if report["unknown_files"]:
        print("Не распознаны по имени (добавьте file_hints в registry.py):", ", ".join(report["unknown_files"]))
    if report["errors"]:
        print(f"\nНе распознано страниц: {len(report['errors'])} — повторный запуск с --vision дораспознает только их:")
        for error in report["errors"]:
            print("  -", error)

    limit = args.max_pages
    missing = sum(
        max(0, min(item["total_pages"], limit or item["total_pages"]) - item["pages"])
        for item in report["documents"]
    )
    if limit:
        print(f"Обработано не больше {limit} стр. на документ (--max-pages); остальные страницы не трогались.")
    if missing and not args.vision:
        print(
            f"Страниц без текста: {missing}. Это сканы — запустите с --vision "
            "или положите расшифровки в data/raw/bank_manual/<doc_id>/p<N>.txt"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
