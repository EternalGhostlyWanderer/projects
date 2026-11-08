import unittest

from app.agents.verify import VerificationReport, Issue, final_status, verify_insight
from app.ai.evidence import bank_evidence, company_evidence, event_evidence
from app.ai.schemas import Insight
from app.modules.news.corroboration import corroborate, extract_figures, outlet_of
from app.schemas.event import EventSource, NewsEvent
from tests.test_agent import BANK_CHUNK, EVENT, draft, make_context

MERGED = {
    "event_id": "evt_merged",
    "title": "ЦБ сохранил ключевую ставку на уровне 14%",
    "url": "https://www.rbc.ru/a",
    "source": "РБК",
    "summary": "Инфляция замедлилась до 6,8%",
    "sources": [
        {"url": "https://www.rbc.ru/a", "source": "РБК", "title": "ЦБ сохранил ключевую ставку на уровне 14%"},
        {
            "url": "https://www.interfax.ru/b",
            "source": "Интерфакс",
            "title": "Банк России оставил ставку 14%",
            "summary": "Годовая инфляция 6,3%",
            "published_at": "2026-10-23T12:00:00+00:00",
        },
        {"url": "https://interfax.ru/c", "source": "Интерфакс", "title": "Перепечатка: ставка 14%"},
    ],
}


class CorroborationTests(unittest.TestCase):
    def test_nearest_measure_within_sentence(self) -> None:
        figures = {(item.measure, item.value) for item in extract_figures("Банк России оставил ставку 14%, инфляция 6,3%")}
        self.assertEqual(figures, {("ключевая ставка", "14"), ("инфляция", "6.3")})

    def test_confirmed_by_independent_outlets_and_conflicts(self) -> None:
        result = corroborate(MERGED)

        self.assertEqual(result["outlets"], ["interfax.ru", "rbc.ru"])  # перепечатка того же издания — одно издание
        self.assertEqual(result["confirmed"][0]["measure"], "ключевая ставка")
        self.assertEqual(result["conflicts"][0]["measure"], "инфляция")
        self.assertEqual(result["conflicts"][0]["numbers"], ["6.3", "6.8"])
        self.assertEqual(outlet_of("https://www.interfax.ru/x", "Интерфакс"), "interfax.ru")

    def test_each_publication_is_evidence_with_its_own_link(self) -> None:
        evidence = {item.id: item for item in event_evidence(MERGED)}

        self.assertEqual(evidence["event.source.1"].source_url, "https://www.interfax.ru/b")
        self.assertIn("6,3%", evidence["event.source.1"].text)
        self.assertNotIn("6,3%", evidence["event.main"].text)
        self.assertIn("подтверждено 2 изданиями", evidence["event.confirmed.1"].text)
        self.assertIn("расходятся", evidence["event.conflict.1"].text)

    def test_single_publication_adds_nothing(self) -> None:
        ids = {item.id for item in event_evidence(EVENT.model_dump(mode="json"))}
        self.assertEqual(ids, {"event.main"})

    def test_source_keeps_its_own_summary(self) -> None:
        event = NewsEvent(event_id="e", title="t", source="s", url="https://x.ru/1", summary="своё начало текста")
        self.assertEqual(EventSource.from_event(event, method="similarity").summary, "своё начало текста")


class DisputedAndStaleTests(unittest.TestCase):
    def report(self, data: dict, event: dict, chunks=(BANK_CHUNK,)) -> VerificationReport:
        insight = Insight(
            **data,
            insight_id="i",
            company_id="U_TEST",
            event_id=event["event_id"],
            evidence=[*event_evidence(event), *company_evidence(make_context()), *bank_evidence(chunks)],
            model="m",
            created_at="2026-10-25T00:00:00+00:00",
            quality_status="unverified",
        )
        return verify_insight(insight, event=event, missing_data=["financials.revenue_rub"])

    def test_disputed_number_as_fact_is_conflicting(self) -> None:
        data = draft()
        data["event_summary"].append(
            {"text": "Инфляция составила 6,3%", "basis": "FACT", "evidence_ids": ["event.source.1"], "confidence": "high"}
        )
        report = self.report(data, MERGED)
        self.assertIn("disputed_fact", {issue.code for issue in report.issues})
        self.assertEqual(final_status(report), "conflicting")

        data["event_summary"][-1]["text"] = "Источники расходятся: по данным Интерфакса инфляция 6,3%, по данным РБК 6,8%"
        self.assertNotIn("disputed_fact", {issue.code for issue in self.report(data, MERGED).issues})

    def test_bank_view_from_older_document_is_outdated(self) -> None:
        old = {**BANK_CHUNK, "chunk_id": "fi_strategy-p1-01", "doc_id": "fi_strategy", "doc_title": "Тактический взгляд", "doc_date": "2026-07-22"}
        data = draft(bank=True)
        data["bank_view"]["claims"][0]["evidence_ids"] = ["bank.fi_strategy-p1-01"]
        report = self.report(data, EVENT.model_dump(mode="json"), chunks=(old, BANK_CHUNK))

        self.assertIn("stale_bank_document", {issue.code for issue in report.issues})
        self.assertEqual(final_status(report), "outdated")

    def test_final_status_order(self) -> None:
        def status(*codes, severity="error"):
            issues = [Issue(code=code, severity=severity, message="m") for code in codes]
            return final_status(VerificationReport(passed=not any(i.severity == "error" for i in issues), issues=issues))

        self.assertEqual(status(), "verified")
        self.assertEqual(status("unsupported_number"), "partial")
        self.assertEqual(status("outdated_bank_forecast"), "outdated")
        self.assertEqual(status("disputed_fact", "outdated_bank_forecast"), "conflicting")


if __name__ == "__main__":
    unittest.main()
