from pathlib import Path
import unittest


class NoProviderRelaxationTests(unittest.TestCase):
    def test_identity_module_does_not_touch_provider_matching_thresholds(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8")
        for token in ("POKETRACE_MAX_REQUESTS", "PRICECHARTING", "minimum_match_score", "MAX_PRICE_EUR"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
