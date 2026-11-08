"""Quality of merging publications about the same event (no API calls unless --llm).

Примеры:
    python backend/scripts/check_dedup.py                    # контрольные пары
    python backend/scripts/check_dedup.py --store            # + сколько публикаций склеено в хранилище

Метрики по контрольным парам: точность склейки (склеено верно / всего склеено) — ошибочная
склейка прячет событие; полнота (найдено дублей / всего дублей).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store  # noqa: E402
from app.modules.news.clustering import conflicts, find_duplicate, similarity  # noqa: E402
from app.schemas.event import NewsEvent  # noqa: E402

PAIRS = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "dedup_pairs.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверка склейки дублей новостей.")
    parser.add_argument("--pairs", type=Path, default=PAIRS)
    parser.add_argument("--llm", action="store_true", help="Спорные пары проверять через LLM (платно)")
    parser.add_argument("--store", action="store_true", help="Показать склейку в хранилище событий")
    args = parser.parse_args()

    pairs = json.loads(args.pairs.read_text(encoding="utf-8"))["pairs"]
    true_merge = false_merge = missed = 0
    for index, pair in enumerate(pairs):
        first, second = (
            NewsEvent(event_id=f"{side}{index}", url=f"https://{pair[side]['source']}/{side}{index}", **pair[side])
            for side in ("a", "b")
        )
        decision = find_duplicate(second, [first], use_llm=args.llm)
        merged = decision.event is not None
        ok = merged == pair["same"]
        true_merge += merged and pair["same"]
        false_merge += merged and not pair["same"]
        missed += pair["same"] and not merged
        blocked = "; ".join(conflicts(first, second)) or "—"
        print(
            f"{'OK ' if ok else 'ОШИБКА'} ожидалось {'склеить' if pair['same'] else 'раздельно':<9} "
            f"близость {similarity(first, second):.2f}  способ {decision.method or '—':<10} "
            f"запрет: {blocked[:60]:<60} {pair['note']}"
        )

    duplicates = sum(1 for pair in pairs if pair["same"])
    precision = true_merge / (true_merge + false_merge) if true_merge + false_merge else 1.0
    recall = true_merge / duplicates if duplicates else 1.0
    print(
        f"\nПар: {len(pairs)}; точность склейки {precision:.2f} (ошибочных склеек {false_merge}); "
        f"полнота {recall:.2f} (пропущено дублей {missed})"
    )

    if args.store:
        store = get_store()
        events, aliases = store.count_events(), store.count_event_aliases()
        print(
            f"\nХранилище {store.path}: публикаций {events + aliases}, событий после склейки {events}, "
            f"склеено дублей {aliases}"
        )
    return 0 if false_merge == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
