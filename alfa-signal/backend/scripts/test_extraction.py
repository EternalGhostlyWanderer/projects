"""Extract events from an RSS feed or a pasted news text; optionally match them to a company.

Примеры:
    python backend/scripts/test_extraction.py --rss https://www.cbr.ru/rss/eventrss --limit 5
    python backend/scripts/test_extraction.py --rss URL --limit 3 --llm
    python backend/scripts/test_extraction.py --title "ЦБ сохранил ключевую ставку" --text "..." --llm
    python backend/scripts/test_extraction.py --rss URL --company U_195486

Без --llm используются только ключевые слова (бесплатно). С --llm — один запрос на новость,
повторный запуск по тем же новостям берётся из кеша.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.news.deduplication import deduplicate_news  # noqa: E402
from app.modules.news.extraction import extract_events  # noqa: E402
from app.modules.news.normalization import normalize_news_item  # noqa: E402
from app.modules.news.sources.base import RawNewsItem  # noqa: E402
from app.modules.news.sources.rss import RSSNewsSource  # noqa: E402
from app.schemas.event import NewsEvent  # noqa: E402


def load_events(args: argparse.Namespace) -> list[NewsEvent]:
    if args.rss:
        raw_items = RSSNewsSource(name="RSS", url=args.rss).fetch()
    else:
        raw_items = [
            RawNewsItem(
                title=args.title,
                url=args.url,
                source="manual",
                summary=args.text,
            )
        ]

    events = [event for item in raw_items if (event := normalize_news_item(item))]
    return deduplicate_news(events)[: args.limit]


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка извлечения событий из новостей.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--rss", help="URL RSS/Atom-ленты")
    source.add_argument("--title", help="Заголовок новости для ручной проверки")
    parser.add_argument("--text", default="", help="Текст новости (вместе с --title)")
    parser.add_argument("--url", default="https://example.com/manual-news", help="URL для --title")
    parser.add_argument("--limit", type=int, default=5, help="Сколько новостей обработать")
    parser.add_argument("--llm", action="store_true", help="Извлекать через LLM (платно)")
    parser.add_argument("--company", help="SYNTHETIC_U компании для проверки релевантности")
    args = parser.parse_args()

    events = load_events(args)
    if not events:
        print("Новостей не получено: проверьте URL ленты или доступ к сети.")
        return 1

    extracted = extract_events(events, use_llm=args.llm)

    context = None
    if args.company:
        from app.modules.personalization.context import build_personalization_context
        from app.modules.personalization.relevance import assess_relevance

        context = build_personalization_context(args.company)
        if context is None:
            print(f"Компания {args.company} не найдена")
            return 1

    for event in extracted:
        print("=" * 70)
        print(event.title)
        print(f"метод: {event.extraction_method} | тип: {event.event_type}")
        print("каналы:", ", ".join(event.impact_channels) or "—")
        entities = {key: value for key, value in event.entities.model_dump().items() if value}
        if entities:
            print("сущности:", json.dumps(entities, ensure_ascii=False))
        for fact in event.facts:
            print("  •", fact)
        if context is not None:
            relevance = assess_relevance(context, event.model_dump(mode="json"))
            print("совпадения с компанией:", relevance["matched_factors"] or "нет")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
