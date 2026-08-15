from __future__ import annotations

import unittest

from v5.catalog_identity_benchmark import _core_compatibility, _number_compatible
from v5.models import CardIdentity


def identity(*, name="Charizard", set_name="Base Set", number="4/102"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=name,
        set=set_name,
        card_number=number,
        language="English",
    )


class CatalogBenchmarkConsensusTests(unittest.TestCase):
    def test_leading_zero_number_is_exactly_compatible(self):
        compatible, enrichment = _number_compatible("004/102", "4/102")
        self.assertTrue(compatible)
        self.assertFalse(enrichment)

    def test_numerator_only_vs_full_number_is_enrichment_not_disagreement(self):
        compatible, enrichment = _number_compatible("4", "004/102")
        self.assertTrue(compatible)
        self.assertTrue(enrichment)

    def test_conflicting_full_denominator_is_hard_disagreement(self):
        compatible, enrichment = _number_compatible("4/102", "004/130")
        self.assertFalse(compatible)
        self.assertFalse(enrichment)

    def test_safe_set_alias_and_number_enrichment_are_consensus(self):
        compatible, enrichment, failures = _core_compatibility(
            identity(set_name="Pokemon TCG Base Set", number="4"),
            identity(set_name="Base Set", number="004/102"),
        )
        self.assertTrue(compatible)
        self.assertTrue(enrichment)
        self.assertEqual(failures, ())

    def test_name_conflict_is_hard_disagreement(self):
        compatible, _enrichment, failures = _core_compatibility(
            identity(name="Charizard"), identity(name="Blastoise")
        )
        self.assertFalse(compatible)
        self.assertIn("name", failures)


if __name__ == "__main__":
    unittest.main()
