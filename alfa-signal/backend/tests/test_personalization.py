import unittest

from app.modules.personalization.relevance import assess_relevance


EVENTS = [
    {
        "event_id": "NEWS_001",
        "impact_channels": [
            "interest_rate",
            "deposit_yield",
            "leasing_cost",
        ],
    },
    {
        "event_id": "NEWS_002",
        "impact_channels": ["international_trade"],
    },
    {
        "event_id": "NEWS_003",
        "impact_channels": [
            "incoming_concentration",
            "outgoing_concentration",
        ],
    },
]


COMPANIES = [
    {
        "company_id": "A",
        "factors": ["interest_rate"],
        "expected": [1, 0, 0],
    },
    {
        "company_id": "B",
        "factors": ["deposit_yield"],
        "expected": [1, 0, 0],
    },
    {
        "company_id": "C",
        "factors": ["international_trade"],
        "expected": [0, 1, 0],
    },
    {
        "company_id": "D",
        "factors": ["incoming_concentration"],
        "expected": [0, 0, 1],
    },
    {
        "company_id": "E",
        "factors": [
            "interest_rate",
            "leasing_cost",
            "international_trade",
        ],
        "expected": [2, 1, 0],
    },
]


class TestPersonalization(unittest.TestCase):
    def test_five_companies(self) -> None:
        for company in COMPANIES:
            context = {
                "company_id": company["company_id"],
                "sensitivity_factors": [
                    {"factor": factor}
                    for factor in company["factors"]
                ],
            }

            results = [
                assess_relevance(context, event)
                for event in EVENTS
            ]
            actual = [result["match_count"] for result in results]

            with self.subTest(company=company["company_id"]):
                self.assertEqual(actual, company["expected"])

    def test_no_false_matches(self) -> None:
        context = {
            "company_id": "EMPTY",
            "sensitivity_factors": [],
        }

        result = assess_relevance(context, EVENTS[0])

        self.assertEqual(result["match_count"], 0)
        self.assertFalse(result["has_direct_matches"])
        self.assertEqual(result["matched_factors"], [])


if __name__ == "__main__":
    unittest.main()
