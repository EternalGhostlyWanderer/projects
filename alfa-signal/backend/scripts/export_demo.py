"""Export ready analyses for the demo, so it works without an LLM key (no LLM calls).

Пример (после того как разборы посчитаны вживую):
    python backend/scripts/export_demo.py --companies U_9250 U_57706 --out data/demo/demo_snapshot.json
Подготовить демо целиком (нужен ключ LLM; платно — по 2–6 запросов на разбор, спросит подтверждение):
    python backend/scripts/export_demo.py --companies SYN_001 SYN_002 SYN_003 --analyze-top 5 --role-views

Выгружает события, сохранённые разборы, журналы агента, ролевые блоки (cfo, accountant, owner) и
сведения от пользователя. Загрузка — scripts/seed_demo.py (в Docker — при первом запуске).
В снимке — новости и выводы по обезличенным компаниям; CSV организаторов в него не попадают.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.snapshot import export_snapshot  # noqa: E402
from app.db.store import get_store  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def analyze_top(store, company_ids: list[str], top: int, confirmed: bool):
    """Верхние события ленты без разбора (балл ≥ порога предварительного анализа) — разобрать агентом."""
    from app.agents.orchestrator import run_agent
    from app.api.v1.feed import _ranked_items
    from app.modules.news.scheduler import SchedulerConfig

    min_score = SchedulerConfig.from_env().min_score
    plan = []
    for company_id in company_ids:
        items = _ranked_items(store, company_id, only_relevant=True, include_hidden=False)
        todo = [item["event"] for item in items if item["insight"] is None and item["relevance"]["score"] >= min_score]
        plan.extend((company_id, event) for event in todo[:top])
    print(f"К разбору: {len(plan)} (верхние {top} событий с баллом от {min_score} у каждой компании)")
    if plan and not confirmed and input("Платно, 2–6 запросов на разбор. Запустить? yes: ").strip().lower() != "yes":
        print("Отменено")
        return None
    done = 0
    for company_id, event in plan:
        result = run_agent(company_id, event, user_data=store.get_user_data(company_id))
        if result.insight is None:
            store.save_trace(result.trace)
            print(f"  {company_id}: не получилось — {event.title[:70]}")
            continue
        store.save_analysis(result.insight, result.trace)
        done += 1
        print(f"  {company_id}: {result.insight.quality_status:<10} {event.title[:70]}")
    print(f"Разобрано: {done} из {len(plan)}")
    return done


def main() -> int:
    parser = argparse.ArgumentParser(description="Снимок демо: готовые разборы без ключа LLM.")
    parser.add_argument("--companies", nargs="+", required=True)
    parser.add_argument("--roles", nargs="*", default=["cfo", "accountant", "owner"])
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "data" / "demo" / "demo_snapshot.json")
    parser.add_argument("--allow-real", action="store_true", help="Разрешить реальные компании в data/demo")
    parser.add_argument("--role-views", action="store_true", help="Подготовить недостающие ролевые блоки перед выгрузкой")
    parser.add_argument(
        "--analyze-top",
        type=int,
        default=0,
        help="Разобрать агентом столько верхних событий ленты каждой компании (как предварительный анализ)",
    )
    parser.add_argument("--yes", action="store_true", help="Не спрашивать подтверждение платных разборов")
    args = parser.parse_args()

    # data/demo попадает в git: туда — только синтетические компании. Выводы по реальным компаниям
    # организаторов (выручка, продукты в доказательствах) храним локально.
    real = [company for company in args.companies if not company.startswith("SYN_")]
    demo_dir = (PROJECT_ROOT / "data" / "demo").resolve()
    if real and args.out.resolve().is_relative_to(demo_dir) and not args.allow_real:
        print(
            f"Компании {', '.join(real)} — из данных организаторов, а data/demo попадает в git. "
            "Укажите --out вне data/demo (например, backend/var/demo_snapshot.json) или --allow-real."
        )
        return 1

    store = get_store()
    if args.analyze_top > 0 and analyze_top(store, args.companies, args.analyze_top, args.yes) is None:
        return 1
    if args.role_views:
        # Ролевые блоки для каждой роли: с ключом LLM — моделью, без ключа — по правилам (role_view.py).
        from app.agents.role_view import build_role_view

        made = 0
        for company_id in args.companies:
            for insight in store.list_insights(company_id, limit=200):
                for role in args.roles:
                    if store.get_role_view(insight.insight_id, role):
                        continue
                    view = build_role_view(insight, role)
                    store.save_role_view(insight.insight_id, role, view.model_dump(mode="json"))
                    made += 1
        print(f"Ролевых блоков подготовлено: {made}")
    snapshot = export_snapshot(store, args.companies, roles=args.roles)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        f"{args.out}: событий {len(snapshot['events'])}, разборов {len(snapshot['insights'])}, "
        f"журналов {len(snapshot['traces'])}, ролевых блоков {len(snapshot['role_views'])}"
    )
    if not snapshot["insights"]:
        print("Разборов нет: сначала разберите события вживую (кнопкой или demo_scenario.py)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
