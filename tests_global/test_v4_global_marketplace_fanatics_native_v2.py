import unittest

import v4_canonical_multimarket as multimarket
from v4_global_marketplace_fanatics_native_v2 import (
    FANATICS_POKEMON_BROWSE,
    fanatics_coordinate_candidates,
    resolve_fanatics_native_identity_v2,
)


def canonical(*, name, set_name, local_id, full_number, language="ja", status="EXACT", reason="TEST_EXACT"):
    return multimarket.CanonicalCard(
        status=status,
        card_id=f"test-{set_name}-{local_id}",
        set_id=f"test-{set_name}",
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=name,
        language_code=language,
        reason=reason,
    )


class FanaticsNativeV2Tests(unittest.TestCase):
    def test_browse_is_broad_pokemon_not_generic_or_card_targeted(self):
        self.assertIn("type=FIXED", FANATICS_POKEMON_BROWSE)
        self.assertIn("similarQuery=Pokemon", FANATICS_POKEMON_BROWSE)

    def test_real_no_rarity_title_can_resolve_by_bounded_suffix_partition(self):
        title = "2021 Pokemon Japanese Sword & Shield 25th Anniversary Collection Dialga #8 PSA 10 GEM MINT"

        def resolver(lot):
            if lot.title == "Dialga" and lot.card_set == "25th Anniversary Collection":
                return canonical(
                    name="Dialga",
                    set_name="25th Anniversary Collection",
                    local_id="8",
                    full_number="8/28",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v2(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "Dialga")
        self.assertEqual(result.identity.set_name, "25th Anniversary Collection")
        self.assertEqual(result.identity.number, "8/28")

    def test_real_pokemon_before_year_and_post_number_name_shape_resolves(self):
        title = "Pokemon 2021 Japanese 25th Anniversary Collection #001 FA/Pikachu PSA 10"

        def resolver(lot):
            if lot.title == "Pikachu" and lot.card_set == "25th Anniversary Collection":
                return canonical(
                    name="Pikachu",
                    set_name="25th Anniversary Collection",
                    local_id="1",
                    full_number="1/28",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v2(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "Pikachu")
        self.assertEqual(result.identity.number, "1/28")

    def test_existing_rarity_boundary_shape_still_resolves(self):
        title = "2025 Pokemon Japanese Scarlet & Violet Black Bolt SAR Genesect ex #172 PSA 10 GEM MINT"

        def resolver(lot):
            if lot.title == "Genesect ex" and lot.card_set == "Black Bolt":
                return canonical(
                    name="Genesect ex",
                    set_name="Black Bolt",
                    local_id="172",
                    full_number="172/086",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v2(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "Genesect ex")

    def test_non_pokemon_or_missing_explicit_language_never_produces_candidates(self):
        candidates, reason = fanatics_coordinate_candidates(
            "2025 Topps Chrome Basketball LeBron James #23 PSA 10 GEM MINT"
        )
        self.assertEqual(candidates, [])
        self.assertEqual(reason, "fanatics_title_schema_unproven")

        candidates, reason = fanatics_coordinate_candidates(
            "2025 Pokemon Black Bolt Genesect ex #172 PSA 10 GEM MINT"
        )
        self.assertEqual(candidates, [])
        self.assertEqual(reason, "fanatics_title_schema_unproven")

    def test_conflicting_full_fraction_still_fails_closed(self):
        title = "2021 Pokemon Japanese Sword & Shield 25th Anniversary Collection Dialga #8 PSA 10 GEM MINT"

        def resolver(lot):
            if lot.title == "Dialga" and lot.card_set == "25th Anniversary Collection":
                return canonical(
                    name="Dialga",
                    set_name="25th Anniversary Collection",
                    local_id="8",
                    full_number="8/28",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v2(
            title,
            proof_text="explicit coordinate 8/30",
            resolver=resolver,
        )
        self.assertNotEqual(result.status, "EXACT")
        self.assertIsNone(result.identity)

    def test_two_distinct_exact_partitions_are_ambiguous(self):
        title = "2025 Pokemon Japanese Alpha Beta Gamma Delta #12 PSA 10 GEM MINT"

        def resolver(lot):
            if lot.card_set == "Alpha Beta Gamma" and lot.title == "Delta":
                return canonical(
                    name="Delta",
                    set_name="Alpha Beta Gamma",
                    local_id="12",
                    full_number="12/100",
                )
            if lot.card_set == "Alpha Beta" and lot.title == "Gamma Delta":
                return canonical(
                    name="Gamma Delta",
                    set_name="Alpha Beta",
                    local_id="12",
                    full_number="12/90",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v2(title, resolver=resolver)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "multiple_exact_tcgdex_partitions")
        self.assertIsNone(result.identity)


if __name__ == "__main__":
    unittest.main()
