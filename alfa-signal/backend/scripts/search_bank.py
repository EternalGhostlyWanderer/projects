"""Search the Alfa-Bank research index (no API calls).

Примеры:
    python backend/scripts/search_bank.py "ключевая ставка сохранена" --channels interest_rate
    python backend/scripts/search_bank.py "цены на сталь" --top 3
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.search import search_bank_research  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Поиск по аналитике Альфа-Банка.")
    parser.add_argument("query")
    parser.add_argument("--channels", nargs="*", default=[], help="Каналы влияния события")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    results = search_bank_research(args.query, args.channels, top_k=args.top)
    if not results:
        print("Релевантных материалов банка не найдено (или индекс не собран: build_bank_index.py).")
        return 0

    for item in results:
        stale = " · УСТАРЕЛ" if item["stale"] else ""
        print("=" * 70)
        print(f"[{item['score']}] {item['doc_title']} · {item['doc_date']} · стр. {item['page']}{stale}")
        print(f"id: {item['chunk_id']}")
        print(item["text"][:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
