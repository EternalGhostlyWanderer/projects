import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from app.modules.news.extraction import (
    ExtractedEvent,
    check_facts_grounded,
    classify_by_keywords,
    extract_event,
)
from app.modules.news.normalization import normalize_news_item
from app.modules.news.sources.base import RawNewsItem
from app.modules.personalization.relevance import assess_relevance
from app.schemas.event import NewsEvent

RATE_NEWS = NewsEvent(
    event_id="evt_rate",
    title="Банк России сохранил ключевую ставку на уровне 14,0% годовых",
    source="test",
    url="https://example.com/rate",
    summary="Совет директоров принял решение 11 сентября 2026 года.",
)


def llm_answer(**overrides) -> str:
    answer = {
        "event_type": "monetary_policy",
        "is_business_relevant": True,
        "impact_channels": ["interest_rate"],
        "entities": {"organizations": ["Банк России"], "countries": ["Россия"]},
        "facts": ["Ключевая ставка сохранена на уровне 14% годовых"],
        "occurred_at": "2026-09-11",
        "confidence": "high",
    }
    answer.update(overrides)
    return json.dumps(answer, ensure_ascii=False)


class FakeLLM:
    def __init__(self, contents: list) -> None:
        self.contents = list(contents)
        self.requests: list[dict] = []
        self.temp_dir = tempfile.TemporaryDirectory()
        settings = LLMSettings(api_key="k", state_db=Path(self.temp_dir.name) / "llm.sqlite3")
        self.client = LLMClient(
            settings=settings,
            client=SimpleNamespace(chat=SimpleNamespace(completions=self)),
            store=LLMStore(settings.state_db),
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=None,
        )

    def close(self) -> None:
        self.temp_dir.cleanup()


class KeywordClassificationTests(unittest.TestCase):
    def test_rate_decision_maps_to_financing_channels(self) -> None:
        extracted = classify_by_keywords(RATE_NEWS)

        self.assertEqual(extracted.event_type, "monetary_policy")
        for channel in ("interest_rate", "deposit_yield", "leasing_cost"):
            self.assertIn(channel, extracted.impact_channels)

    def test_trade_news(self) -> None:
        event = RATE_NEWS.model_copy(
            update={"title": "Правительство повысило экспортные пошлины на металлы", "summary": None}
        )

        extracted = classify_by_keywords(event)

        self.assertIn("international_trade", extracted.impact_channels)
        self.assertNotIn("interest_rate", extracted.impact_channels)

    def test_industry_keywords_give_okved_sections(self) -> None:
        event = RATE_NEWS.model_copy(
            update={"title": "Потребительский спрос в рознице начал охлаждаться", "summary": None}
        )

        extracted = classify_by_keywords(event)

        self.assertIn("47", extracted.entities.okved_codes)
        self.assertIn("industry", extracted.impact_channels)

    def test_noise_has_no_channels(self) -> None:
        event = RATE_NEWS.model_copy(update={"title": "Футбольный клуб выиграл кубок", "summary": None})

        extracted = classify_by_keywords(event)

        self.assertEqual(extracted.impact_channels, [])
        self.assertFalse(extracted.is_business_relevant)


class LLMExtractionTests(unittest.TestCase):
    def test_llm_result_is_applied_and_rate_channels_expanded(self) -> None:
        fake = FakeLLM([llm_answer()])
        self.addCleanup(fake.close)

        event = extract_event(RATE_NEWS, llm=fake.client)

        self.assertEqual(event.extraction_method, "llm")
        self.assertEqual(event.event_type, "monetary_policy")
        self.assertIn("leasing_cost", event.impact_channels)
        self.assertEqual(event.entities.organizations, ["Банк России"])
        self.assertEqual(len(event.facts), 1)
        self.assertIn("<news>", fake.requests[0]["messages"][1]["content"])

    def test_invented_number_triggers_repair(self) -> None:
        fake = FakeLLM(
            [
                llm_answer(facts=["Ставка сохранена на уровне 15%"]),
                llm_answer(),
            ]
        )
        self.addCleanup(fake.close)

        event = extract_event(RATE_NEWS, llm=fake.client)

        self.assertEqual(len(fake.requests), 2)
        self.assertIn("15", fake.requests[1]["messages"][-1]["content"])
        self.assertEqual(event.facts, ["Ключевая ставка сохранена на уровне 14% годовых"])

    def test_falls_back_to_keywords_when_llm_fails(self) -> None:
        fake = FakeLLM([RuntimeError("gateway down")])
        self.addCleanup(fake.close)

        event = extract_event(RATE_NEWS, llm=fake.client)

        self.assertEqual(event.extraction_method, "keywords")
        self.assertIn("interest_rate", event.impact_channels)

    def test_irrelevant_news_gets_no_channels(self) -> None:
        fake = FakeLLM([llm_answer(is_business_relevant=False, event_type="other")])
        self.addCleanup(fake.close)

        event = extract_event(RATE_NEWS, llm=fake.client)

        self.assertEqual(event.impact_channels, [])

    def test_grounding_accepts_number_formats_from_text(self) -> None:
        extracted = ExtractedEvent.model_validate_json(
            llm_answer(facts=["Решение принято 11 сентября 2026 года, ставка 14,0%"])
        )

        errors = check_facts_grounded(extracted, RATE_NEWS.title + " " + RATE_NEWS.summary)

        self.assertEqual(errors, [])

    def test_bad_okved_codes_are_rejected(self) -> None:
        extracted = ExtractedEvent.model_validate_json(
            llm_answer(facts=[], entities={"okved_codes": ["41.20", "строительство"]})
        )

        errors = check_facts_grounded(extracted, RATE_NEWS.title)

        self.assertTrue(errors)


class NormalizationTests(unittest.TestCase):
    def test_strips_html_from_rss_summary(self) -> None:
        event = normalize_news_item(
            RawNewsItem(
                title="Новость",
                url="https://example.com/a",
                source="rss",
                summary="<p>Ставка&nbsp;<b>сохранена</b></p>",
            )
        )

        self.assertEqual(event.summary, "Ставка сохранена")


class EntityRelevanceTests(unittest.TestCase):
    CONTEXT = {
        "company_id": "U_TEST",
        "company_profile": {
            "industry": {"code": "41.20", "name": "Строительство"},
            "location": {"region": "Москва"},
            "risk_indicators": {"fts_country": "АРМЕНИЯ"},
        },
        "sensitivity_factors": [{"factor": "leasing_cost"}],
    }

    def test_matches_industry_region_and_country(self) -> None:
        event = {
            "event_id": "e1",
            "impact_channels": ["leasing_cost"],
            "entities": {
                "okved_codes": ["41", "43"],
                "regions": ["Москва и Московская область"],
                "countries": ["Армения"],
            },
        }

        result = assess_relevance(self.CONTEXT, event)

        self.assertEqual(
            result["matched_factors"],
            ["leasing_cost", "industry", "region", "trade_country"],
        )
        self.assertEqual(result["matched_entities"]["industry"], "41.20")

    def test_matches_one_of_several_fts_countries(self) -> None:
        context = {
            "company_id": "U_TEST",
            "company_profile": {"risk_indicators": {"fts_country": "КИРГИЗИЯ, КАЗАХСТАН"}},
            "sensitivity_factors": [],
        }
        event = {"event_id": "e3", "impact_channels": [], "entities": {"countries": ["Казахстан"]}}

        result = assess_relevance(context, event)

        self.assertEqual(result["matched_factors"], ["trade_country"])

    def test_unrelated_entities_do_not_match(self) -> None:
        event = {
            "event_id": "e2",
            "impact_channels": [],
            "entities": {"okved_codes": ["01"], "regions": ["Казань"], "countries": ["Китай"]},
        }

        result = assess_relevance(self.CONTEXT, event)

        self.assertEqual(result["match_count"], 0)


if __name__ == "__main__":
    unittest.main()
