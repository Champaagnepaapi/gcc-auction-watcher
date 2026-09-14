import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target


class ExistingExactUnchangedTests(unittest.TestCase):
    def test_wrapper_returns_existing_exact_without_new_recovery(self) -> None:
        lot = watcher.Lot(url="x", title="Palkia-GX", current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Ultra Prism", card_number="165/156", language="English")
        exact = canonical.CanonicalCard("EXACT", card_id="sm5-165")
        previous = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = lambda _lot: exact
        try:
            self.assertIs(target._resolve_with_coordinate_authority(lot), exact)
        finally:
            target._ORIGINAL_RESOLVER = previous


if __name__ == "__main__":
    unittest.main()
