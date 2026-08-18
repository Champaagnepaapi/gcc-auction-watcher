from __future__ import annotations

import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm
import v4_multimarket_safety as safety
import v4_poketrace_market_retrieval as retrieval


def _lot(*, name, reference, language, series):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/poketrace-provider-bridge-test",
        title=name,
        current_price=40.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_number=reference,
        card_set=series,
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{reference}\n"
            f"Série: {series}\n"
            f"Langue: {language}\n"
            "Société de gradation: PSA\n"
            "Note: 10\n"
        ),
    )


def _canonical(
    *,
    card_id,
    set_id,
    set_name,
    local_id,
    full_number,
    name,
    language_code,
):
    return mm.CanonicalCard(
        "EXACT",
        card_id=card_id,
        set_id=set_id,
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=name,
        language_code=language_code,
        variants={"holo": True},
        reason="TCGDEX_EXACT_SET_LOCALID",
    )


def _candidate(*, name, number, set_name, game):
    return {
        "id": "pt-card",
        "name": name,
        "cardNumber": number,
        "set": {"name": set_name, "slug": "provider-set", "id": "provider-id"},
        "variant": "Holofoil",
        "productType": "single",
        "game": game,
    }


class PokeTraceProviderBridgeTests(unittest.TestCase):
    def test_japanese_retrieval_uses_exact_same_card_tcgdex_localized_name(self):
        target = _lot(
            name="Reshiram & Charizard Gx",
            reference="#016/173",
            language="Japanese",
            series="Tag All Stars",
        )
        canonical = _canonical(
            card_id="SM12a-016",
            set_id="SM12a",
            set_name="Tag All Stars",
            local_id="016",
            full_number="#016/173",
            name="Reshiram & Charizard Gx",
            language_code="ja",
        )
        detail = {
            "id": "SM12a-016",
            "localId": "016",
            "name": "レシラム&リザードンGX",
            "set": {"id": "SM12a"},
        }
        with patch.object(
            retrieval.multimarket,
            "_fetch_tcgdex_card_detail",
            return_value=(200, detail),
        ):
            context = retrieval._retrieval_context(target, canonical)

        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context.search_name, "レシラム&リザードンGX")
        self.assertEqual(context.card_number, "16/173")
        self.assertEqual(context.game, "pokemon-japanese")
        self.assertEqual(context.provider_name_aliases, ("レシラム&リザードンGX",))

    def test_localized_alias_fails_closed_on_wrong_tcgdex_coordinate(self):
        canonical = _canonical(
            card_id="SM12a-016",
            set_id="SM12a",
            set_name="Tag All Stars",
            local_id="016",
            full_number="016/173",
            name="Reshiram & Charizard Gx",
            language_code="ja",
        )
        wrong = {
            "id": "SM12a-017",
            "localId": "017",
            "name": "別カード",
            "set": {"id": "SM12a"},
        }
        with patch.object(
            retrieval.multimarket,
            "_fetch_tcgdex_card_detail",
            return_value=(200, wrong),
        ):
            self.assertEqual(
                retrieval._exact_tcgdex_localized_name(canonical, "ja"), ""
            )

    def test_localized_alias_is_scoped_to_active_exact_card(self):
        canonical = _canonical(
            card_id="SM12a-016",
            set_id="SM12a",
            set_name="Tag All Stars",
            local_id="016",
            full_number="016/173",
            name="Reshiram & Charizard Gx",
            language_code="ja",
        )
        context = retrieval.PokeTraceRetrievalContext(
            search_name="レシラム&リザードンGX",
            card_number="16/173",
            game="pokemon-japanese",
            language_code="ja",
            canonical_card_id="SM12a-016",
            provider_name_aliases=("レシラム&リザードンGX",),
        )
        self.assertFalse(
            retrieval.exact_provider_name_alias_matches(
                canonical, "レシラム&リザードンGX"
            )
        )
        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            self.assertTrue(
                retrieval.exact_provider_name_alias_matches(
                    canonical, "レシラム&リザードンGX"
                )
            )
            other = _canonical(
                card_id="SM12a-017",
                set_id="SM12a",
                set_name="Tag All Stars",
                local_id="017",
                full_number="017/173",
                name="Other",
                language_code="ja",
            )
            self.assertFalse(
                retrieval.exact_provider_name_alias_matches(
                    other, "レシラム&リザードンGX"
                )
            )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)

    def test_secret_display_suffix_requires_secret_collector_number(self):
        secret = _canonical(
            card_id="swsh4-201",
            set_id="swsh4",
            set_name="Vivid Voltage",
            local_id="201",
            full_number="201/185",
            name="Hero's Medal",
            language_code="en",
        )
        ordinary = _canonical(
            card_id="swsh4-100",
            set_id="swsh4",
            set_name="Vivid Voltage",
            local_id="100",
            full_number="100/185",
            name="Hero's Medal",
            language_code="en",
        )
        self.assertTrue(safety._provider_name_matches(secret, "Hero's Medal (Secret)"))
        self.assertFalse(
            safety._provider_name_matches(ordinary, "Hero's Medal (Secret)")
        )
        self.assertFalse(safety._provider_name_matches(secret, "Other Medal (Secret)"))

    def test_provider_catalog_prefix_is_exact_set_id_bridge_only(self):
        canonical = _canonical(
            card_id="swsh4-201",
            set_id="swsh4",
            set_name="Vivid Voltage",
            local_id="201",
            full_number="201/185",
            name="Hero's Medal",
            language_code="en",
        )
        self.assertTrue(
            safety._provider_set_id_prefix_matches(
                canonical, "SWSH04: Vivid Voltage"
            )
        )
        self.assertFalse(
            safety._provider_set_id_prefix_matches(canonical, "SWSH05: Battle Styles")
        )
        self.assertFalse(
            safety._provider_set_id_prefix_matches(canonical, "Vivid Voltage")
        )

    def test_hero_medal_live_shape_passes_only_exact_existing_gates(self):
        target = _lot(
            name="Hero's Medal",
            reference="201/185",
            language="English",
            series="Vivid Voltage",
        )
        canonical = _canonical(
            card_id="swsh4-201",
            set_id="swsh4",
            set_name="Vivid Voltage",
            local_id="201",
            full_number="201/185",
            name="Hero's Medal",
            language_code="en",
        )
        candidate = _candidate(
            name="Hero's Medal (Secret)",
            number="201/185",
            set_name="SWSH04: Vivid Voltage",
            game="pokemon",
        )
        self.assertTrue(
            safety.hardened_candidate_exact_for_canonical(target, canonical, candidate)
        )
        candidate["set"] = {"name": "SWSH05: Battle Styles"}
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(target, canonical, candidate)
        )

    def test_japanese_localized_name_plus_exact_set_prefix_passes_inside_context(self):
        target = _lot(
            name="Reshiram & Charizard Gx",
            reference="016/173",
            language="Japanese",
            series="Tag All Stars",
        )
        canonical = _canonical(
            card_id="SM12a-016",
            set_id="SM12a",
            set_name="Tag All Stars",
            local_id="016",
            full_number="016/173",
            name="Reshiram & Charizard Gx",
            language_code="ja",
        )
        candidate = _candidate(
            name="レシラム&リザードンGX",
            number="016/173",
            set_name="SM12a: Tag All Stars",
            game="pokemon-japanese",
        )
        context = retrieval.PokeTraceRetrievalContext(
            search_name="レシラム&リザードンGX",
            card_number="16/173",
            game="pokemon-japanese",
            language_code="ja",
            canonical_card_id="SM12a-016",
            provider_name_aliases=("レシラム&リザードンGX",),
        )
        self.assertFalse(
            safety.hardened_candidate_exact_for_canonical(target, canonical, candidate)
        )
        token = retrieval._ACTIVE_CONTEXT.set(context)
        try:
            self.assertTrue(
                safety.hardened_candidate_exact_for_canonical(
                    target, canonical, candidate
                )
            )
        finally:
            retrieval._ACTIVE_CONTEXT.reset(token)


if __name__ == "__main__":
    unittest.main()
