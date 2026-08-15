from __future__ import annotations

import unittest

from catalog_cardinality import (
    CatalogCard,
    CatalogCardinalityIndex,
    IdentityClues,
    ResolutionStatus,
)


class CatalogCardinalityTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = [
            CatalogCard("swsh7-192-en", "Dragonite V", "Evolving Skies", "192/203", "en"),
            CatalogCard("swsh7-192-fr", "Dracolosse V", "Évolution Céleste", "192/203", "fr"),
            CatalogCard("swsh12-186-en", "Lugia V", "Silver Tempest", "186/195", "en"),
            CatalogCard("other-lugia-en", "Lugia V", "Example Set", "001/100", "en"),
            CatalogCard("swsh8-271-en", "Gengar VMAX", "Fusion Strike", "271/264", "en"),
        ]
        self.index = CatalogCardinalityIndex(rows, snapshot_version="tcgdex-test-20260815")

    def test_any_exact_subset_can_resolve_when_cardinality_is_one(self) -> None:
        result = self.index.resolve(IdentityClues(name="Gengar VMAX", language="EN"))
        self.assertEqual(result.status, ResolutionStatus.RESOLVED)
        self.assertEqual(result.card.catalog_id, "swsh8-271-en")
        self.assertEqual(result.candidate_count, 1)
        self.assertIn("set_name", result.inferred_fields)
        self.assertIn("number", result.inferred_fields)

    def test_full_number_resolves_and_infers_name_set(self) -> None:
        result = self.index.resolve(IdentityClues(number="192/203", language="en"))
        self.assertEqual(result.status, ResolutionStatus.RESOLVED)
        self.assertEqual(result.card.name, "Dragonite V")
        self.assertEqual(result.card.set_name, "Evolving Skies")

    def test_numerator_plus_set_resolves(self) -> None:
        result = self.index.resolve(IdentityClues(set_name="Evolving Skies", number="192", language="en"))
        self.assertEqual(result.status, ResolutionStatus.RESOLVED)
        self.assertEqual(result.card.catalog_id, "swsh7-192-en")

    def test_ambiguous_subset_never_guesses(self) -> None:
        result = self.index.resolve(IdentityClues(name="Lugia V", language="en"))
        self.assertEqual(result.status, ResolutionStatus.AMBIGUOUS)
        self.assertEqual(result.candidate_count, 2)
        self.assertIsNone(result.card)

    def test_more_clues_reduce_ambiguity(self) -> None:
        result = self.index.resolve(IdentityClues(name="Lugia V", number="186/195", language="en"))
        self.assertEqual(result.status, ResolutionStatus.RESOLVED)
        self.assertEqual(result.card.catalog_id, "swsh12-186-en")

    def test_wrong_denominator_is_unresolved(self) -> None:
        result = self.index.resolve(IdentityClues(number="192/264", language="en"))
        self.assertEqual(result.status, ResolutionStatus.UNRESOLVED)
        self.assertEqual(result.candidate_count, 0)

    def test_language_is_not_silently_collapsed(self) -> None:
        result = self.index.resolve(IdentityClues(number="192/203"))
        self.assertEqual(result.status, ResolutionStatus.AMBIGUOUS)
        self.assertEqual(result.candidate_count, 2)

    def test_empty_clues_never_resolve(self) -> None:
        result = self.index.resolve(IdentityClues())
        self.assertEqual(result.status, ResolutionStatus.UNRESOLVED)


if __name__ == "__main__":
    unittest.main()
