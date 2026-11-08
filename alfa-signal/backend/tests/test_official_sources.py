import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from app.agents.orchestrator import PlannedStep, _enforce_policy
from app.agents.tools import AgentState, NoArgs, ToolError, _official_rates
from app.ai.evidence import market_evidence
from app.db.store import AppStore
from app.modules.news import service
from app.modules.news.normalization import normalize_news_item
from app.modules.news.sources import cbr
from app.modules.news.sources.moex import is_service_news, parse_sitenews
from tests.test_agent import EVENT
from tests.test_api import keywords_only

KEY_RATE_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <KeyRateResponse xmlns="http://web.cbr.ru/">
      <KeyRateResult>
        <diffgr:diffgram xmlns:diffgr="urn:schemas-microsoft-com:xml-diffgram-v1">
          <KeyRate xmlns="">
            <KR diffgr:id="KR1"><DT>2026-10-27T00:00:00+03:00</DT><Rate>13.50</Rate></KR>
            <KR diffgr:id="KR2"><DT>2026-10-24T00:00:00+03:00</DT><Rate>14.00</Rate></KR>
            <KR diffgr:id="KR3"><DT>2026-09-15T00:00:00+03:00</DT><Rate>14.00</Rate></KR>
            <KR diffgr:id="KR4"><DT>2026-09-12T00:00:00+03:00</DT><Rate>14.50</Rate></KR>
          </KeyRate>
        </diffgr:diffgram>
      </KeyRateResult>
    </KeyRateResponse>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")


def xml_daily(day: str, cny: str, usd: str) -> bytes:
    return f"""<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="{day}" name="Foreign Currency Market">
  <Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal><Name>Юань</Name><Value>{cny}</Value></Valute>
  <Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>Доллар США</Name><Value>{usd}</Value></Valute>
  <Valute ID="R01820"><NumCode>392</NumCode><CharCode>JPY</CharCode><Nominal>100</Nominal><Name>Иен</Name><Value>55,1000</Value></Valute>
</ValCurs>""".encode("windows-1251")


LATEST = cbr.parse_fx(xml_daily("27.10.2026", "11,6200", "81,5000"))
PREVIOUS = cbr.parse_fx(xml_daily("24.10.2026", "11,4500", "81,2000"))
RATES = cbr.parse_key_rates(KEY_RATE_RESPONSE)


class CBRParsingTests(unittest.TestCase):
    def test_key_rate_series_is_sorted(self) -> None:
        self.assertEqual(RATES[0], (date(2026, 9, 12), 14.5))
        self.assertEqual(RATES[-1], (date(2026, 10, 27), 13.5))

    def test_fx_per_unit_and_only_known_currencies(self) -> None:
        day, rates = LATEST
        self.assertEqual(day, date(2026, 10, 27))
        self.assertEqual(rates, {"CNY": 11.62, "USD": 81.5})

    def test_broken_payload_is_a_data_error(self) -> None:
        with self.assertRaises(cbr.CBRDataError):
            cbr.parse_fx(b"<html>maintenance</html>")
        with self.assertRaises(cbr.CBRDataError):
            cbr.parse_key_rates(b"not xml")


class CBREventTests(unittest.TestCase):
    def test_each_rate_change_becomes_an_event_with_exact_numbers(self) -> None:
        items = cbr.key_rate_items(RATES)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[-1].title, "Банк России снизил ключевую ставку до 13,50% годовых")
        self.assertIn("до этого 14,00%", items[-1].summary)
        self.assertNotEqual(normalize_news_item(items[0]).event_id, normalize_news_item(items[1]).event_id)

    def test_fx_event_only_above_threshold(self) -> None:
        items = cbr.fx_items(LATEST, PREVIOUS, threshold=1.0)

        # Юань +1,5% — событие; доллар +0,4% — нет.
        self.assertEqual(len(items), 1)
        self.assertIn("курс юаня вырос на 1,5%", items[0].title)
        self.assertIn("11,4500", items[0].summary)

    def test_events_get_channels_from_keywords(self) -> None:
        items = cbr.key_rate_items(RATES) + cbr.fx_items(LATEST, PREVIOUS, threshold=1.0)
        events = [keywords_only(normalize_news_item(item)) for item in items]

        self.assertIn("interest_rate", events[0].impact_channels)
        self.assertEqual(events[0].event_type, "monetary_policy")
        self.assertIn("currency", events[-1].impact_channels)
        self.assertIn("КИТАЙ", events[-1].entities.countries)


class MarketSnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        cbr.clear_snapshot_cache()
        self.addCleanup(cbr.clear_snapshot_cache)

    def snapshot(self) -> dict:
        return cbr.market_snapshot(key_rates=lambda: RATES, fx_pair=lambda: (LATEST, PREVIOUS))

    def test_current_rate_and_since_date(self) -> None:
        snapshot = self.snapshot()
        self.assertEqual(snapshot["key_rate"], {"value": 13.5, "since": "2026-10-27", "as_of": "2026-10-27"})
        self.assertEqual(snapshot["fx"]["CNY"]["previous"], 11.45)

    def test_facts_become_fact_evidence_with_source(self) -> None:
        evidence = market_evidence(cbr.snapshot_facts(self.snapshot()))

        rate = next(item for item in evidence if item.id == "market.key_rate")
        self.assertEqual(rate.type, "FACT")
        self.assertIn("13,50%", rate.text)
        self.assertTrue(rate.source_url.startswith("https://www.cbr.ru/"))
        self.assertIn("курс вырос на 1,5%", next(item for item in evidence if item.id == "market.fx.CNY").text)

    def test_fall_is_written_in_words(self) -> None:
        snapshot = cbr.market_snapshot(key_rates=lambda: RATES, fx_pair=lambda: (PREVIOUS, LATEST))
        text = next(fact["text"] for fact in cbr.snapshot_facts(snapshot) if fact["id"] == "market.fx.CNY")
        self.assertIn("курс снизился на 1,5%", text)
        self.assertNotIn("-", text.split(";")[1])


class OfficialRatesToolTests(unittest.TestCase):
    def test_tool_puts_facts_into_state(self) -> None:
        state = AgentState(company_id="U_TEST", event=EVENT)
        snapshot = cbr.market_snapshot(key_rates=lambda: RATES, fx_pair=lambda: (LATEST, PREVIOUS))
        cbr.clear_snapshot_cache()
        with patch.dict("os.environ", {"CBR_DATA_ENABLED": "1"}), patch.object(cbr, "market_snapshot", return_value=snapshot):
            result = _official_rates(state, NoArgs())

        self.assertIn("market.key_rate", result.evidence_ids)
        self.assertEqual(len(state.market_facts), 3)

    def test_unavailable_service_is_a_tool_error(self) -> None:
        state = AgentState(company_id="U_TEST", event=EVENT)
        with patch.dict("os.environ", {"CBR_DATA_ENABLED": "1"}), patch.object(
            cbr, "market_snapshot", side_effect=cbr.CBRDataError("timeout")
        ):
            with self.assertRaises(ToolError):
                _official_rates(state, NoArgs())

    def test_policy_adds_tool_for_rate_events_when_enabled(self) -> None:
        steps = [PlannedStep(tool="get_company_profile", reason="r"), PlannedStep(tool="assess_relevance", reason="r")]
        with patch.dict("os.environ", {"CBR_DATA_ENABLED": "1"}):
            enabled, added = _enforce_policy(steps, EVENT)
        with patch.dict("os.environ", {"CBR_DATA_ENABLED": "0"}):
            disabled, _ = _enforce_policy(steps, EVENT)

        self.assertIn("get_official_rates", [step.tool for step in enabled])
        self.assertIn("get_official_rates", added)
        self.assertNotIn("get_official_rates", [step.tool for step in disabled])


class MOEXTests(unittest.TestCase):
    def test_sitenews_columns_and_rows(self) -> None:
        payload = {
            "sitenews": {
                "columns": ["id", "tag", "title", "published_at", "modified_at"],
                "data": [
                    [90001, "site", "Курс юаня на &quot;Мосбирже&quot; превысил 12 рублей", "2026-10-25 10:15:00", None],
                    [90002, "site", "", "2026-10-25 11:00:00", None],
                    [90003, "site", "Определена цена исполнения фьючерсного контракта на индекс ключевой ставки", "2026-10-25 11:00:00", None],
                    [90004, "site", "Изменены границы ценового коридора ценной бумаги RU000A10F090", "2026-10-25 11:05:00", None],
                    "мусор",
                ],
            }
        }
        items = parse_sitenews(payload)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://www.moex.com/n90001")
        self.assertEqual(items[0].published_at.utcoffset().total_seconds(), 3 * 3600)
        self.assertEqual(parse_sitenews({"unexpected": True}), [])
        # HTML-сущности ISS декодируются при нормализации.
        self.assertEqual(normalize_news_item(items[0]).title, 'Курс юаня на "Мосбирже" превысил 12 рублей')

    def test_service_messages_are_not_news(self) -> None:
        for title in (
            "Об изменении риск-параметров по акциям",
            "О регистрации проспекта биржевых облигаций",
            "Технические работы на сетевом оборудовании в зоне колокации",
            "2026-10-23 состоится депозитный аукцион 22 026 513 Межрегионального УФК",
        ):
            self.assertTrue(is_service_news(title), title)
        self.assertFalse(is_service_news("Мосбиржа запускает торги юанем с расчётами завтра"))


class StaticSource:
    name = "Банк России"

    def __init__(self, items) -> None:
        self.items = items

    def fetch(self):
        return self.items


class CollectOfficialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")

    def test_official_events_are_stored_alongside_rss(self) -> None:
        items = cbr.key_rate_items(RATES) + cbr.fx_items(LATEST, PREVIOUS, threshold=1.0)
        with patch.object(service, "extract_event", side_effect=keywords_only), patch.dict(
            "os.environ", {"NEWS_MAX_AGE_DAYS": "0"}
        ):
            result = service.collect_rss(self.store, [], extra_sources=[StaticSource(items)])

        self.assertEqual(len(result["added"]) + len(result["merged"]), 3)
        self.assertEqual(result["skipped_offtopic"], 0)
        self.assertTrue(all(event.source == "Банк России" for event in result["added"]))

    def test_configured_official_sources(self) -> None:
        with patch.dict("os.environ", {"NEWS_OFFICIAL_SOURCES": "cbr, moex, unknown"}):
            self.assertEqual(service.configured_official_sources(), ["cbr", "moex"])
        with patch.dict("os.environ", {"NEWS_OFFICIAL_SOURCES": ""}):
            self.assertEqual(service.configured_official_sources(), [])
        names = [source.name for source in service.official_sources(["cbr", "moex"])]
        self.assertEqual(names, ["Банк России", "Московская биржа"])


if __name__ == "__main__":
    unittest.main()


FX_ALL_XML = """<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="30.10.2026" name="Foreign Currency Market">
<Valute ID="R01770"><NumCode>752</NumCode><CharCode>SEK</CharCode><Nominal>10</Nominal><Name>Шведских крон</Name><Value>78,1234</Value></Valute>
<Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>1</Nominal><Name>Китайский юань</Name><Value>12,0844</Value></Valute>
</ValCurs>""".encode("cp1251")


class OfficialFxFactsTests(unittest.TestCase):
    def setUp(self) -> None:
        from app.modules.news.sources import cbr

        cbr._all_fx = None
        self.addCleanup(setattr, cbr, "_all_fx", None)
        self.cbr = cbr

    def test_any_currency_with_nominal(self) -> None:
        facts = self.cbr.official_fx_facts(["sek", "KPW", "CNY"], fetch=lambda: FX_ALL_XML)

        self.assertEqual([fact["id"] for fact in facts], ["market.fx.SEK", "market.fx.CNY"])  # воны КНДР у ЦБ нет
        self.assertIn("78,1234 руб. за 10 Шведских крон (SEK)", facts[0]["text"])
        self.assertIn("7,8123 руб. за 1", facts[0]["text"])
        self.assertIn("30.10.2026", facts[0]["text"])
        self.assertNotIn("за 1 —", facts[1]["text"])
