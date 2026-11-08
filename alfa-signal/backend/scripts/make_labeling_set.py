"""Build a labeling set «event × company» for human relevance labels (no LLM).

Примеры (из корня репозитория, после сбора реальных новостей):
    python backend/scripts/make_labeling_set.py --auto 8 --events 30 --annotators anna maria alina
    python backend/scripts/make_labeling_set.py --companies U_9250 U_57706 --events 20 --annotators anna

Что получается в backend/var/labeling/ (в git не попадает):
- labeling_<разметчик>.csv — таблица для Excel: компания, событие, пустые столбцы label и reason;
- labeling_key.json — оценка системы по каждой паре (разметчикам не показывать: иначе она подскажет ответ);
- LABELING_GUIDE.md — инструкция и шкала 0–3.
Пары делятся между разметчиками поровну; --overlap пар достаются всем — по ним считается согласие людей.
Заполненные таблицы — в ту же папку, затем: python backend/scripts/score_labels.py
"""
import argparse
import csv
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.store import get_store  # noqa: E402
from app.modules.companies.links import clean_revenue, group_summary, okved_class  # noqa: E402
from app.modules.companies.position import describe_position  # noqa: E402
from app.modules.companies.repository import get_all_companies  # noqa: E402
from app.modules.personalization.context import build_personalization_context  # noqa: E402
from app.modules.personalization.relevance import assess_relevance  # noqa: E402

OUT_DIR = Path(__file__).resolve().parents[1] / "var" / "labeling"
PRODUCTS = {"rko": "РКО", "gar": "гарантии", "loa": "кредиты", "lea": "лизинг", "dep": "депозиты", "zpp": "зарплатный проект"}
COLUMNS = ["pair_id", "company_id", "company", "event_id", "event", "summary", "source", "published_at", "url", "label", "reason"]

GUIDE = """# Разметка: важно ли событие этой компании

Вы — менеджер банка, который хорошо знает клиента. Для каждой строки прочитайте описание компании (столбец
`company`) и новость (`event`, `summary`) и поставьте в столбец `label` одну цифру:

| Оценка | Значит | Пример |
|---|---|---|
| **3** | прямо меняет условия бизнеса компании, руководителю нужно знать сегодня | ставка ЦБ — компании с кредитами; пошлина на её экспорт |
| **2** | заметно влияет через один канал, полезно знать | курс юаня — компании, которая торгует с Китаем, но не по контрактам в юанях |
| **1** | косвенно, фоном | общая инфляция — компании без кредитов |
| **0** | не касается | футбол; новость другой отрасли без связи с компанией |

В `reason` — по желанию, 3–10 слов: почему («кредиты, ставка», «нет связи», «другая отрасль»).

Правила:
- оценивайте по тому, что написано о компании, не додумывайте; «нет данных» — это не «нет связи», но и не связь;
- не ищите новость в интернете — достаточно заголовка и начала текста;
- не смотрите в `labeling_key.json` и в ленту сервиса — это подскажет ответ;
- примерно 1–2 минуты на строку; сомневаетесь между двумя оценками — ставьте меньшую.

Готовую таблицу сохраните в той же папке с тем же именем (CSV, разделитель «;») и запустите
`python backend/scripts/score_labels.py`.
"""


def describe_company(context: dict) -> str:
    profile = context["company_profile"]
    industry = profile.get("industry") or {}
    parts = [f"{industry.get('name') or 'отрасль не указана'} (ОКВЭД {industry.get('code') or '—'})"]
    region = (profile.get("location") or {}).get("region")
    if region:
        parts.append(region)
    products = [label for key, label in PRODUCTS.items() if (profile.get("products") or {}).get(key)]
    parts.append("продукты банка: " + (", ".join(products) or "нет"))
    fts = (profile.get("risk_indicators") or {}).get("fts_country")
    parts.append(f"внешняя торговля (ФТС): {fts}" if fts else "внешней торговли по ФТС нет")
    revenue = (profile.get("financials") or {}).get("revenue_rub")
    parts.append(f"выручка {revenue / 1e9:.1f} млрд руб." if revenue else "выручка неизвестна")
    group = profile.get("group") or {}
    if group.get("company_count", 1) > 1:
        parts.append(f"группа из {group['company_count']} компаний")
    position = describe_position(profile.get("industry_position") or {})
    if position:
        parts.append(position)
    counterparties = (context.get("counterparty_industries") or {}).get("industries") or []
    if counterparties:
        top = ", ".join(f"{item.get('example_name') or item['okved_class']} {item['share']:.0%}" for item in counterparties[:3])
        parts.append(f"контрагенты по платежам: {top}")
    user = context.get("user_data") or {}
    if user.get("interests"):
        parts.append("важные темы (со слов клиента): " + ", ".join(user["interests"]))
    return "; ".join(parts)


def auto_companies(count: int) -> list[str]:
    """Разные компании: крупный бизнес, разные отрасли, кредит / депозит / лизинг / ВЭД."""
    candidates = []
    for company in get_all_companies():
        if company.client_type != "CLIENT" or clean_revenue(company.revenue) is None:
            continue
        group = group_summary(company)
        if not group.get("large_business"):
            continue
        candidates.append(company)
    candidates.sort(key=lambda company: clean_revenue(company.revenue) or 0, reverse=True)
    chosen, classes, traits = [], set(), set()
    for company in candidates:
        code = okved_class(company.main_okved_code)
        trait = (
            company.product_loa_mark == 1,
            company.product_dep_mark == 1,
            company.product_lea_mark == 1,
            bool(company.fts_country),
        )
        if code in classes and trait in traits:
            continue
        chosen.append(company.id)
        classes.add(code)
        traits.add(trait)
        if len(chosen) >= count:
            break
    return chosen


def pick_events(store, count: int) -> list:
    """Свежие события, поровну по типам: ставка, курс, торговля, отрасли, регулирование и прочее."""
    by_type: dict[str, list] = defaultdict(list)
    for event in store.list_events(limit=500):
        by_type[event.event_type or "other"].append(event)
    picked = []
    while len(picked) < count and any(by_type.values()):
        for event_type in sorted(by_type):
            if by_type[event_type] and len(picked) < count:
                picked.append(by_type[event_type].pop(0))
    return picked


def main() -> int:
    parser = argparse.ArgumentParser(description="Таблица для ручной разметки релевантности.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--companies", nargs="+", help="SYNTHETIC_U компаний")
    source.add_argument("--auto", type=int, help="Подобрать столько разных компаний автоматически")
    parser.add_argument("--events", type=int, default=30)
    parser.add_argument("--annotators", nargs="+", default=["annotator"])
    parser.add_argument("--overlap", type=int, default=40, help="Сколько пар размечают все (для согласия)")
    parser.add_argument("--seed", type=int, default=26)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    store = get_store()
    company_ids = args.companies or auto_companies(args.auto)
    events = pick_events(store, args.events)
    if not events:
        print("В хранилище нет событий: сначала соберите новости (load_events.py)")
        return 1

    pairs, key = [], {}
    for company_id in company_ids:
        context = build_personalization_context(company_id, store.get_user_data(company_id))
        if context is None:
            print(f"Компания {company_id} не найдена — пропускаю")
            continue
        company_text = describe_company(context)
        for event in events:
            pair_id = f"{company_id}:{event.event_id}"
            relevance = assess_relevance(context, event.model_dump(mode="json"))
            key[pair_id] = {
                "score": relevance["score"],
                "rank": relevance.get("rank", relevance["score"]),
                "level": relevance.get("level"),
                "explanation": relevance.get("explanation"),
            }
            pairs.append(
                {
                    "pair_id": pair_id,
                    "company_id": company_id,
                    "company": company_text,
                    "event_id": event.event_id,
                    "event": event.title,
                    "summary": (event.summary or "")[:400],
                    "source": event.source,
                    "published_at": event.published_at.isoformat() if event.published_at else "",
                    "url": str(event.url),
                    "label": "",
                    "reason": "",
                }
            )

    rng = random.Random(args.seed)
    shuffled = pairs[:]
    rng.shuffle(shuffled)
    overlap = shuffled[: min(args.overlap, len(shuffled))] if len(args.annotators) > 1 else []
    rest = shuffled[len(overlap):]
    assignment = {name: list(overlap) for name in args.annotators}
    for index, pair in enumerate(rest):
        assignment[args.annotators[index % len(args.annotators)]].append(pair)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, items in assignment.items():
        # Внутри файла — по компаниям: так разметчик держит в голове одну компанию.
        items.sort(key=lambda pair: (pair["company_id"], rng.random()))
        path = args.out / f"labeling_{name}.csv"
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS, delimiter=";")
            writer.writeheader()
            writer.writerows(items)
        print(f"{path}: пар {len(items)}")
    (args.out / "labeling_key.json").write_text(
        json.dumps({"companies": company_ids, "overlap": [pair["pair_id"] for pair in overlap], "pairs": key}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (args.out / "LABELING_GUIDE.md").write_text(GUIDE, encoding="utf-8")
    print(f"Компаний: {len(company_ids)}, событий: {len(events)}, пар: {len(pairs)}, общих для всех: {len(overlap)}")
    print(f"Инструкция: {args.out / 'LABELING_GUIDE.md'}; ключ системы (не показывать): {args.out / 'labeling_key.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
