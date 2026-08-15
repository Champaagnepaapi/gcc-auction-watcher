from __future__ import annotations

import unittest

from v5 import source_scout_opportunity_benchmark_v3 as benchmark


class OpportunityBenchmarkV3Tests(unittest.TestCase):
    def test_anchor_clients_are_raised_for_twelve_fr_cards(self) -> None:
        for provider in ("tcgdex_ppt_anchor", "tcgdex_poketrace_anchor"):
            client = benchmark.OpportunitySafeClient(provider, call_cap=10)
            self.assertGreaterEqual(client.call_cap, 12)

    def test_ppt_pacing_remains_conservative(self) -> None:
        client = benchmark.OpportunitySafeClient("pokemonpricetracker", call_cap=60, interval=0.1)
        self.assertGreaterEqual(client.interval, 2.2)


if __name__ == "__main__":
    unittest.main()
