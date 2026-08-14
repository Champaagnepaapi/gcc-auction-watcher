from __future__ import annotations

import unittest

from v5 import source_scout_cmapi_liquid_sentinel as sentinel


class CmapiLiquidSentinelTests(unittest.TestCase):
    def test_call_cap_is_four(self) -> None:
        self.assertEqual(sentinel.MAX_CMAPI_CALLS, 4)
        self.assertGreaterEqual(sentinel.STOP_IF_REMAINING_AT_OR_BELOW, 10)

    def test_strict_identity_accepts_exact_base_set_charizard(self) -> None:
        row = {
            "name": "Charizard",
            "set_name": "Base Set",
            "card_number": "4/102",
            "id": 123,
        }
        self.assertTrue(sentinel._strict_match(row))

    def test_strict_identity_rejects_wrong_set(self) -> None:
        row = {
            "name": "Charizard",
            "set_name": "Base Set 2",
            "card_number": "4/130",
            "id": 456,
        }
        self.assertFalse(sentinel._strict_match(row))


if __name__ == "__main__":
    unittest.main()
