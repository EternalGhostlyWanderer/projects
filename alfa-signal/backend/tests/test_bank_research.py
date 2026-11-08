import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pymupdf

from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from app.research.index import BankChunk, build_bank_index, chunk_document, load_chunks
from app.research.pages import (
    ExtractedPage,
    GatewayUnavailableError,
    PageBlock,
    extract_document_pages,
    load_pages,
)
from app.research.registry import DOCUMENTS_BY_ID, match_document
from app.research.search import build_search_index, search_bank_research, search_chunks, tokenize

RATE_DOC = DOCUMENTS_BY_ID["policy_rate_2026_09_11"]
STEEL_DOC = DOCUMENTS_BY_ID["russian_steel_2021_04_15"]


def chunk(chunk_id: str, document, text: str, page: int = 1) -> BankChunk:
    return BankChunk(
        chunk_id=chunk_id,
        doc_id=document.doc_id,
        doc_title=document.title,
        doc_date=document.date,
        page=page,
        kind="text",
        text=text,
    )


CHUNKS = [
    chunk("rate-1", RATE_DOC, "Регулятор оставил ключевую ставку без изменения, риторика стала жестче. Мы ожидаем сохранения паузы."),
    chunk("rate-2", RATE_DOC, "Инфляционные ожидания населения остаются повышенными, базовая инфляция ускорилась.", page=2),
    chunk("steel-1", STEEL_DOC, "Цены на стальной прокат растут, экспорт металлургов поддерживает результаты."),
    chunk("steel-2", STEEL_DOC, "Ключевая ставка и стоимость кредитов металлургов не меняют прогноз."),
]


def scanned_pdf(path: Path, pages: int) -> None:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
        pixmap.set_rect(pixmap.irect, (200, 200, 200))
        page.insert_image(page.rect, pixmap=pixmap)
    document.save(str(path))


class FakeVision:
    def __init__(self, temp_dir: str, answer: dict) -> None:
        self.answer = answer
        self.requests: list[dict] = []
        settings = LLMSettings(api_key="k", state_db=Path(temp_dir) / "llm.sqlite3")
        self.client = LLMClient(
            settings=settings,
            client=SimpleNamespace(chat=SimpleNamespace(completions=self)),
            store=LLMStore(settings.state_db),
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(self.answer, ensure_ascii=False)),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )


OCR_ANSWER = {
    "blocks": [
        {"kind": "title", "text": "Ключевая ставка ЦБ РФ"},
        {
            "kind": "paragraph",
            "heading": "ЦБ РФ принял решение оставить ставку неизменной",
            "text": "Совет директоров взял паузу, вариант снижения ставки не рассматривался.",
        },
        {"kind": "chart", "heading": "Динамика ставки, %", "text": "Ставка стабильна с июля."},
        {"kind": "footer", "text": "Альфа-Банк. Все права защищены."},
    ]
}


class RegistryTests(unittest.TestCase):
    def test_matches_files_regardless_of_prefix_and_case(self) -> None:
        cases = {
            "55f3ee02-Бонд_Бриф_14092026.pdf": "bond_brief_2026_09_14",
            "c4c0b20e-alfa-7m26.pdf": "macro_7m26_2026_09_07",
            "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf": "policy_rate_2026_09_11",
        }
        for name, doc_id in cases.items():
            with self.subTest(name=name):
                self.assertEqual(match_document(Path(name)).doc_id, doc_id)

        self.assertIsNone(match_document(Path("random.pdf")))


class TokenizerTests(unittest.TestCase):
    def test_word_forms_share_stems(self) -> None:
        self.assertEqual(tokenize("ставки"), tokenize("ставку"))
        self.assertEqual(tokenize("инфляции"), tokenize("инфляция"))
        self.assertEqual(tokenize("ключевой"), tokenize("ключевая"))
        self.assertEqual(tokenize("и в на"), [])


class ChunkingTests(unittest.TestCase):
    def test_paragraphs_keep_heading_and_skip_footer(self) -> None:
        pages = [
            ExtractedPage(
                doc_id=RATE_DOC.doc_id,
                page=1,
                method="vision",
                blocks=[PageBlock.model_validate(block) for block in OCR_ANSWER["blocks"]],
            )
        ]

        chunks = chunk_document(RATE_DOC, pages)

        self.assertEqual([item.kind for item in chunks], ["text", "chart"])
        self.assertTrue(chunks[0].text.startswith("ЦБ РФ принял решение"))
        self.assertTrue(all("права защищены" not in item.text for item in chunks))
        self.assertEqual(chunks[0].chunk_id, f"{RATE_DOC.doc_id}-p1-01")

    def test_paragraph_glued_to_title_is_kept(self) -> None:
        first_paragraph = (
            "ЦБ РФ принял решение оставить ставку неизменной на уровне 14,0%. "
            "Совет директоров предметно обсуждал только вариант паузы, а вариант снижения ставки "
            "не рассматривался; пресс-релиз содержит корректировки, свидетельствующие об ужесточении позиции."
        )
        pages = [
            ExtractedPage(
                doc_id=RATE_DOC.doc_id,
                page=1,
                method="vision",
                blocks=[
                    PageBlock(kind="title", heading="Ключевая ставка ЦБ РФ", text=f"Ставка без изменения\n\n{first_paragraph}"),
                    PageBlock(kind="title", text="11 сентября 2026 г."),
                ],
            )
        ]

        chunks = chunk_document(RATE_DOC, pages)

        self.assertEqual(len(chunks), 1)
        self.assertIn("вариант снижения ставки", chunks[0].text)

    def test_chart_chunk_is_marked_approximate(self) -> None:
        pages = [
            ExtractedPage(
                doc_id=RATE_DOC.doc_id,
                page=2,
                method="vision",
                blocks=[PageBlock(kind="chart", heading="Доходность ОФЗ, %", text="Рост с июля до 16,2%")],
            )
        ]

        chunks = chunk_document(RATE_DOC, pages)

        self.assertEqual(chunks[0].kind, "chart")
        self.assertIn("значения приблизительные", chunks[0].text)

    def test_chart_axis_labels_are_dropped(self) -> None:
        axis_text = "17,5\n16,5\n15,5\n14.01.2026\n14.02.2026\nОФЗ 26254 (14 лет)\nКлючевая ставка\n3 500\n2 900"
        pages = [
            ExtractedPage(
                doc_id=RATE_DOC.doc_id,
                page=1,
                method="vision",
                blocks=[PageBlock(kind="chart", heading="Динамика доходности ОФЗ и Ключевая ставка, %", text=axis_text)],
            )
        ]

        text = chunk_document(RATE_DOC, pages)[0].text

        self.assertIn("ОФЗ 26254 (14 лет) Ключевая ставка", text)
        for label in ("17,5", "14.01.2026", "3 500"):
            self.assertNotIn(label, text)

    def test_long_paragraph_is_split_by_sentences(self) -> None:
        sentence = "Предложение о ставке и инфляции с достаточно длинным текстом. "
        pages = [
            ExtractedPage(
                doc_id=RATE_DOC.doc_id,
                page=1,
                method="manual",
                blocks=[PageBlock(kind="paragraph", text=sentence * 60)],
            )
        ]

        chunks = chunk_document(RATE_DOC, pages)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(item.text) <= 1400 for item in chunks))


class SearchTests(unittest.TestCase):
    INDEX = build_search_index(CHUNKS)

    def test_rate_query_finds_fresh_rate_material_first(self) -> None:
        results = search_chunks(
            self.INDEX,
            "ЦБ сохранил ключевую ставку",
            ["interest_rate"],
            as_of=date(2026, 9, 20),
        )

        self.assertEqual(results[0]["chunk_id"], "rate-1")
        steel = next(item for item in results if item["chunk_id"] == "steel-2")
        self.assertTrue(steel["stale"])

    def test_unrelated_query_returns_nothing(self) -> None:
        results = search_chunks(self.INDEX, "футбольный чемпионат", as_of=date(2026, 9, 20))

        self.assertEqual(results, [])

    def test_max_per_doc_limits_results(self) -> None:
        results = search_chunks(
            self.INDEX,
            "ключевая ставка инфляция",
            max_per_doc=1,
            min_matched_terms=1,
            as_of=date(2026, 9, 20),
        )

        doc_ids = [item["doc_id"] for item in results]
        self.assertEqual(len(doc_ids), len(set(doc_ids)))


class FlakyVision(FakeVision):
    """Fails the first N requests with a timeout, then answers normally."""

    def __init__(self, temp_dir: str, answer: dict, failures: int) -> None:
        super().__init__(temp_dir, answer)
        self.failures = failures

    def create(self, **kwargs):
        if self.failures:
            self.failures -= 1
            self.requests.append(kwargs)
            raise TimeoutError("Request timed out.")
        return super().create(**kwargs)


class APIConnectionError(Exception):
    """Same class name as openai's: the pipeline tells connection failures apart by it."""


class DroppingVision(FakeVision):
    """Answers the first N requests, then loses the connection."""

    def __init__(self, temp_dir: str, answer: dict, ok_requests: int) -> None:
        super().__init__(temp_dir, answer)
        self.ok_requests = ok_requests

    def create(self, **kwargs):
        if self.ok_requests <= 0:
            self.requests.append(kwargs)
            raise APIConnectionError("Connection error.")
        self.ok_requests -= 1
        return super().create(**kwargs)


class GatewayStopTests(unittest.TestCase):
    def test_stops_after_consecutive_connection_errors_and_keeps_progress(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_dir = root / "raw"
            bank_dir.mkdir()
            document = pymupdf.open()
            for shade in range(60, 240, 30):
                page = document.new_page()
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
                pixmap.set_rect(pixmap.irect, (shade, shade, shade))
                page.insert_image(page.rect, pixmap=pixmap)
            document.save(str(bank_dir / "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"))
            dropping = DroppingVision(temp_dir, OCR_ANSWER, ok_requests=1)

            with self.assertRaises(GatewayUnavailableError):
                build_bank_index(
                    bank_dirs=[bank_dir], manual_dir=root / "manual", processed_dir=root / "processed",
                    use_vision=True, llm=dropping.client,
                )
            saved = load_pages(root / "processed" / "bank_pages" / "policy_rate_2026_09_11.json")

        # 1 удачная страница, затем 3 обрыва подряд (без попыток по половинам) — стоп.
        self.assertEqual(len(dropping.requests), 4)
        self.assertEqual([page.page for page in saved], [1])

class OcrFallbackTests(unittest.TestCase):
    def test_unknown_kinds_and_extra_fields_are_tolerated(self) -> None:
        block = PageBlock.model_validate(
            {"kind": "subheading", "heading": "Раздел", "text": None, "bbox": [0, 0, 1, 1]}
        )
        figure = PageBlock.model_validate({"kind": "figure", "text": "Рис. 1"})
        other = PageBlock.model_validate({"kind": "sidebar", "text": "Врезка"})

        self.assertEqual((block.kind, block.text), ("heading", ""))
        self.assertEqual(figure.kind, "chart")
        self.assertEqual(other.kind, "paragraph")

    def test_dense_page_is_retried_as_two_halves(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "ALFA-consumption.pdf"
            scanned_pdf(pdf, pages=1)
            flaky = FlakyVision(temp_dir, OCR_ANSWER, failures=1)

            pages = extract_document_pages(
                DOCUMENTS_BY_ID["consumption_2026_08_05"],
                pdf,
                manual_dir=Path(temp_dir) / "manual",
                use_vision=True,
                llm=flaky.client,
            )

        hints = [request["messages"][1]["content"][0]["text"] for request in flaky.requests]
        self.assertEqual(len(flaky.requests), 3)
        self.assertIn("верхняя половина", hints[1])
        self.assertIn("нижняя половина", hints[2])
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0].blocks), 2 * len(OCR_ANSWER["blocks"]))


class PipelineTests(unittest.TestCase):
    def test_failed_page_is_reported_and_retried_alone(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_dir = root / "raw" / "news"
            bank_dir.mkdir(parents=True)
            pdf = bank_dir / "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"
            document = pymupdf.open()
            for shade in (120, 200):
                page = document.new_page()
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 40, 40), False)
                pixmap.set_rect(pixmap.irect, (shade, shade, shade))
                page.insert_image(page.rect, pixmap=pixmap)
            document.save(str(pdf))
            processed = root / "processed"
            # Целая страница и обе половины падают — страница попадает в отчёт об ошибках.
            flaky = FlakyVision(temp_dir, OCR_ANSWER, failures=2)

            first = build_bank_index(
                bank_dirs=[root / "raw"], manual_dir=root / "manual", processed_dir=processed,
                use_vision=True, llm=flaky.client,
            )
            second = build_bank_index(
                bank_dirs=[root / "raw"], manual_dir=root / "manual", processed_dir=processed,
                use_vision=True, llm=flaky.client,
            )

        self.assertEqual(len(first["errors"]), 1)
        self.assertIn("стр. 1", first["errors"][0])
        self.assertEqual(first["documents"][0]["pages"], 1)
        self.assertEqual(second["errors"], [])
        self.assertEqual(second["documents"][0]["new_pages"], 1)
        self.assertEqual(second["documents"][0]["pages"], 2)
        self.assertEqual(second["documents"][0]["source"], "cache+new")
        # Стр. 1 целиком и её верхняя половина, стр. 2, затем повтор только стр. 1.
        self.assertEqual(len(flaky.requests), 4)

    def test_scanned_pdf_uses_manual_text_then_vision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pdf = root / "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf"
            scanned_pdf(pdf, pages=2)
            manual = root / "manual" / RATE_DOC.doc_id / "p1.txt"
            manual.parent.mkdir(parents=True)
            manual.write_text("Первый абзац о ставке.\n\nВторой абзац.", encoding="utf-8")
            fake = FakeVision(temp_dir, OCR_ANSWER)

            pages = extract_document_pages(
                RATE_DOC, pdf, manual_dir=root / "manual", use_vision=True, llm=fake.client
            )

        self.assertEqual([page.method for page in pages], ["manual", "vision"])
        self.assertEqual(len(fake.requests), 1)
        image_part = fake.requests[0]["messages"][1]["content"][1]
        self.assertTrue(image_part["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(fake.requests[0]["timeout"], 240.0)
        self.assertEqual(fake.requests[0]["model"], "qwen/qwen3-vl-30b-a3b-instruct")

    def test_scanned_pdf_without_vision_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf = Path(temp_dir) / "ALFA-7M26.pdf"
            scanned_pdf(pdf, pages=1)

            pages = extract_document_pages(
                DOCUMENTS_BY_ID["macro_7m26_2026_09_07"],
                pdf,
                manual_dir=Path(temp_dir) / "manual",
                use_vision=False,
            )

        self.assertEqual(pages, [])

    def test_build_index_caches_pages_and_supports_search(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bank_dir = root / "bank"
            bank_dir.mkdir()
            scanned_pdf(bank_dir / "ALFA-Macro_Insights-Policy_Rate_11Sep.pdf", pages=1)
            (bank_dir / "unknown.pdf").write_bytes(b"%PDF-1.3")
            nested = bank_dir / "news"
            nested.mkdir()
            scanned_pdf(nested / "ALFA-7M26.pdf", pages=1)
            fake = FakeVision(temp_dir, OCR_ANSWER)
            processed = root / "processed"

            report = build_bank_index(
                bank_dirs=[bank_dir],
                manual_dir=root / "manual",
                processed_dir=processed,
                use_vision=True,
                llm=fake.client,
            )
            second = build_bank_index(
                bank_dirs=[bank_dir],
                manual_dir=root / "manual",
                processed_dir=processed,
                use_vision=True,
                llm=fake.client,
            )
            chunks = load_chunks(processed / "bank_index.json")
            results = search_bank_research(
                "решение по ставке",
                ["interest_rate"],
                index_path=processed / "bank_index.json",
                as_of=date(2026, 9, 20),
            )

        # Второй PDF лежит во вложенной папке news/ — тоже найден.
        self.assertEqual(report["chunks"], 4)
        self.assertEqual(report["unknown_files"], ["unknown.pdf"])
        self.assertIn("bond_brief_2026_09_14", report["missing_documents"])
        self.assertNotIn("macro_7m26_2026_09_07", report["missing_documents"])
        self.assertEqual({item["source"] for item in second["documents"]}, {"cache"})
        # Страницы-заглушки одинаковые: второе распознавание берётся из кеша LLM.
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(len(chunks), 4)
        self.assertEqual(results[0]["page"], 1)
        self.assertEqual(results[0]["doc_title"], RATE_DOC.title)


if __name__ == "__main__":
    unittest.main()


class TopicalFreshnessTests(unittest.TestCase):
    """Реальные провалы поиска из аудита: старый прогноз выше свежего, единственный документ о стали спрятан."""

    MACRO_OLD = DOCUMENTS_BY_ID["macro_1h26_2026_07_31"]
    CONSUMPTION = DOCUMENTS_BY_ID["consumption_2026_08_05"]
    INDEX = build_search_index(
        [
            chunk("old-forecast", MACRO_OLD, "Прогноз: ключевая ставка на конец года 13,5%, прогноз ставки снижен."),
            chunk("new-forecast", RATE_DOC, "Прогноз ключевой ставки на конец года — 14,0%."),
            chunk("steel", STEEL_DOC, "Производство стали в России и экспорт металлургов растут."),
            chunk("macro-industry", MACRO_OLD, "Производство в промышленности замедлилось, в России рост слабый."),
            chunk("consumption", CONSUMPTION, "Динамика потребления на пике, рост спроса охлаждается."),
        ]
    )

    def search(self, query: str) -> list[str]:
        return [item["doc_id"] for item in search_chunks(self.INDEX, query, as_of=date(2026, 10, 26))]

    def test_newer_document_on_topic_wins(self) -> None:
        self.assertEqual(self.search("прогноз ключевой ставки на конец года")[0], RATE_DOC.doc_id)

    def test_only_document_on_topic_is_not_penalized_for_age(self) -> None:
        results = search_chunks(self.INDEX, "российская металлургия производство стали", as_of=date(2026, 10, 26))
        self.assertEqual(results[0]["doc_id"], STEEL_DOC.doc_id)
        self.assertTrue(results[0]["stale"])  # возраст виден, но документ не спрятан

    def test_related_word_forms_match(self) -> None:
        # «потребительский» в запросе — «потребления» в документе.
        self.assertIn(self.CONSUMPTION.doc_id, self.search("потребительский спрос"))
