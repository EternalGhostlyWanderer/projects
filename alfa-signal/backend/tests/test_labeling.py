import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import score_labels  # noqa: E402


class LabelingMetricsTests(unittest.TestCase):
    def test_weighted_kappa(self) -> None:
        self.assertEqual(score_labels.weighted_kappa([(0, 0), (1, 1), (3, 3), (2, 2)]), 1.0)
        self.assertLess(score_labels.weighted_kappa([(0, 3), (3, 0), (1, 2), (2, 1)]), 0)

    def test_agreement_on_shared_pairs_only(self) -> None:
        labels = {"p1": {"anna": 3, "maria": 3}, "p2": {"anna": 1, "maria": 2}, "p3": {"anna": 0}}
        result = score_labels.agreement(labels)
        self.assertEqual(result["shared_pairs"], 2)
        self.assertEqual(result["exact"], 0.5)
        self.assertEqual(result["within_one"], 1.0)


if __name__ == "__main__":
    unittest.main()
