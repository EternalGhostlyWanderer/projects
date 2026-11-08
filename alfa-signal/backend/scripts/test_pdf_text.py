"""Check whether a PDF contains an extractable text layer."""
from __future__ import annotations

import argparse
from pathlib import Path

from pypdf import PdfReader


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверяет извлечение текста из PDF.")
    parser.add_argument("pdf_path", help="Путь к PDF, например data/research.pdf")
    parser.add_argument("--pages", type=int, default=5, help="Сколько первых страниц проверить (по умолчанию 5)")
    parser.add_argument("--show-text", action="store_true", help="Показать до 1000 символов с каждой проверенной страницы")
    args = parser.parse_args()

    path = Path(args.pdf_path).expanduser().resolve()
    if not path.is_file():
        parser.error(f"Файл не найден: {path}")
    if args.pages < 1:
        parser.error("--pages должен быть положительным числом")

    try:
        reader = PdfReader(str(path))
        print(f"PDF: {path.name}")
        print(f"Всего страниц: {len(reader.pages)}")
        page_limit = min(args.pages, len(reader.pages))
        empty_pages = 0
        for index in range(page_limit):
            text = reader.pages[index].extract_text() or ""
            if not text.strip():
                empty_pages += 1
            print(f"\nСтраница {index + 1}: извлечено {len(text)} символов")
            if args.show_text and text.strip():
                print(text[:1000])
                if len(text) > 1000:
                    print("[фрагмент обрезан до 1000 символов]")
        if empty_pages:
            print(
                f"\nНа {empty_pages} из {page_limit} проверенных страниц текст не извлечён. "
                "Страницы могут быть сканами/изображениями или иметь необычную структуру."
            )
        else:
            print("\nНа всех проверенных страницах найден извлекаемый текст.")
        return 0
    except Exception as exc:
        print(f"Не удалось прочитать PDF: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
