"""Remove already stored low-value events: clickbait headlines and publications from given domains (no LLM).

Фильтр кликбейта (app/modules/news/quality.py) работает при сборе; события, собранные раньше, убирает этот скрипт.
Примеры:
    python backend/scripts/clean_events.py                    # показать, что будет удалено
    python backend/scripts/clean_events.py --apply            # удалить кликбейт
    python backend/scripts/clean_events.py --domain lenta.ru --apply   # и всё из Ленты.ру
Удалённые ссылки запоминаются как «не про бизнес»: при следующем сборе они не вернутся.
"""
import argparse
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store  # noqa: E402
from app.modules.news.quality import is_clickbait  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Очистка сохранённых событий от кликбейта и ненужных источников.")
    parser.add_argument("--domain", nargs="*", default=[], help="Удалить все публикации этих доменов")
    parser.add_argument("--apply", action="store_true", help="Без флага — только показать")
    args = parser.parse_args()

    store = get_store()
    domains = {item.lower().removeprefix("www.") for item in args.domain}
    found = []
    for event in store.list_events(limit=5000):
        host = urlsplit(str(event.url)).netloc.lower().removeprefix("www.")
        reason = "кликбейт" if is_clickbait(event.title) else ("источник" if host in domains else None)
        if reason:
            found.append((reason, event))
    for reason, event in found:
        print(f"  [{reason}] {event.title[:90]}  ({event.source})")
    if not args.apply:
        print(f"\nНайдено {len(found)}; удалить — добавьте --apply")
        return 0
    for _, event in found:
        store.mark_offtopic(event.event_id, event.title)
        store.delete_event(event.event_id)
    print(f"\nУдалено {len(found)}; осталось событий: {store.count_events()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
