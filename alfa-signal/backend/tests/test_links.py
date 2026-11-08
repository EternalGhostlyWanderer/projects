import unittest
from pathlib import Path
from unittest.mock import patch

from app.modules.companies import links, relationships, repository
from app.modules.companies.links import (
    clean_revenue,
    counterparty_industries,
    group_summary,
    okved_class,
    related_companies,
)

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"


class LinksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patches = [
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
        ]
        for item in cls.patches:
            item.start()
        cls.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls.patches:
            item.stop()
        cls.clear()

    @staticmethod
    def clear() -> None:
        repository.clear_company_cache()
        relationships.clear_relationship_cache()
        links.clear_links_cache()

    def company(self, company_id: str):
        return repository.find_company_by_id(company_id)

    def test_revenue_placeholder_is_missing(self) -> None:
        self.assertIsNone(clean_revenue(1000))
        self.assertIsNone(clean_revenue(None))
        self.assertEqual(clean_revenue(2.5e9), 2.5e9)

    def test_okved_class(self) -> None:
        self.assertEqual(okved_class("46.34.2"), "46")
        self.assertEqual(okved_class("01.11"), "01")
        self.assertIsNone(okved_class(None))

    def test_group_revenue_is_summed_without_placeholders(self) -> None:
        summary = group_summary(self.company("SYN_001"))

        # SYN_001 (24 млрд) + SYN_004 (31 млрд) + SYN_007 (заглушка 1000 — не учитывается)
        self.assertEqual(summary["company_count"], 3)
        self.assertEqual(summary["revenue_rub"], 55e9)
        self.assertFalse(summary["revenue_complete"])
        self.assertTrue(summary["large_business"])

    def test_company_without_group_is_its_own_group(self) -> None:
        summary = group_summary(self.company("SYN_002"))

        self.assertEqual(summary["company_count"], 1)
        self.assertEqual(summary["revenue_rub"], 18.5e9)

    def test_group_members_are_confirmed_and_people_links_are_hypotheses(self) -> None:
        group = {item["company_id"]: item for item in related_companies(self.company("SYN_001"))}
        people = {item["company_id"]: item for item in related_companies(self.company("SYN_003"))}

        self.assertEqual(set(group), {"SYN_004", "SYN_007"})
        self.assertEqual(group["SYN_004"]["certainty"], "confirmed")
        self.assertEqual(people["SYN_006"]["link"], "shared_person")
        self.assertEqual(people["SYN_006"]["certainty"], "hypothesis")

    def test_counterparty_industries_exclude_self_transfers_and_keep_unknown(self) -> None:
        result = counterparty_industries("SYN_001")

        classes = {(item["okved_class"], item["direction"]): item["share"] for item in result["industries"]}
        self.assertIn(("46", "outgoing"), classes)
        self.assertIn(("24", "outgoing"), classes)
        self.assertIn(("41", "incoming"), classes)
        # Контрагенты без профиля (SYN_CP_07 и др.) не угадываются, а уходят в «неизвестно».
        self.assertGreater(result["unknown_share"], 0)
        self.assertAlmostEqual(sum(classes.values()) + result["unknown_share"], 1.0, places=3)
        self.assertEqual(result["certainty"], "hypothesis")


if __name__ == "__main__":
    unittest.main()
