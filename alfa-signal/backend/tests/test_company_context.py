import unittest
from unittest.mock import patch

from app.modules.companies.exposures import _summarize_direction
from app.modules.companies.profiling import build_company_profile
from app.modules.companies.relationships import RelationshipDataError
from app.modules.companies.repository import _exclude_duplicate_companies
from app.modules.personalization.context import build_personalization_context
from app.schemas.company import Company


def make_company(**overrides: object) -> Company:
    values: dict[str, object] = {
        "SYNTHETIC_U": "U_TEST",
        "CL_TYPE": "CLIENT",
        "REVENUE_COMPANY": 1000,
        "CL_PRODUCT_RKO_MARK": 0,
        "CL_PRODUCT_GAR_MARK": 0,
        "CL_PRODUCT_LOA_MARK": 1,
        "CL_PRODUCT_LEA_MARK": 0,
        "CL_PRODUCT_DEP_MARK": 0,
        "CL_PRODUCT_ZPP_MARK": 0,
        "FTS_FLAG": 1,
        "FACTORING_MARK": 0,
        "NEGATIVEMARK": 0,
    }
    values.update(overrides)
    return Company.model_validate(values)


class CompanyProfileTests(unittest.TestCase):
    def test_normalizes_flags_and_revenue_placeholder(self) -> None:
        profile = build_company_profile(make_company())

        self.assertIs(profile["products"]["loa"], True)
        self.assertIs(profile["products"]["dep"], False)
        self.assertIs(profile["risk_indicators"]["fts_data_available"], True)
        self.assertIsNone(profile["financials"]["revenue_rub"])
        self.assertIn(
            "financials.revenue_rub",
            profile["data_quality"]["missing_fields"],
        )

    def test_excludes_every_conflicting_duplicate_id(self) -> None:
        companies, duplicate_ids = _exclude_duplicate_companies(
            [
                make_company(SYNTHETIC_U="U_DUP", REGION="Москва"),
                make_company(SYNTHETIC_U="U_OK"),
                make_company(SYNTHETIC_U="U_DUP", REGION="Казань"),
            ]
        )

        self.assertEqual([company.id for company in companies], ["U_OK"])
        self.assertEqual(duplicate_ids, ("U_DUP",))

    def test_keeps_one_copy_of_identical_duplicate(self) -> None:
        company = make_company(SYNTHETIC_U="U_SAME")

        companies, duplicate_ids = _exclude_duplicate_companies(
            [company, company.model_copy()]
        )

        self.assertEqual([item.id for item in companies], ["U_SAME"])
        self.assertEqual(duplicate_ids, ())

    def test_small_counterparty_set_is_not_labeled_high(self) -> None:
        relationships = [
            {
                "direction": "incoming",
                "counterparty_id": f"C_{index}",
                "amount": 100.0,
                "count": 1.0,
            }
            for index in range(3)
        ]

        summary = _summarize_direction(relationships, "incoming")

        self.assertEqual(summary["counterparty_count"], 3)
        self.assertEqual(summary["concentration"], "insufficient_counterparties")


class PersonalizationContextTests(unittest.TestCase):
    @patch("app.modules.personalization.context.calculate_company_exposures")
    @patch("app.modules.personalization.context.get_analytics_profile")
    def test_returns_profile_when_payments_are_unavailable(
        self,
        get_profile_mock,
        calculate_exposures_mock,
    ) -> None:
        get_profile_mock.return_value = build_company_profile(make_company())
        calculate_exposures_mock.side_effect = RelationshipDataError("missing")

        context = build_personalization_context("U_TEST")

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["payment_exposures"]["status"], "unavailable")
        self.assertEqual(context["eligibility"]["supported"], True)
        self.assertIn(
            "interest_rate",
            [item["factor"] for item in context["sensitivity_factors"]],
        )


if __name__ == "__main__":
    unittest.main()
