"""Seed a fresh Docker database without calling an LLM.

Если есть снимок демо (DEMO_SNAPSHOT_FILE, по умолчанию data/demo/demo_snapshot.json, его делает
scripts/export_demo.py) — загружаются события и готовые разборы: демо работает и без ключа LLM.
Иначе — синтетические новости (DEMO_EVENTS_FILE). Поверх — пул заготовленных демонстрационных новостей
(DEMO_EXTRA_NEWS_FILE, по умолчанию data/demo/extra_news.json): ленте всех демо-компаний есть что показать.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store  # noqa: E402
from app.db.snapshot import import_snapshot, load_snapshot  # noqa: E402
from app.modules.news.service import load_events_file  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _path(variable: str, default: str) -> Path:
    path = Path(os.getenv(variable, default))
    return path if path.is_absolute() else PROJECT_ROOT / path


def load_extra_news(store) -> None:
    extra = _path("DEMO_EXTRA_NEWS_FILE", "data/demo/extra_news.json")
    if extra.is_file():
        events = load_events_file(store, extra, use_llm=False)
        print(f"Seeded {len(events)} prepared demo news.")


def main() -> int:
    if os.getenv("SEED_SYNTHETIC_DATA", "1").strip() != "1":
        print("Demo seed is disabled.")
        return 0

    store = get_store()
    if store.count_events() > 0:
        print("Event store already contains data; demo seed skipped.")
        return 0

    snapshot_path = Path(os.getenv("DEMO_SNAPSHOT_FILE", "data/demo/demo_snapshot.json"))
    snapshot_path = snapshot_path if snapshot_path.is_absolute() else PROJECT_ROOT / snapshot_path
    if snapshot_path.is_file():
        counts = import_snapshot(store, load_snapshot(snapshot_path))
        print(f"Seeded demo snapshot {snapshot_path.name}: {counts}")
        load_extra_news(store)
        return 0

    configured_path = Path(os.getenv("DEMO_EVENTS_FILE", "data/synthetic/news.json"))
    source_path = configured_path if configured_path.is_absolute() else PROJECT_ROOT / configured_path
    if not source_path.is_file():
        print(f"Demo seed file not found: {source_path}", file=sys.stderr)
        return 1

    events = load_events_file(store, source_path, use_llm=False)
    print(f"Seeded {len(events)} synthetic events.")
    load_extra_news(store)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
