import unittest

import v4_canonical_multimarket as multimarket
from v4_global_marketplace_fanatics_native_v3 import (
    fanatics_coordinate_candidates_v3,
    resolve_fanatics_native_identity_v3,
)


def canonical(*, name, set_name, local_id, full_number, language="ja", unique=True):
    return multimarket.CanonicalCard(
        status="EXACT",
        card_id=f"test-{set_name}-{local_id}",
        set_id=f"test-{set_name}",
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=name,
        language_code=language,
        reason="TEST_EXACT",
        unique_name_number=unique,
    )


class FanaticsNativeV3Tests(unittest.TestCase):
    def test_japanese_before_pokemon_and_bare_local_number(self):
        title = "2023 Japanese Pokemon SV2a Hitmonchan Masterball 107 PSA 10"

        def resolver(lot):
            if lot.title == "Hitmonchan" and lot.card_number == "107":
                return canonical(
                    name="Hitmonchan",
                    set_name="Pokemon Card 151",
                    local_id="107",
                    full_number="107/165",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "Hitmonchan")
        self.assertEqual(result.identity.finish, "Master Ball")

    def test_jpn_abbreviation_and_fa_slash_are_explicit_not_number_conflict(self):
        title = "Pokemon 2021 JPN.SWSH VMax Climax - FA/Eevee #210 PSA 10"

        def resolver(lot):
            if lot.title == "Eevee" and lot.card_number == "210":
                return canonical(
                    name="Eevee",
                    set_name="VMAX Climax",
                    local_id="210",
                    full_number="210/184",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.name, "Eevee")

    def test_full_fraction_and_language_at_end_can_use_unique_name_number(self):
        title = "Vivillon 107/106 - Art Rare - PSA 10 - Japanese Pokémon"

        def resolver(lot):
            if lot.title == "Vivillon" and lot.card_number == "107":
                return canonical(
                    name="Vivillon",
                    set_name="Super Electric Breaker",
                    local_id="107",
                    full_number="107/106",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.number, "107/106")

    def test_no_dot_number_and_no_year_can_still_be_exact(self):
        title = "Pokémon Japanese Venusaur Holo Expansion Pack No. 003 PSA 8"

        def resolver(lot):
            if lot.title == "Venusaur" and lot.card_number == "3":
                return canonical(
                    name="Venusaur",
                    set_name="Expansion Pack",
                    local_id="3",
                    full_number="3/102",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.grade, "8")
        self.assertEqual(result.identity.finish, "Holo")

    def test_language_is_never_inferred_for_english_looking_title(self):
        candidates, reason = fanatics_coordinate_candidates_v3(
            "2026 Pokemon Ascended Heroes Pikachu ex 277 PSA 10"
        )
        self.assertEqual(candidates, [])
        self.assertEqual(reason, "explicit_language_unproven")

    def test_non_unique_catalog_result_still_requires_exact_provider_set(self):
        title = "2023 Japanese Pokemon SV2a Hitmonchan Masterball 107 PSA 10"

        def resolver(lot):
            if lot.title == "Hitmonchan":
                return canonical(
                    name="Hitmonchan",
                    set_name="Pokemon Card 151",
                    local_id="107",
                    full_number="107/165",
                    unique=False,
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertNotEqual(result.status, "EXACT")
        self.assertIsNone(result.identity)

    def test_explicit_full_fraction_conflict_stays_blocked(self):
        title = "Vivillon 107/105 - Art Rare - PSA 10 - Japanese Pokémon"

        def resolver(lot):
            if lot.title == "Vivillon":
                return canonical(
                    name="Vivillon",
                    set_name="Super Electric Breaker",
                    local_id="107",
                    full_number="107/106",
                )
            return multimarket.CanonicalCard("NO_MATCH", reason="TEST_NO_MATCH")

        result = resolve_fanatics_native_identity_v3(title, resolver=resolver)
        self.assertNotEqual(result.status, "EXACT")
        self.assertIsNone(result.identity)


if __name__ == "__main__":
    unittest.main()
