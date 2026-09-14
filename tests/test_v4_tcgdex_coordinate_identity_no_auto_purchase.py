from pathlib import Path
import unittest


class NoAutoPurchaseTests(unittest.TestCase):
    def test_identity_module_is_read_only(self) -> None:
        source = Path("v4_tcgdex_coordinate_authoritative_name.py").read_text(encoding="utf-8").casefold()
        for token in ("buy_now", "checkout", "bid_amount", "payment_method"):
            self.assertNotIn(token, source)


if __name__ == "__main__":
    unittest.main()
