import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.agents.tools import AgentState, NoArgs, _bank_forecasts
from app.agents.verify import verify_insight
from app.modules.news import service
from app.modules.personalization.scoring import freshness, score_event
from app.research.forecasts import describe, extract_forecasts, forecast_table, relevant_forecasts
from app.research.pages import ExtractedPage, PageBlock
from app.research.registry import DOCUMENTS_BY_ID
from app.research.search import _recency
from app.schemas.event import NewsEvent
from tests import test_agent
from tests.test_agent import EVENT, FORECASTS, draft
from tests.test_scoring import RATE, context

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


def table_page(doc_id: str, page: int, rate_2026: str, usd_2027: str) -> ExtractedPage:
    return ExtractedPage(
        doc_id=doc_id,
        page=page,
        method="manual",
        blocks=[
            PageBlock(
                kind="table",
                heading="Основные макроэкономические показатели",
                text=(
                    "Показатель | 2025 | 2026П | 2027П\n"
                    f"Ставка, конец года, % | 16,0% | {rate_2026} | 12,0%\n"
                    "Инфляция, % дек./дек. | 5,6% | 7,5% | 5,5%\n"
                    f"Курс, конец года, руб./$ | 78,2 | 87,2 | {usd_2027}"
                ),
            )
        ],
    )


class FreshnessTests(unittest.TestCase):
    def test_freshness_decays_but_has_a_floor(self) -> None:
        self.assertEqual(freshness(NOW - timedelta(hours=5), NOW)["factor"], 1.0)
        week = freshness(NOW - timedelta(days=8), NOW)["factor"]
        self.assertAlmostEqual(week, 0.5, places=2)
        self.assertEqual(freshness(NOW - timedelta(days=90), NOW)["factor"], 0.3)
        self.assertEqual(freshness(None, NOW)["factor"], 1.0)

    def test_rank_prefers_fresh_event_but_score_stays_explainable(self) -> None:
        fresh = score_event(context(), {**RATE, "published_at": datetime.now(timezone.utc).isoformat()})
        old = score_event(context(), {**RATE, "published_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()})

        self.assertEqual(fresh["score"], old["score"])
        self.assertGreater(fresh["rank"], old["rank"])

    def test_rss_cutoff_skips_old_but_keeps_undated(self) -> None:
        def item(days: int | None) -> NewsEvent:
            published = None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
            return NewsEvent(event_id=f"e{days}", title="t", source="s", url="https://x.ru/a", published_at=published)

        self.assertFalse(service._too_old(item(2), 7))
        self.assertTrue(service._too_old(item(30), 7))
        self.assertFalse(service._too_old(item(None), 7))
        self.assertFalse(service._too_old(item(30), 0))
        with patch.dict("os.environ", {"NEWS_MAX_AGE_DAYS": ""}):
            self.assertEqual(service.max_news_age_days(), 7)

    def test_bank_search_prefers_recent_documents(self) -> None:
        today = date(2026, 10, 25)
        self.assertEqual(_recency("2026-10-01", today), 1.0)
        self.assertLess(_recency("2026-07-01", today), _recency("2026-09-11", today))
        self.assertGreaterEqual(_recency("2021-04-15", today), 0.85)


class ForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        old = extract_forecasts(DOCUMENTS_BY_ID["macro_1h26_2026_07_31"], [table_page("macro_1h26_2026_07_31", 4, "13,5%", "95,0")])
        new = extract_forecasts(DOCUMENTS_BY_ID["policy_rate_2026_09_11"], [table_page("policy_rate_2026_09_11", 2, "14,0%", "93,0")])
        self.table = forecast_table([*old, *new])

    def test_only_forecast_columns_are_extracted(self) -> None:
        periods = {entry["period"] for entry in self.table.values()}
        self.assertEqual(periods, {"2026", "2027"})

    def test_latest_document_wins_and_revision_is_marked(self) -> None:
        rate = self.table["key_rate_end:2026"]
        self.assertEqual(rate["latest"]["value"], 14.0)
        self.assertEqual(rate["previous"]["value"], 13.5)
        self.assertTrue(rate["revised"])
        self.assertIn("пересмотрен: ранее 13,5", describe(rate))
        self.assertFalse(self.table["inflation_dec:2026"]["revised"])
        self.assertTrue(self.table["usd_rub_end:2027"]["revised"])

    def test_forecasts_by_event_channels(self) -> None:
        rate_only = relevant_forecasts(self.table, ["interest_rate"])
        self.assertEqual({entry["indicator"] for entry in rate_only}, {"key_rate_end"})
        self.assertEqual(relevant_forecasts(self.table, ["regulation"]), [])

    def test_agent_tool_adds_current_forecast_as_bank_evidence(self) -> None:
        state = AgentState(company_id="U_TEST", event=EVENT)
        with patch("app.agents.tools.bank_forecasts", return_value=self.table):
            result = _bank_forecasts(state, NoArgs())

        self.assertIn("13.5 → 14", result.summary)
        chunk = next(item for item in state.bank_chunks if "key_rate_end" in item["chunk_id"])
        self.assertTrue(chunk["chunk_id"].startswith("policy_rate_2026_09_11-p2-"))
        self.assertIn("Прогноз пересмотрен", chunk["text"])


class OutdatedForecastVerifyTests(unittest.TestCase):
    insight = test_agent.VerifyTests.insight

    def codes_with(self, risk_text: str) -> set[str]:
        report = verify_insight(
            self.insight(draft(bank=True, risk_text=risk_text)),
            event=EVENT.model_dump(mode="json"),
            missing_data=["financials.revenue_rub"],
            forecasts=FORECASTS.values(),
        )
        return {issue.code for issue in report.issues}

    def test_old_forecast_presented_as_current_is_an_error(self) -> None:
        self.assertIn("outdated_bank_forecast", self.codes_with("Банк ждёт ключевую ставку 13,5% на конец года"))

    def test_cbr_forecast_range_and_other_year_are_not_bank_forecast(self) -> None:
        # Реальный случай: прогноз ЦБ принимался за устаревший прогноз Альфа-Банка.
        for text in (
            "Базовый сценарий ЦБ РФ предполагает среднюю ключевую ставку 12,5–13,5% в 2027 году",
            "Банк России ожидает ключевую ставку 13,5% на конец года",
            "Ставка на конец 2027 года — 13,5%",
        ):
            self.assertNotIn("outdated_bank_forecast", self.codes_with(text), text)
        self.assertIn(
            "outdated_bank_forecast",
            self.codes_with("Альфа-Банк, в отличие от ЦБ, ждёт ключевую ставку 13,5% на конец 2026 года"),
        )

    def test_mentioning_revision_is_fine(self) -> None:
        codes = self.codes_with("Банк пересмотрел прогноз ключевой ставки: ранее 13,5%, теперь 14%")
        self.assertNotIn("outdated_bank_forecast", codes)


if __name__ == "__main__":
    unittest.main()
