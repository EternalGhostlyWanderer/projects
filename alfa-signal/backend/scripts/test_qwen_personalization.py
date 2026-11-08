"""Manual Qwen personalization check."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.analyzer import analyze_event
from app.research.search import search_bank_research

from app.modules.personalization.context import (
    build_personalization_context,
)

from app.modules.personalization.relevance import (
    assess_relevance,
)


COMPANY_ID = "U_195486"

EVENT = {
    "event_id": "TEST_RATE_001",
    "title": "Решение о сохранении ключевой ставки",
    "event_type": "interest_rate",
    "impact_channels": [
        "interest_rate",
        "deposit_yield",
        "leasing_cost",
    ],
    "description": (
        "Синтетический тестовый сценарий: "
        "регулятор сохранил ключевую ставку."
    ),
}


def main():
    context = build_personalization_context(COMPANY_ID)

    if context is None:
        print("Компания не найдена")
        return

    relevance = assess_relevance(
        context,
        EVENT,
    )

    print("Компания:", COMPANY_ID)
    print(
        "Найденные факторы:",
        [
            f["factor"] if isinstance(f, dict) else str(f)
            for f in relevance["matched_factors"]
        ],
    )

    bank_chunks = search_bank_research(
        EVENT["title"],
        EVENT["impact_channels"],
        top_k=3,
    )
    print(
        "Материалы банка:",
        [f"{chunk['doc_title']} · стр. {chunk['page']}" for chunk in bank_chunks]
        or "не найдены (индекс не собран или нет релевантных)",
    )

    print("\nЗапускаем анализ Qwen...\n")

    insight = analyze_event(
        context=context,
        event=EVENT,
        relevance=relevance,
        bank_chunks=bank_chunks,
    )

    print(
        insight.model_dump_json(indent=2)
    )


if __name__ == "__main__":
    main()