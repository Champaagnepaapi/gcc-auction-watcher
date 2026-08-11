from __future__ import annotations

import unittest

from v5.models import CardIdentity
from v5.poketrace_matching import REJECT_VARIANT, _candidate_evidence
from v5.variant_semantics import (
    EDITION_FIRST,
    FINISH_HOLO,
    FINISH_REVERSE,
    FINISH_STANDARD,
    semantics_from_identity,
    semantics_from_text,
    tcgdex_variant_supports_identity,
    variant_compatibility,
)


def candidate(*, variant="Holofoil", rarity="Rare Holo", set_name="Base Set"):
    return {
        "id": "pt-card",
        "name": "Charizard",
        "cardNumber": "004/102",
        "set": {"name": set_name, "slug": "base-set"},
        "variant": variant,
        "rarity": rarity,
        "productType": "single",
    }


def identity(**kwargs):
    values = dict(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
    )
    values.update(kwargs)
    return CardIdentity(**values)


class VariantSemanticsTests(unittest.TestCase):
    def test_holo_aliases_canonicalize_to_same_finish(self):
        self.assertEqual(semantics_from_text("Holographic").finish, FINISH_HOLO)
        self.assertEqual(semantics_from_text("Holofoil").finish, FINISH_HOLO)
        result = variant_compatibility(identity(finish="Holographic"), candidate())
        self.assertTrue(result.compatible)
        self.assertTrue(result.finish_match)

    def test_reverse_holo_is_not_collapsed_into_holo(self):
        result = variant_compatibility(
            identity(finish="Reverse Holo"),
            candidate(variant="Holofoil"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "finish_conflict")
        evidence = _candidate_evidence(identity(finish="Reverse Holo"), candidate())
        self.assertEqual(evidence.rejection, REJECT_VARIANT)

    def test_rarity_holo_does_not_override_explicit_reverse_finish(self):
        parsed, conflict = semantics_from_identity(
            identity(finish="Reverse Holo", rarity="Rare Holo")
        )
        self.assertFalse(conflict)
        self.assertEqual(parsed.finish, FINISH_REVERSE)

        result = variant_compatibility(
            identity(finish="Reverse Holo", rarity="Rare Holo"),
            candidate(variant="Reverse Holofoil", rarity="Rare Holo"),
        )
        self.assertTrue(result.compatible)
        self.assertTrue(result.finish_match)

    def test_set_name_finish_word_is_not_physical_finish_evidence(self):
        parsed, conflict = semantics_from_identity(identity(set="Holo Collection"))
        self.assertFalse(conflict)
        self.assertIsNone(parsed.finish)

    def test_missing_candidate_finish_evidence_is_blocking(self):
        result = variant_compatibility(
            identity(finish="Holo"),
            candidate(variant=None, rarity="Rare Holo"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "candidate_finish_missing")
        self.assertTrue(result.metadata_missing)

    def test_missing_listing_finish_evidence_is_blocking(self):
        result = variant_compatibility(
            identity(),
            candidate(variant="Holofoil", rarity="Rare Holo"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "listing_finish_missing")
        self.assertTrue(result.metadata_missing)

    def test_normal_and_non_holo_share_standard_family(self):
        self.assertEqual(semantics_from_text("Normal").finish, FINISH_STANDARD)
        result = variant_compatibility(
            identity(finish="Non Holo"),
            candidate(variant="Standard", rarity="Rare"),
        )
        self.assertTrue(result.compatible)
        self.assertTrue(result.finish_match)

    def test_ebay_standard_parallel_does_not_conflict_with_holo_finish(self):
        parsed, conflict = semantics_from_identity(
            identity(variant="Standard", finish="Holo", edition="Unlimited")
        )
        self.assertFalse(conflict)
        self.assertEqual(parsed.finish, FINISH_HOLO)

        result = variant_compatibility(
            identity(variant="Standard", finish="Holo", edition="Unlimited"),
            candidate(variant="Unlimited Holofoil"),
        )
        self.assertTrue(result.compatible)
        self.assertTrue(result.finish_match)
        self.assertTrue(result.edition_match)

    def test_first_edition_holo_is_split_into_edition_and_finish(self):
        parsed, conflict = semantics_from_identity(
            identity(variant="1st Edition Holofoil")
        )
        self.assertFalse(conflict)
        self.assertEqual(parsed.edition, EDITION_FIRST)
        self.assertEqual(parsed.finish, FINISH_HOLO)
        result = variant_compatibility(
            identity(edition="1st Edition", finish="Holo"),
            candidate(variant="1st Edition Holofoil"),
        )
        self.assertTrue(result.compatible)
        self.assertTrue(result.edition_match)
        self.assertTrue(result.finish_match)

    def test_first_edition_vs_unlimited_is_blocking(self):
        result = variant_compatibility(
            identity(edition="1st Edition", finish="Holo"),
            candidate(variant="Unlimited Holofoil"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "edition_conflict")

    def test_premium_edition_missing_on_candidate_is_not_invented(self):
        result = variant_compatibility(
            identity(edition="1st Edition", finish="Holo"),
            candidate(variant="Holofoil"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "candidate_edition_missing")
        self.assertTrue(result.metadata_missing)

    def test_candidate_first_edition_without_listing_proof_is_not_invented(self):
        result = variant_compatibility(
            identity(finish="Holo"),
            candidate(variant="1st Edition Holofoil"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "listing_edition_missing")

    def test_promo_can_be_proven_from_set_or_rarity(self):
        listing = identity(set="Black Star Promos", rarity="Promo", finish="Holo")
        result = variant_compatibility(
            listing,
            candidate(variant="Holofoil", rarity="Promo", set_name="Black Star Promos"),
        )
        self.assertTrue(result.compatible)
        self.assertTrue(result.promo_match)

    def test_listing_promo_requires_candidate_promo_evidence(self):
        result = variant_compatibility(
            identity(rarity="Promo", finish="Holo"),
            candidate(variant="Holofoil", rarity="Rare Holo", set_name="Base Set"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "candidate_promo_missing")
        self.assertTrue(result.metadata_missing)

    def test_candidate_promo_requires_listing_promo_evidence(self):
        result = variant_compatibility(
            identity(finish="Holo"),
            candidate(variant="Holofoil", rarity="Promo", set_name="Promo Set"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "listing_promo_missing")
        self.assertTrue(result.metadata_missing)

    def test_special_finish_is_not_collapsed_to_generic_holo(self):
        result = variant_compatibility(
            identity(variant="Cosmos Holo"),
            candidate(variant="Holofoil"),
        )
        self.assertFalse(result.compatible)
        self.assertEqual(result.reason, "candidate_special_finish_missing")

    def test_tcgdex_variants_only_check_availability_not_listing_variant(self):
        card = {
            "variants": {
                "firstEdition": True,
                "holo": True,
                "normal": False,
                "reverse": True,
                "wPromo": False,
            }
        }
        self.assertTrue(
            tcgdex_variant_supports_identity(
                identity(edition="1st Edition", finish="Holo"), card
            )
        )
        self.assertFalse(
            tcgdex_variant_supports_identity(identity(finish="Normal"), card)
        )


if __name__ == "__main__":
    unittest.main()
