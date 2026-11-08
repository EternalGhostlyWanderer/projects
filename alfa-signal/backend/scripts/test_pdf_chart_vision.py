"""Render one PDF page and test image input through the OpenAI-compatible gateway."""
from __future__ import annotations

import argparse
import base64
from pathlib import Path

import pymupdf

from common import THINK_STYLE_CHOICES, make_client, safe_error, think_off_body, usage_summary


def render_page_png(path: Path, page_number: int, zoom: float) -> bytes:
    doc = pymupdf.open(str(path))
    try:
        if page_number > len(doc):
            raise ValueError(f"В PDF только {len(doc)} страниц, запрошена {page_number}")
        page = doc[page_number - 1]
        # Keep image dimensions moderate to limit image-token cost.
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Отправляет одну страницу PDF как изображение модели; это API-запрос."
    )
    parser.add_argument("pdf_path", help="Например data/bank_research.pdf")
    parser.add_argument("--page", type=int, required=True, help="Номер страницы PDF, начиная с 1")
    parser.add_argument("--model", help="Модель с поддержкой изображений; по умолчанию LLM_MODEL.")
    parser.add_argument("--zoom", type=float, default=1.5, help="Масштаб рендера (по умолчанию 1.5).")
    parser.add_argument("--max-tokens", type=int, default=1500)
    parser.add_argument("--think-style", choices=THINK_STYLE_CHOICES, default="none")
    args = parser.parse_args()

    path = Path(args.pdf_path).expanduser().resolve()
    if not path.is_file():
        parser.error(f"Файл не найден: {path}")
    if args.page < 1:
        parser.error("--page нумеруется с 1 и должен быть положительным")

    try:
        image_bytes = render_page_png(path, args.page, args.zoom)
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("ascii")
        print(f"Размер изображения: {len(image_bytes) / 1024:.0f} КБ")

        client, default_model = make_client()
        model = args.model or default_model
        kwargs: dict = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Проанализируй изображение страницы финансово-экономического PDF. "
                                "Если виден график, укажи тему, подписи осей, единицы измерения, "
                                "период и только те значения/тенденции, которые читаются уверенно. "
                                "Не угадывай нечитаемые числа; отметь ограничения. Отвечай по-русски."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            "max_tokens": args.max_tokens,
        }
        body = think_off_body(args.think_style)
        if body:
            kwargs["extra_body"] = body

        response = client.chat.completions.create(**kwargs)
        choice = response.choices[0]

        print("Модель:", model)
        print(f"PDF: {path.name}, страница {args.page}")
        print("finish_reason:", choice.finish_reason)
        print("\nОтвет модели:\n")
        print(choice.message.content or "[Пустой ответ]")
        print("\nUsage:", usage_summary(response))
        if choice.finish_reason == "length":
            print("Ответ оборван по лимиту: увеличьте --max-tokens или отключите рассуждения.")
        return 0
    except Exception as exc:
        print("Визуальный тест не прошёл:")
        print(safe_error(exc))
        print(
            "Проверьте поддержку image_url/data URL и мультимодального ввода шлюзом. "
            "Ошибка не обязательно означает, что исходная модель не поддерживает изображения."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
