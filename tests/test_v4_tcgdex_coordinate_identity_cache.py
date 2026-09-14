import unittest

import v4_tcgdex_coordinate_authoritative_name as target


class CoordinateIdentityCacheTests(unittest.TestCase):
    def test_local_caches_can_be_cleared_without_touching_market_state(self) -> None:
        target._RESULT_CACHE.clear()
        target._NEGATIVE_CACHE.clear()
        self.assertEqual(target._RESULT_CACHE, {})
        self.assertEqual(target._NEGATIVE_CACHE, set())


if __name__ == "__main__":
    unittest.main()
