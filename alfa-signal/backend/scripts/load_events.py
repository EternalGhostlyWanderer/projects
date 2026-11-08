"""Load news into the app storage: from a JSON file or from RSS feeds.

Примеры:
    python backend/scripts/load_events.py --file data/synthetic/news.json          # бесплатно: ключевые слова
    python backend/scripts/load_events.py --file data/synthetic/news.json --llm    # извлечение через LLM
    python backend/scripts/load_events.py --rss https://www.cbr.ru/rss/eventrss --limit 20
    python backend/scripts/load_events.py --official cbr moex                       # ставка и курсы ЦБ, новости Мосбиржи
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store  # noqa: E402
from app.modules.news.service import (  # noqa: E402
    OFFICIAL_SOURCES,
    collect_rss,
    load_events_file,
    max_news_age_days,
    official_sources,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Загрузка новостей в хранилище приложения.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path, help="JSON-список новостей {title, text, url, source, published_at}")
    source.add_argument("--rss", nargs="+", help="Одна или несколько RSS-лент")
    source.add_argument(
        "--official", nargs="+", choices=sorted(OFFICIAL_SOURCES), help="Официальные источники с открытым API"
    )
    parser.add_argument("--limit", type=int, default=30, help="Сколько новостей брать из каждой ленты")
    parser.add_argument("--llm", action="store_true", help="Извлекать события через LLM (платно)")
    args = parser.parse_args()

    store = get_store()
    merged: list = []
    if args.file:
        events = load_events_file(store, args.file, use_llm=args.llm)
    else:
        result = collect_rss(
            store,
            args.rss or [],
            use_llm=args.llm,
            limit_per_source=args.limit,
            extra_sources=official_sources(args.official or [], args.limit),
        )
        events, merged = result["added"], result["merged"]
        print(
            f"Уже собранных ссылок пропущено: {result['skipped_known_urls']}; "
            f"старше {max_news_age_days()} дн. (NEWS_MAX_AGE_DAYS): {result['skipped_old']}; "
            f"не про бизнес (без каналов влияния, NEWS_KEEP_OFFTOPIC=1 — сохранять): {result['skipped_offtopic']}; "
            f"кликбейт-заголовки: {result['skipped_clickbait']}"
        )

    for event in events:
        channels = ", ".join(event.impact_channels) or "—"
        sources = f"  · источников: {len(event.sources)}" if len(event.sources) > 1 else ""
        print(f"{event.event_id}  [{event.extraction_method}] {event.title[:70]}  → {channels}{sources}")
    for event in merged:
        print(f"  склеено с событием {event.event_id}: «{event.title[:60]}», источников {len(event.sources)}")
    print(
        f"\nЗагружено: {len(events)}, склеено с уже известными: {len(merged)}; "
        f"всего событий в хранилище: {store.count_events()}, склеенных публикаций: {store.count_event_aliases()}"
    )
    if not args.file:
        print("\nИсточники:")
        for item in result["sources"]:
            error = f"  ошибка: {item['last_error'][:90]}" if item.get("last_error") else ""
            print(
                f"  {item['status']:<9} {item['name'][:40]:<40} записей {item['last_items']:>3}, "
                f"новых {item['last_added']:>3}, склеено {item['last_merged']:>2}, "
                f"{item['last_duration_ms']:>5} мс{error}"
            )
    print(f"База: {store.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
