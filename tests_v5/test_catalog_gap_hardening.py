from __future__ import annotations

import unittest

from v5.card_identity_catalog import CatalogIdentityResult, HybridPokemonCardResolver
from v5.catalog_gap_registry import resolve_curated_catalog_gap
from v5.ebay import is_non_physical_pokemon_listing
from v5.microvariants import LocalMicrovariantValidator, MicrovariantApplicability
from v5.models import CardIdentity


class _NoPokeTraceIdentity:
    def has_deterministic_alias(self, identity):
        return False


class _NoNetworkHybrid(HybridPokemonCardResolver):
    def _resolve_tcgdex(self, identity):
        return CatalogIdentityResult(identity=identity)

    def _resolve_pokemon_tcg(self, identity):
        raise AssertionError("curated exact gap must resolve before network fallback")


class CatalogGapHardeningTests(unittest.TestCase):
    def test_tcg_pocket_structured_game_is_non_physical(self):
        payload = {
            "title": "Pokémon Center Lady - Pokemon TCG Pocket - Full Art ⭐⭐ - English - Fast ✅",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG Pocket"},
                {"name": "Set", "value": "TCG Pocket"},
                {"name": "Card Number", "value": "089"},
            ],
        }
        self.assertTrue(is_non_physical_pokemon_listing(payload))

    def test_tcg_pocket_account_title_is_non_physical(self):
        payload = {"title": "Pokémon TCG Pocket Account | 6300 Hourglass [ Instant ]"}
        self.assertTrue(is_non_physical_pokemon_listing(payload))

    def test_physical_pokemon_tcg_listing_is_not_rejected(self):
        payload = {
            "title": "Pokemon Magikarp 040/M-P Korea Mega Festa 2026 Promo Card",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Set", "value": "Promo Cards"},
            ],
        }
        self.assertFalse(is_non_physical_pokemon_listing(payload))

    def _magikarp_identity(self, **changes):
        values = dict(
            game="Pokémon TCG",
            card_name="Magikarp",
            set="Promo Cards",
            card_number="040/M-P",
            year=2026,
            language="Korean",
        )
        values.update(changes)
        return CardIdentity(**values)

    def test_exact_korean_magikarp_gap_resolves_with_holo_applicability(self):
        match = resolve_curated_catalog_gap(self._magikarp_identity())
        self.assertIsNotNone(match)
        self.assertEqual(match.identity.set, "M-P Promotional cards")
        self.assertEqual(match.identity.card_number, "040/M-P")
        self.assertEqual(match.identity.language, "Korean")
        self.assertTrue(match.applicability.finish_proven_single)
        self.assertEqual(match.applicability.single_finish, "holofoil")
        self.assertTrue(match.applicability.promo_proven_single)
        self.assertTrue(match.applicability.single_promo)

    def test_exact_gap_can_resolve_only_game_ambiguity(self):
        identity = self._magikarp_identity(
            game=None,
            ambiguities=("game: valeurs contradictoires (Pokémon TCG, Pokémon)",),
        )
        match = resolve_curated_catalog_gap(identity)
        self.assertIsNotNone(match)
        self.assertEqual(match.identity.game, "Pokémon TCG")
        self.assertEqual(match.identity.ambiguities, ())

    def test_exact_gap_does_not_clear_other_ambiguity(self):
        identity = self._magikarp_identity(
            ambiguities=("finish: valeurs contradictoires (Holo, Reverse)",),
        )
        self.assertIsNone(resolve_curated_catalog_gap(identity))

    def test_exact_gap_fail_closed_wrong_language_number_or_set(self):
        self.assertIsNone(
            resolve_curated_catalog_gap(self._magikarp_identity(language="English"))
        )
        self.assertIsNone(
            resolve_curated_catalog_gap(self._magikarp_identity(card_number="041/M-P"))
        )
        self.assertIsNone(
            resolve_curated_catalog_gap(self._magikarp_identity(set="Paldea Evolved"))
        )

    def test_hybrid_wires_curated_gap_before_other_fallbacks(self):
        resolver = _NoNetworkHybrid(poketrace_identity_resolver=_NoPokeTraceIdentity())
        result = resolver.resolve_identity(self._magikarp_identity())
        self.assertTrue(result.matched)
        self.assertFalse(result.ambiguous)
        self.assertEqual(result.source, "CURATED_EXACT_CATALOG")
        self.assertEqual(result.identity.set, "M-P Promotional cards")

    def test_curated_exact_applicability_can_unblock_unknown_finish(self):
        match = resolve_curated_catalog_gap(self._magikarp_identity())
        self.assertIsNotNone(match)
        result = LocalMicrovariantValidator().resolve(
            match.identity,
            match.applicability,
        )
        self.assertFalse(result.blocks_economics)

    def test_curated_exact_applicability_blocks_finish_conflict(self):
        match = resolve_curated_catalog_gap(
            self._magikarp_identity(finish="Reverse Holo")
        )
        self.assertIsNotNone(match)
        result = LocalMicrovariantValidator().resolve(
            match.identity,
            match.applicability,
        )
        self.assertTrue(result.blocks_economics)

    def test_untrusted_shadow_metadata_cannot_unblock(self):
        identity = self._magikarp_identity()
        shadow = MicrovariantApplicability(
            status="MICROVARIANT_NOT_APPLICABLE",
            source="POKEMON_PRICE_TRACKER_SHADOW",
            single_finish="holofoil",
            finish_proven_single=True,
            edition_proven_single=True,
        )
        result = LocalMicrovariantValidator().resolve(identity, shadow)
        self.assertTrue(result.blocks_economics)


if __name__ == "__main__":
    unittest.main()
