import unittest

from app.modules.personalization.scoring import GROUP_MAX, MIN_FEED_SCORE, score_event


def context(**overrides) -> dict:
    profile = {
        "industry": {"code": "25.11", "name": "Производство строительных металлических конструкций"},
        "location": {"region": "Москва"},
        "products": {"loa": True, "lea": True, "dep": True},
        "risk_indicators": {"fts_data_available": True, "fts_country": "КИТАЙ, ТУРЦИЯ"},
    }
    profile.update(overrides.pop("profile", {}))
    return {
        "company_profile": profile,
        "payment_exposures": {},
        "counterparty_industries": overrides.pop("counterparties", {"industries": []}),
        "related_companies": overrides.pop("related", []),
    }


def event(event_type="monetary_policy", channels=(), codes=(), countries=(), regions=()) -> dict:
    return {
        "event_type": event_type,
        "impact_channels": list(channels),
        "entities": {"okved_codes": list(codes), "countries": list(countries), "regions": list(regions)},
    }


RATE = {
    **event("monetary_policy", ["interest_rate", "deposit_yield", "leasing_cost", "inflation"]),
    "title": "Банк России сохранил ключевую ставку на уровне 14% годовых",
}
METAL_DUTY = event("trade", ["international_trade", "industry"], codes=["24", "25"])
GRAIN_LOANS = event("trade", ["interest_rate", "international_trade", "industry"], codes=["01"])
CHINA_PAYMENTS = event("trade", ["international_trade"], countries=["Китай"])
FOOTBALL = event("other")


class ScoringTests(unittest.TestCase):
    def test_components_sum_to_score_within_range(self) -> None:
        cases = [RATE, METAL_DUTY, GRAIN_LOANS, CHINA_PAYMENTS, FOOTBALL]
        for item in cases:
            result = score_event(context(), item)
            with self.subTest(item["event_type"]):
                self.assertEqual(sum(part["points"] for part in result["components"]), result["score"])
                self.assertTrue(0 <= result["score"] <= 100)
                for part in result["components"]:
                    self.assertLessEqual(part["points"], GROUP_MAX[part["group"]])

    def test_irrelevant_news_scores_zero(self) -> None:
        result = score_event(context(), FOOTBALL)

        self.assertEqual(result["score"], 0)
        self.assertEqual(result["level"], "none")
        self.assertEqual(result["components"], [])

    def test_similar_factors_do_not_inflate(self) -> None:
        # Кредит, лизинг и депозит: лучший канал целиком, остальные наполовину, не выше максимума группы.
        result = score_event(context(), RATE)

        self.assertEqual(result["score"], 35)
        self.assertEqual(result["level"], "medium")
        self.assertEqual([part["group"] for part in result["components"]], ["channels"])
        self.assertIn("кредиты", result["explanation"])
        self.assertIn("лизинг", result["explanation"])

    def test_rate_commentary_weighs_less_than_decision(self) -> None:
        commentary = {**RATE, "title": "Набиуллина: ЦБ предметно обсудил сохранение ключевой ставки"}
        self.assertLess(score_event(context(), commentary)["score"], score_event(context(), RATE)["score"])

    def test_foreign_central_bank_rate_is_not_a_loan_rate(self) -> None:
        turkey = {
            **event("monetary_policy", ["interest_rate", "deposit_yield", "leasing_cost"], countries=["ТУРЦИЯ"]),
            "title": "Центробанк Турции снизил ключевую ставку до 36%",
        }
        # Компания торгует с Турцией — география засчитывается, а кредитная ставка нет.
        groups = [part["group"] for part in score_event(context(), turkey)["components"]]
        self.assertNotIn("channels", groups)

    def test_same_news_differs_between_companies(self) -> None:
        steel = score_event(context(), METAL_DUTY)
        grain = score_event(
            context(profile={"industry": {"code": "01.11", "name": "Выращивание зерновых"}}), METAL_DUTY
        )

        self.assertGreater(steel["score"], 0)
        self.assertEqual(grain["score"], 0)

    def test_sector_news_needs_sector_link_for_financial_channels(self) -> None:
        # «Льготные кредиты экспортёрам зерна» не должны попадать каждому заёмщику.
        borrower = score_event(context(), GRAIN_LOANS)
        farmer = score_event(context(profile={"industry": {"code": "01.11", "name": "Зерно"}}), GRAIN_LOANS)

        self.assertEqual(borrower["score"], 0)
        self.assertGreaterEqual(farmer["score"], 30)

    def test_country_specific_trade_news_requires_matching_country(self) -> None:
        china = score_event(context(), CHINA_PAYMENTS)
        kazakhstan = score_event(
            context(profile={"risk_indicators": {"fts_data_available": True, "fts_country": "КАЗАХСТАН"}}),
            CHINA_PAYMENTS,
        )

        self.assertGreater(china["score"], kazakhstan["score"])
        self.assertEqual(kazakhstan["score"], 0)
        self.assertIn("география", china["explanation"])

    def test_supply_chain_is_a_hypothesis_proportional_to_payment_share(self) -> None:
        trader = context(
            profile={"industry": {"code": "47.11", "name": "Розница"}, "products": {}, "risk_indicators": {}},
            counterparties={"industries": [{"okved_class": "24", "share": 0.6, "direction": "outgoing"}]},
        )

        result = score_event(trader, METAL_DUTY)

        supply = next(part for part in result["components"] if part["group"] == "supply_chain")
        self.assertEqual(supply["certainty"], "hypothesis")
        self.assertEqual(supply["points"], round(round(0.6 * 15) * 0.9))

    def test_small_supply_share_alone_is_not_shown(self) -> None:
        trader = context(
            profile={"industry": {"code": "47.11", "name": "Розница"}, "products": {}, "risk_indicators": {}},
            counterparties={"industries": [{"okved_class": "24", "share": 0.07, "direction": "outgoing"}]},
        )

        self.assertEqual(score_event(trader, METAL_DUTY)["score"], 0)

    def test_group_member_in_affected_industry_counts(self) -> None:
        holding = context(
            profile={"industry": {"code": "68.20", "name": "Аренда"}, "products": {}, "risk_indicators": {}},
            related=[{"company_id": "U_2", "okved_code": "24.10", "certainty": "confirmed"}],
        )

        result = score_event(holding, METAL_DUTY)

        self.assertEqual([part["group"] for part in result["components"]], ["related"])
        self.assertEqual(result["components"][0]["certainty"], "confirmed")

    def test_levels_follow_thresholds(self) -> None:
        # Решение по ставке для компании с кредитом, лизингом и депозитом — заметное влияние.
        self.assertEqual(score_event(context(), RATE)["level"], "medium")
        steel_china = event("trade", ["international_trade", "industry"], codes=["25"], countries=["Китай"])
        self.assertIn(score_event(context(), steel_china)["level"], {"medium", "high"})
        self.assertGreaterEqual(MIN_FEED_SCORE, 1)


if __name__ == "__main__":
    unittest.main()


class ScaleTests(unittest.TestCase):
    def test_score_never_exceeds_100_and_parts_sum_up(self) -> None:
        from app.modules.personalization.scoring import _fit_to_scale

        parts = [{"group": group, "points": points} for group, points in
                 (("industry", 30), ("channels", 35), ("geography", 20), ("supply_chain", 15), ("related", 10), ("role", 15))]
        scaled = _fit_to_scale(parts)
        self.assertEqual(sum(item["points"] for item in scaled), 100)
        self.assertTrue(all(item["scaled"] for item in scaled))
        self.assertEqual(_fit_to_scale(parts[:2]), parts[:2])


class LowInformationTests(unittest.TestCase):
    """Заявление без новой меры и онлайн-трансляция: тема есть, нового решения нет."""

    def test_statement_without_measure_drops_below_feed(self) -> None:
        statement = {
            **event("sanctions", ["international_trade"]),
            "title": "Медведев заявил, что Россия вопреки санкциям «как стояла, так и стоит»",
        }
        measure = {**event("sanctions", ["international_trade"]), "title": "ЕС утвердил 20-й пакет санкций"}

        quiet = score_event(context(), statement)
        loud = score_event(context(), measure)

        self.assertLess(quiet["score"], MIN_FEED_SCORE)
        self.assertGreater(loud["score"], quiet["score"])
        self.assertIn("без новой меры", quiet["explanation"])

    def test_live_coverage_is_low_information(self) -> None:
        live = {**event("sanctions", ["international_trade"]), "title": "Военная операция на Украине. Онлайн"}

        self.assertLess(score_event(context(), live)["score"], MIN_FEED_SCORE)

    def test_announcement_is_low_information(self) -> None:
        from app.modules.personalization.scoring import is_low_information

        self.assertTrue(is_low_information("23 октября в 15:00 состоится пресс-конференция по итогам заседания Совета директоров"))

    def test_preanalysis_covers_whole_feed(self) -> None:
        from app.modules.news.scheduler import SchedulerConfig

        self.assertEqual(SchedulerConfig().min_score, MIN_FEED_SCORE)

    def test_regulator_signal_and_decision_keep_weight(self) -> None:
        from app.modules.personalization.scoring import is_low_information

        self.assertFalse(is_low_information("Набиуллина допустила снижение ставки"))
        self.assertFalse(is_low_information("Минфин заявил о введении пошлин на прокат"))
        self.assertFalse(is_low_information(RATE["title"]))


class FeedFreshnessTests(unittest.TestCase):
    def test_age_counts_from_newest_news(self) -> None:
        from datetime import datetime, timedelta, timezone

        from app.modules.personalization.scoring import feed_freshness

        newest = datetime(2026, 10, 1, tzinfo=timezone.utc)
        # Через месяц без новостей вчерашняя (относительно последней) новость всё ещё свежая.
        self.assertEqual(feed_freshness(30, newest - timedelta(hours=5), newest)["factor"], 1.0)

    def test_important_old_event_outranks_fresh_background(self) -> None:
        from datetime import datetime, timedelta, timezone

        from app.modules.personalization.scoring import feed_freshness

        newest = datetime(2026, 10, 26, tzinfo=timezone.utc)
        old_important = 70 * feed_freshness(70, newest - timedelta(days=20), newest)["factor"]
        fresh_background = 25 * feed_freshness(25, newest, newest)["factor"]

        self.assertGreater(old_important, fresh_background)
