"""Control questions for the Alfa-Bank research search (no LLM).

Пример (после build_bank_index.py):
    python backend/scripts/eval_bank_search.py
    python backend/scripts/eval_bank_search.py --as-of 2026-10-26

Для каждого вопроса — какой документ должен найтись (data/synthetic/bank_search_questions.json):
«первым» — первый результат из списка допустимых; «в топ-3» — нужный документ среди первых трёх
(поле top3, по умолчанию — любой из expected). Запускать при каждом изменении поиска.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.research.index import INDEX_PATH  # noqa: E402
from app.research.search import search_bank_research  # noqa: E402

QUESTIONS = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "bank_search_questions.json"


def evaluate(search, questions: list[dict]) -> dict:
    rows, first_ok, top3_ok = [], 0, 0
    for item in questions:
        found = [result["doc_id"] for result in search(item["query"])]
        first = bool(found) and found[0] in item["expected"]
        needed = item.get("top3") or item["expected"]
        in_top3 = any(doc_id in needed for doc_id in found[:3])
        first_ok += first
        top3_ok += in_top3
        rows.append({"query": item["query"], "found": found[:3], "first": first, "top3": in_top3, "note": item.get("note")})
    total = len(questions) or 1
    return {"first_accuracy": round(first_ok / total, 3), "top3_recall": round(top3_ok / total, 3), "questions": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Контрольные вопросы к поиску по аналитике банка.")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None, help="Дата «сегодня» для свежести")
    args = parser.parse_args()
    if not INDEX_PATH.exists():
        print(f"Нет индекса {INDEX_PATH}: сначала python backend/scripts/build_bank_index.py")
        return 1
    questions = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    report = evaluate(lambda query: search_bank_research(query, top_k=3, as_of=args.as_of), questions)
    for row in report["questions"]:
        mark = "OK " if row["first"] else ("~  " if row["top3"] else "НЕТ")
        print(f"{mark} {row['query'][:50]:<50} → {', '.join(row['found'])}")
    print(f"\nПервым — нужный документ: {report['first_accuracy']:.0%}; в топ-3: {report['top3_recall']:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
