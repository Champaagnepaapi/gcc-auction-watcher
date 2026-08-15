from __future__ import annotations

import unittest

from v5 import source_scout_opportunity_benchmark_v2 as benchmark
from v5.source_scout_benchmark import Observation, Runtime


class OpportunityBenchmarkV2Tests(unittest.TestCase):
    def test_summary_counts_anchor_only_rows(self) -> None:
        rows = [
            Observation("cmapi", "a", identity="EXACT"),
            Observation("cmapi", "b", identity="ANCHOR_ONLY"),
            Observation("cmapi", "c", identity="ANCHOR_ONLY"),
        ]
        summary = benchmark._summary_with_anchor("cmapi", rows, Runtime())
        self.assertEqual(summary["identity_exact"], 1)
        self.assertEqual(summary["identity_anchor"], 2)


if __name__ == "__main__":
    unittest.main()
