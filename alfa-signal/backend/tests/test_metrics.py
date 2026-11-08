import unittest

from app.evaluation.metrics import personalization, precision_at_k, summarize


def record(company_id, event_id, *, ok=True, status="verified", issues=(), rounds=0, bank="found", kind="risk", score=70, evidence=()):
    return {
        "company_id": company_id,
        "event_id": event_id,
        "ok": ok,
        "seconds": 10.0,
        "quality_status": status if ok else None,
        "issue_codes": list(issues),
        "tool_calls": 3,
        "rounds": rounds,
        "bank_view": bank,
        "kind": kind,
        "score": score,
        "company_evidence": list(evidence),
        "trace_id": "t",
    }


class MetricsTests(unittest.TestCase):
    def test_summary_rates(self) -> None:
        records = [
            record("A", "e1", evidence=["company.product.loa"]),
            record("B", "e1", status="partial", issues=["unsupported_number"], rounds=1, bank="not_found", kind="opportunity", evidence=["company.product.dep"]),
            record("C", "e2", ok=False),
        ]

        summary = summarize(records)

        self.assertEqual(summary["success_rate"], 0.667)
        self.assertEqual(summary["verified_rate"], 0.5)
        self.assertEqual(summary["revision_rate"], 0.5)
        self.assertEqual(summary["bank_found_rate"], 0.5)
        self.assertEqual(summary["runs_with_unsupported_numbers"], 1)

    def test_personalization_compares_companies_on_same_event(self) -> None:
        result = personalization(
            [
                record("A", "e1", evidence=["company.product.loa"]),
                record("B", "e1", kind="opportunity", evidence=["company.product.dep"]),
                record("C", "e2"),
            ]
        )

        self.assertEqual(result["pairs"], 1)
        self.assertEqual(result["mean_company_evidence_jaccard"], 0.0)
        self.assertEqual(result["share_different_kind_or_score"], 1.0)

    def test_precision_at_k(self) -> None:
        self.assertEqual(precision_at_k(["a", "b", "c"], {"a", "c"}, k=2), 0.5)
        self.assertIsNone(precision_at_k([], {"a"}))


if __name__ == "__main__":
    unittest.main()
