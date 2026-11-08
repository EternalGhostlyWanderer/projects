"""Исправления по прогону на реальных новостях 26 октября (docs/reports/09-real-news-fixes.md)."""
import unittest
from datetime import datetime, timedelta, timezone

from app.agents.chat import ChatAnswer
from app.ai.analyzer import check_draft_evidence, repair_draft
from app.ai.evidence import company_evidence, event_evidence
from app.ai.schemas import InsightDraft
from app.api.v1.feed import group_stories
from app.schemas.event import NewsEvent
from tests.test_agent import EVENT, draft
from tests.test_chat import make_context

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def evidence():
    return [*event_evidence(EVENT.model_dump(mode="json")), *company_evidence(make_context())]


class RepairDraftTests(unittest.TestCase):
    def test_unknown_ids_and_wrong_sources_are_repaired_not_rejected(self) -> None:
        data = draft()
        data["risks"][0]["evidence_ids"].append("bank.not-there")
        data["primary_effect"] = {**data["primary_effect"], "basis": "BANK_ANALYSIS"}
        value = InsightDraft.model_validate(data)
        pool = evidence()

        self.assertTrue(check_draft_evidence(value, pool))
        repaired = repair_draft(value, pool)

        self.assertEqual(check_draft_evidence(repaired, pool), [])
        self.assertEqual(repaired.primary_effect.basis, "AI_INFERENCE")
        self.assertNotIn("bank.not-there", repaired.risks[0].evidence_ids)

    def test_bank_view_without_bank_materials_becomes_not_found(self) -> None:
        value = repair_draft(InsightDraft.model_validate(draft(bank=True)), evidence())
        self.assertEqual(value.bank_view.status, "not_found")
        self.assertEqual(value.bank_view.claims, [])


def item(title: str, event_type: str, score: int, hours_ago: int = 1, countries=()) -> dict:
    event = NewsEvent(
        event_id=title[:10],
        title=title,
        source="s",
        url=f"https://example.com/{abs(hash(title))}",
        published_at=NOW - timedelta(hours=hours_ago),
        event_type=event_type,
        entities={"countries": list(countries)},
    )
    return {"event": event, "relevance": {"score": score}}


class StoryGroupingTests(unittest.TestCase):
    def test_rate_decision_and_comments_are_one_story(self) -> None:
        items = [
            item("Банк России принял решение сохранить ключевую ставку на уровне 14,00%", "monetary_policy", 35),
            item("Набиуллина: ЦБ предметно обсудил сохранение ключевой ставки", "monetary_policy", 28, 3),
            item("ЦБ сопроводил сообщение о ключевой ставке изображением кота", "monetary_policy", 28, 4),
            item("Недельная инфляция в России замедлилась до 0,05%", "inflation", 20),
            item("Центробанк Турции снизил ключевую ставку до 36%", "monetary_policy", 16, countries=["ТУРЦИЯ"]),
            item("ЦБ снизил ключевую ставку до 13,5%", "monetary_policy", 35, hours_ago=24 * 10),
        ]
        grouped = group_stories(items)

        self.assertEqual(len(grouped), 4)
        self.assertEqual(grouped[0]["related_count"], 2)
        self.assertTrue(grouped[0]["event"].title.startswith("Банк России принял решение"))
        self.assertEqual([related["score"] for related in grouped[0]["related"]], [28, 28])
        # Чужой центробанк и заседание другой недели — отдельные карточки.
        self.assertEqual(sum(1 for lead in grouped if lead["related_count"] == 0), 3)


class ChatLabelTests(unittest.TestCase):
    def test_definition_is_not_a_fact_and_jargon_is_removed(self) -> None:
        answer = ChatAnswer.model_validate(
            {
                "answer": [
                    {
                        "text": "Санкции — это ограничительные меры, вводимые государствами",
                        "basis": "FACT",
                        "evidence_ids": ["event.main"],
                        "confidence": "high",
                    },
                    {"text": "Курс кроны в массиве evidence отсутствует", "basis": "AI_INFERENCE", "evidence_ids": [], "confidence": "medium"},
                    {"text": "Официальный курс евро — 90,2429 руб.", "basis": "FACT", "evidence_ids": ["market.fx.EUR"], "confidence": "high"},
                ]
            }
        )
        self.assertEqual(answer.answer[0].basis, "AI_INFERENCE")
        self.assertEqual(answer.answer[1].text, "Курс кроны в доступных данных отсутствует")
        self.assertEqual(answer.answer[2].basis, "FACT")


if __name__ == "__main__":
    unittest.main()


class BankViewRepairTests(unittest.TestCase):
    """HTTP 500 от 26.10: тезис банка со ссылкой на новость превращался в AI_INFERENCE внутри bank_view."""

    def test_bank_claim_citing_news_is_removed_not_relabeled(self) -> None:
        from app.ai.evidence import bank_evidence
        from tests.test_agent import BANK_CHUNK

        value = InsightDraft.model_validate(draft(bank=True))
        value.bank_view.claims[0].evidence_ids = ["event.main"]
        pool = [*evidence(), *bank_evidence([BANK_CHUNK])]

        repaired = repair_draft(value, pool)
        self.assertEqual(repaired.bank_view.status, "not_found")
        InsightDraft.model_validate(repaired.model_dump())  # контракт соблюдён

    def test_store_skips_broken_saved_insight(self) -> None:
        import tempfile
        from pathlib import Path

        from app.db.store import AppStore
        from tests.test_chat import make_insight

        with tempfile.TemporaryDirectory() as folder:
            store = AppStore(Path(folder) / "app.sqlite3")
            good = make_insight()
            broken = good.model_copy(update={"insight_id": "broken"}, deep=True)
            broken.bank_view.status = "found"  # found без тезисов — нарушение контракта
            store._write(
                "INSERT INTO insights VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("broken", good.company_id, "e2", "agent-1", 50, good.created_at, broken.model_dump_json()),
            )
            store._write(
                "INSERT INTO insights VALUES (?, ?, ?, ?, ?, ?, ?)",
                (good.insight_id, good.company_id, good.event_id, "agent-1", 40, good.created_at, good.model_dump_json()),
            )
            with self.assertLogs("app.db.store", "WARNING"):
                listed = store.list_insights(good.company_id)
            self.assertEqual([item.insight_id for item in listed], [good.insight_id])
            self.assertIsNone(store.get_insight("broken"))


class NoiseTests(unittest.TestCase):
    def test_verb_sprosit_is_not_demand(self) -> None:
        from app.modules.news.extraction import extract_event

        def channels(title: str) -> list[str]:
            return extract_event(NewsEvent(event_id="x", title=title, source="s", url="https://a.ru/x"), use_llm=False).impact_channels

        self.assertEqual(channels("На ЕГЭ не спросят того, чему не учили в школе"), [])
        self.assertIn("revenue", channels("Потребительский спрос начал охлаждаться"))

    def test_trade_news_without_country_weighs_less(self) -> None:
        from app.modules.personalization.scoring import score_event
        from tests.test_scoring import context, event

        with_country = score_event(context(), event("trade", ["international_trade"], countries=["ТУРЦИЯ"]))["score"]
        without = score_event(context(), event("trade", ["international_trade"]))["score"]
        self.assertLess(without, with_country)
        self.assertLess(without, 10)  # без страны и других признаков — ниже порога ленты


class EventSummaryRelabelTests(unittest.TestCase):
    """HTTP 500 от 26.10, второй случай: «может» в «Что произошло» перемечалось в AI_INFERENCE."""

    def test_event_summary_stays_fact_and_insight_stays_valid(self) -> None:
        from app.agents.verify import relabel_inferred_facts
        from app.ai.schemas import Insight
        from tests.test_chat import make_insight

        insight = make_insight()
        insight.event_summary[0].text = "ЦБ сохранил ставку, что может замедлить кредитование"
        fixed, changed = relabel_inferred_facts(insight)
        self.assertEqual(fixed.event_summary[0].basis, "FACT")
        Insight.model_validate(fixed.model_dump(mode="json"))

    def test_store_refuses_to_save_broken_insight(self) -> None:
        import tempfile
        from pathlib import Path

        from pydantic import ValidationError

        from app.agents.trace import AgentTrace
        from app.db.store import AppStore
        from tests.test_chat import make_insight

        broken = make_insight()
        broken.event_summary[0].basis = "AI_INFERENCE"
        trace = AgentTrace(trace_id="t", insight_id="i1", company_id="U_TEST", event_id="e", started_at="x", goal="g")
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValidationError):
                AppStore(Path(folder) / "app.sqlite3").save_analysis(broken, trace)
