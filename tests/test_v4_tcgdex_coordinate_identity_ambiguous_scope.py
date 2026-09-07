import unittest

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_coordinate_authoritative_name as target


class AmbiguousScopeTests(unittest.TestCase):
    def test_unrelated_ambiguous_reason_is_never_overridden(self) -> None:
        lot = watcher.Lot(url="x", title="Palkia", current_price=1.0, source_type="fixed", grader="PSA", grade="10", card_set="Ultra Prism", card_number="165", language="English")
        ambiguous = canonical.CanonicalCard("AMBIGUOUS", reason="set TCGdex exact non unique")
        previous = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = lambda _lot: ambiguous
        try:
            self.assertIs(target._resolve_with_coordinate_authority(lot), ambiguous)
        finally:
            target._ORIGINAL_RESOLVER = previous


if __name__ == "__main__":
    unittest.main()
