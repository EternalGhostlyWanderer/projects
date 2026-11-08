"""Score the feed against human labels and measure agreement between annotators (no LLM).

Пример (после заполнения таблиц make_labeling_set.py):
    python backend/scripts/score_labels.py
    python backend/scripts/score_labels.py --dir backend/var/labeling --relevant 2

Считает:
- согласие разметчиков на общих парах: точное совпадение, совпадение ±1, взвешенная каппа Коэна;
- качество ленты: Precision@5, Recall@5, nDCG@5 по компаниям (порядок — как в ленте: балл × свежесть);
- порог ленты: сколько важных событий (оценка ≥ 2) лента скрыла бы и сколько неважных показала —
  при текущем пороге и при других (подбор порога);
- потолок P@5: если у компании меньше 5 важных событий, P@5 не может быть 1 — считается и доля от достижимого;
- худшие ошибки: высокий балл при оценке 0 и низкий балл при оценке 3 — по ним настраиваются веса.
Отчёт: <папка>/labeling_report.json.
"""
import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modules.personalization.scoring import MIN_FEED_SCORE  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "var" / "labeling"
K = 5


def read_labels(folder: Path) -> dict[str, dict[str, int]]:
    """pair_id → {разметчик: оценка 0–3}; пустые и некорректные оценки пропускаются."""
    labels: dict[str, dict[str, int]] = defaultdict(dict)
    rows: dict[str, dict] = {}
    for path in sorted(folder.glob("labeling_*.csv")):
        annotator = path.stem.removeprefix("labeling_")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(2048)
            handle.seek(0)
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
            for row in csv.DictReader(handle, delimiter=delimiter):
                value = (row.get("label") or "").strip()
                if value in {"0", "1", "2", "3"}:
                    labels[row["pair_id"]][annotator] = int(value)
                    rows[row["pair_id"]] = row
    return labels, rows


def weighted_kappa(pairs: list[tuple[int, int]], categories: int = 4) -> float:
    """Квадратично взвешенная каппа Коэна для двух разметчиков."""
    if not pairs:
        return float("nan")
    n = len(pairs)
    observed = [[0.0] * categories for _ in range(categories)]
    for a, b in pairs:
        observed[a][b] += 1
    row = [sum(observed[i]) for i in range(categories)]
    col = [sum(observed[i][j] for i in range(categories)) for j in range(categories)]
    weights = [[(i - j) ** 2 / (categories - 1) ** 2 for j in range(categories)] for i in range(categories)]
    disagree_observed = sum(weights[i][j] * observed[i][j] for i in range(categories) for j in range(categories)) / n
    disagree_expected = sum(weights[i][j] * row[i] * col[j] for i in range(categories) for j in range(categories)) / n**2
    return 1.0 if disagree_expected == 0 else round(1 - disagree_observed / disagree_expected, 3)


def agreement(labels: dict[str, dict[str, int]]) -> dict:
    shared = {pair: votes for pair, votes in labels.items() if len(votes) >= 2}
    exact = [len(set(votes.values())) == 1 for votes in shared.values()]
    close = [max(votes.values()) - min(votes.values()) <= 1 for votes in shared.values()]
    annotators = sorted({name for votes in shared.values() for name in votes})
    kappas = {}
    for left, right in combinations(annotators, 2):
        both = [(votes[left], votes[right]) for votes in shared.values() if left in votes and right in votes]
        if both:
            kappas[f"{left}–{right}"] = weighted_kappa(both)
    return {
        "shared_pairs": len(shared),
        "exact": round(sum(exact) / len(exact), 3) if exact else None,
        "within_one": round(sum(close) / len(close), 3) if close else None,
        "weighted_kappa": kappas,
    }


def dcg(gains: list[float]) -> float:
    return sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))


def main() -> int:
    parser = argparse.ArgumentParser(description="Метрики ленты по ручной разметке.")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    parser.add_argument("--relevant", type=int, default=2, help="С какой оценки событие считается важным")
    args = parser.parse_args()

    key_path = args.dir / "labeling_key.json"
    if not key_path.exists():
        print(f"Нет {key_path}: сначала make_labeling_set.py")
        return 1
    key = json.loads(key_path.read_text(encoding="utf-8"))["pairs"]
    labels, rows = read_labels(args.dir)
    if not labels:
        print("В таблицах нет оценок 0–3 в столбце label")
        return 1

    final = {pair: round(statistics.median(votes.values())) for pair, votes in labels.items() if pair in key}
    by_company: dict[str, list[tuple[str, float, int, int]]] = defaultdict(list)
    for pair, label in final.items():
        company_id = pair.split(":", 1)[0]
        by_company[company_id].append((pair, key[pair]["rank"], key[pair]["score"], label))

    per_company = {}
    for company_id, items in sorted(by_company.items()):
        ranked = sorted(items, key=lambda item: item[1], reverse=True)
        relevant = sum(1 for item in items if item[3] >= args.relevant)
        top = ranked[:K]
        hits = sum(1 for item in top if item[3] >= args.relevant)
        ideal = dcg(sorted((item[3] for item in items), reverse=True)[:K])
        per_company[company_id] = {
            "pairs": len(items),
            "relevant": relevant,
            "precision_at_5": round(hits / min(K, len(top)), 3) if top else None,
            "precision_ceiling": round(min(K, relevant) / min(K, len(top)), 3) if top else None,
            "recall_at_5": round(hits / min(K, relevant), 3) if relevant else None,
            "ndcg_at_5": round(dcg([item[3] for item in top]) / ideal, 3) if ideal else None,
        }

    shown = [(key[pair]["score"] >= MIN_FEED_SCORE, label >= args.relevant) for pair, label in final.items()]
    threshold = {
        "important_hidden": sum(1 for is_shown, important in shown if important and not is_shown),
        "unimportant_shown": sum(1 for is_shown, important in shown if is_shown and not important),
        "important_total": sum(1 for _, important in shown if important),
        "shown_total": sum(1 for is_shown, _ in shown if is_shown),
    }
    sweep = []
    for cutoff in range(5, 65, 5):
        sweep.append(
            {
                "threshold": cutoff,
                "important_hidden": sum(1 for pair, label in final.items() if label >= args.relevant and key[pair]["score"] < cutoff),
                "unimportant_shown": sum(1 for pair, label in final.items() if label < args.relevant and key[pair]["score"] >= cutoff),
                "shown_total": sum(1 for pair in final if key[pair]["score"] >= cutoff),
            }
        )
    errors = sorted(
        (
            {
                "pair_id": pair,
                "label": label,
                "score": key[pair]["score"],
                "event": rows[pair]["event"],
                "explanation": key[pair]["explanation"],
                "reason": rows[pair].get("reason"),
            }
            for pair, label in final.items()
            if (label == 0 and key[pair]["score"] >= 30) or (label == 3 and key[pair]["score"] < MIN_FEED_SCORE)
        ),
        key=lambda item: abs(item["score"] / 33 - item["label"]),
        reverse=True,
    )

    def mean(metric: str):
        values = [item[metric] for item in per_company.values() if item[metric] is not None]
        return round(statistics.mean(values), 3) if values else None

    report = {
        "labeled_pairs": len(final),
        "agreement": agreement(labels),
        "feed": {
            "mean_precision_at_5": mean("precision_at_5"),
            "mean_recall_at_5": mean("recall_at_5"),
            "mean_ndcg_at_5": mean("ndcg_at_5"),
            "mean_precision_ceiling": mean("precision_ceiling"),
            # nDCG без компаний, где важных событий нет: там «идеальный» порядок — из одних оценок 0–1.
            "mean_ndcg_at_5_with_relevant": (
                round(statistics.mean(values), 3)
                if (values := [item["ndcg_at_5"] for item in per_company.values() if item["relevant"] and item["ndcg_at_5"] is not None])
                else None
            ),
            "companies": per_company,
        },
        "feed_threshold": threshold,
        "threshold_sweep": sweep,
        "worst_errors": errors[:20],
    }
    (args.dir / "labeling_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Размечено пар: {len(final)}")
    print(f"Согласие разметчиков: {report['agreement']}")
    print(
        f"Лента: P@5 {report['feed']['mean_precision_at_5']}, R@5 {report['feed']['mean_recall_at_5']}, "
        f"nDCG@5 {report['feed']['mean_ndcg_at_5']}"
    )
    ceiling = report["feed"]["mean_precision_ceiling"]
    if ceiling:
        print(
            f"  P@5 от достижимого: {report['feed']['mean_precision_at_5'] / ceiling:.0%} (потолок {ceiling}: у компаний мало важных событий); "
            f"nDCG@5 по компаниям с важными событиями: {report['feed']['mean_ndcg_at_5_with_relevant']}"
        )
    for company_id, item in per_company.items():
        print(f"  {company_id}: {item}")
    print(
        f"Порог ленты ({MIN_FEED_SCORE}): скрыто важных {threshold['important_hidden']} из {threshold['important_total']}, "
        f"показано неважных {threshold['unimportant_shown']} из {threshold['shown_total']}"
    )
    print("Подбор порога (порог: скрыто важных / показано неважных / показано всего):")
    for item in sweep:
        print(f"  {item['threshold']:>3}: {item['important_hidden']:>3} / {item['unimportant_shown']:>3} / {item['shown_total']:>3}")
    for item in errors[:10]:
        print(f"  ошибка: оценка {item['label']}, балл {item['score']}: {item['event'][:70]} — {item['explanation'][:90]}")
    print(f"\nОтчёт: {args.dir / 'labeling_report.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
