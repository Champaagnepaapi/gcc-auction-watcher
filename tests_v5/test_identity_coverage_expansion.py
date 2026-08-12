from __future__ import annotations

import unittest
from typing import Mapping

from v5.card_identity_catalog import (
    MultilingualPokemonCardResolver,
    _local_card_number_candidates,
)
from v5.ebay import (
    CardIdentity,
    card_identity_from_ebay_payload,
    is_bundle_or_multi_card_listing,
    resolve_card_identity,
)
from v5.microvariants import (
    EDITION_CONFLICT,
    EDITION_UNKNOWN,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    MICROVARIANT_NOT_REQUIRED,
    LocalMicrovariantValidator,
    MicrovariantApplicability,
    tcgdex_microvariant_applicability,
)


class IdentityCoverageExpansionTests(unittest.TestCase):
    # ----------------------------------------------------------------------
    # 1. Early Bundle / Multi-Card Detection
    # ----------------------------------------------------------------------

    def test_bundle_detection_choose_one_and_selection_phrases(self):
        """Obvious choose-one listings must be detected and rejected."""
        choose_titles = [
            "Pokemon 151 Choose Your Card / You Pick Holo & Reverse Holo",
            "Pokemon Scarlet Violet - Pick your card - Reverse Holo / Rare",
            "Cartes Pokemon 151 Choisissez votre carte au choix",
            "Pokemon Karten Wähle deine Karte Holo Reverse",
            "Carte Pokemon Scegli la tua carta Spada e Scudo",
            "Cartas Pokemon Elige tu carta Escarlata y Purpura",
            "Pokemon Select your card from list NM",
        ]
        for title in choose_titles:
            with self.subTest(title=title):
                self.assertTrue(
                    is_bundle_or_multi_card_listing({"title": title}),
                    f"Expected bundle detection for '{title}'",
                )

    def test_bundle_detection_lots_and_quantities(self):
        """Lot / collection / playset / quantity listings must be rejected."""
        bundle_titles = [
            "Lot de 50 cartes Pokemon holo rares sans double",
            "Sammlung 100 Pokemon Karten Vintage & Modern",
            "Pikachu 151 sv2a 025/165 4x Playset",
            "Pokemon 10x holo lot booster pack cards",
            "Charizard ex 151 Master Set Complete Collection",
            "Pokemon Cards Binder Collection with 200 cards",
            "Pokemon Elite Trainer Box sealed ETB",
            "Display 36 Boosters Pokemon Francais Neuf Scelle",
            "100 Pokémon Karten Deutsch | 1 EX garantiert | Reverse & Holo",
            "Cartes Pokémon Trio Cartes Grenousse Feunnec Marisson",
        ]
        for title in bundle_titles:
            with self.subTest(title=title):
                self.assertTrue(
                    is_bundle_or_multi_card_listing({"title": title}),
                    f"Expected bundle detection for '{title}'",
                )

    def test_bundle_detection_aspects_indicators(self):
        """Aspects indicating lot or multi-card quantity must trigger rejection."""
        payload_lot_yes = {
            "title": "Pikachu Holo Rare",
            "localizedAspects": [{"name": "Lot", "value": "Yes"}],
        }
        self.assertTrue(is_bundle_or_multi_card_listing(payload_lot_yes))

        payload_qty_cards = {
            "title": "Charizard Base Set",
            "localizedAspects": [{"name": "Number of Cards", "value": "25"}],
        }
        self.assertTrue(is_bundle_or_multi_card_listing(payload_qty_cards))

    def test_single_card_listing_is_not_rejected_as_bundle(self):
        """Legitimate single card listings must NOT be flagged as bundles."""
        single_titles = [
            "Charizard 4/102 Holo Base Set Pokemon Card Rare",
            "Pikachu Promo SVP 027 Scarlet & Violet Black Star",
            "Pokemon sv2a 025/165 Pikachu Holo Japanese 151",
            "Journey Together 167/159 Pikachu Illustration Rare",
            "Pokemon CS4.1C-014 Charizard VMAX Chinese",
            # Red Team required regressions:
            "Charizard Promo 121 from Tin",
            "Mint Pikachu Binder fresh",
            "Charizard aus meiner Sammlung",
            "Charizard Collection de Pikachu",
            "Charizard Collection of Pikachu",
            "Charizard 100 HP Pokemon Card Base Set",
        ]
        for title in single_titles:
            with self.subTest(title=title):
                self.assertFalse(
                    is_bundle_or_multi_card_listing({"title": title}),
                    f"Unexpected bundle detection for '{title}'",
                )

    # ----------------------------------------------------------------------
    # 2. Deterministic Title Extraction for Set Codes and Forms
    # ----------------------------------------------------------------------

    def test_extract_sv2a_set_code_and_number(self):
        """sv2a set code and collector number extraction."""
        payload = {
            "title": "Pokemon Card Pikachu sv2a 025/165 Japanese 151 Holo",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "sv2a")
        self.assertEqual(identity.card_number, "025/165")
        self.assertEqual(identity.language, "Japanese")

    def test_live_reversed_sv2a_overrides_only_generic_scarlet_violet_family(self):
        payload = {
            "title": "Charmeleon/Reptincel AR 169/165 SV2a Pokemon 151 - Pokemon Card Japanese NM",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Set", "value": "Scarlet & Violet"},
                {"name": "Card Number", "value": "169/165"},
                {"name": "Language", "value": "Japanese"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "sv2a")
        self.assertEqual(identity.card_number, "169/165")

    def test_explicit_sv_code_does_not_override_a_specific_structured_set(self):
        payload = {
            "title": "Charmeleon 169/165 SV2a Pokemon Card Japanese",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Set", "value": "Some Specific Set"},
                {"name": "Card Number", "value": "169/165"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "Some Specific Set")

    def test_extract_svp_promo_code_and_number(self):
        """SVP promo prefix and number extraction."""
        payload = {
            "title": "Pokemon Pikachu Promo SVP 027 Scarlet & Violet Black Star",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "SVP")
        self.assertEqual(identity.card_number, "027")

    def test_extract_chinese_cs_set_code_and_number(self):
        """Simplified Chinese set code CS4.1C-014 extraction."""
        payload = {
            "title": "Pokemon Charizard CS4.1C-014 Simplified Chinese",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "CS4.1C")
        self.assertEqual(identity.card_number, "014")

    def test_extract_csv_chinese_set_code_and_number(self):
        payload = {
            "title": "Pokemon TCG Chinesisch Nachtara ex SAR CSV9.5C-239/208 Holo NM",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "CSV9.5C")
        self.assertEqual(identity.card_number, "239/208")

    def test_extract_csv_chinese_set_code_and_number_with_space(self):
        payload = {
            "title": "Pokémon TCG S-Chinesische Feelinara Sylveon ex CSV9.5C 233/208 SAR Holo NM",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "CSV9.5C")
        self.assertEqual(identity.card_number, "233/208")

    def test_extract_journey_together_canonical_set_and_fractional_number(self):
        """Journey Together 167/159 set name and fractional collector number extraction."""
        payload = {
            "title": "Pokemon Journey Together 167/159 Pikachu Illustration Rare English",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        identity = resolve_card_identity(payload).identity
        self.assertEqual(identity.set, "Journey Together")
        self.assertEqual(identity.card_number, "167/159")
        self.assertEqual(identity.language, "English")

    def test_local_card_number_candidates_covers_promo_and_stripped_variants(self):
        """_local_card_number_candidates should deterministically produce case/unpadded variants."""
        svp_candidates = _local_card_number_candidates("027")
        self.assertIn("027", svp_candidates)
        self.assertIn("27", svp_candidates)

        frac_candidates = _local_card_number_candidates("027/165")
        self.assertIn("027", frac_candidates)
        self.assertIn("27", frac_candidates)

    # ----------------------------------------------------------------------
    # 3. Real Catalog Proof for Microvariant Relevance
    # ----------------------------------------------------------------------

    def test_single_compatible_finish_proves_unknown_listing_finish_is_non_blocking(self):
        """When catalog proves only 1 finish exists (e.g. holo only), unknown listing finish is non-blocking."""
        card_data = {
            "id": "sv2a-151",
            "variants": {
                "normal": False,
                "reverse": False,
                "holo": True,
                "firstEdition": False,
            },
        }
        applicability = tcgdex_microvariant_applicability(card_data)
        self.assertEqual(applicability.status, MICROVARIANT_NOT_APPLICABLE)
        self.assertTrue(applicability.finish_proven_single)
        self.assertEqual(applicability.single_finish, "holofoil")
        self.assertTrue(applicability.edition_proven_single)

        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Mew ex",
            set="sv2a",
            card_number="151/165",
            language="Japanese",
            finish=None,  # Unknown finish on listing
            edition=None,  # Unknown edition on listing
        )
        provider_candidate = {
            "id": "pt-151",
            "variant": "Holofoil",
            "set": {"name": "151"},
        }
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            target_identity,
            applicability=applicability,
            candidate=provider_candidate,
        )
        # Proven single-compatible: economics is NOT blocked!
        self.assertFalse(resolution.blocks_economics)
        self.assertEqual(resolution.edition_status, MICROVARIANT_NOT_REQUIRED)

    def test_exact_single_detailed_tcgdex_variant_can_prove_stufful_holo_finish(self):
        applicability = tcgdex_microvariant_applicability(
            {
                "id": "me01-154",
                "variants_detailed": [
                    {"type": "holo", "size": "standard"},
                ],
            }
        )
        self.assertEqual(applicability.source, "TCGDEX_EXACT")
        self.assertEqual(applicability.status, MICROVARIANT_NOT_APPLICABLE)
        self.assertTrue(applicability.finish_proven_single)
        self.assertEqual(applicability.single_finish, "holofoil")
        self.assertTrue(applicability.edition_proven_single)

    def test_detailed_tcgdex_variant_fallback_stays_closed_when_not_simple_and_unique(self):
        ambiguous = tcgdex_microvariant_applicability(
            {
                "id": "fixture",
                "variants_detailed": [
                    {"type": "normal"},
                    {"type": "holo"},
                ],
            }
        )
        stamped = tcgdex_microvariant_applicability(
            {
                "id": "fixture",
                "variants_detailed": [
                    {"type": "holo", "stamp": ["pokemon-center"]},
                ],
            }
        )
        self.assertEqual(ambiguous.source, "UNAVAILABLE")
        self.assertFalse(ambiguous.finish_proven_single)
        self.assertEqual(stamped.source, "UNAVAILABLE")
        self.assertFalse(stamped.finish_proven_single)

    def test_multiple_catalog_finishes_remain_fail_closed_when_listing_finish_is_unknown(self):
        """When catalog proves multiple finishes (normal + reverse), unknown listing finish blocks economics."""
        card_data = {
            "id": "sv2a-025",
            "variants": {
                "normal": True,
                "reverse": True,
                "holo": False,
                "firstEdition": False,
            },
        }
        applicability = tcgdex_microvariant_applicability(card_data)
        self.assertTrue(applicability.finish_multiple_variants)
        self.assertFalse(applicability.finish_proven_single)

        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Pikachu",
            set="sv2a",
            card_number="025/165",
            language="Japanese",
            finish=None,  # Unknown on listing
            edition=None,
        )
        provider_candidate = {
            "id": "pt-025",
            "variant": "Normal",
            "set": {"name": "151"},
        }
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            target_identity,
            applicability=applicability,
            candidate=provider_candidate,
        )
        # Multiple compatible finishes exist commercially: must stay fail-closed!
        self.assertTrue(resolution.blocks_economics)
        self.assertEqual(resolution.edition_status, EDITION_UNKNOWN)

    def test_vintage_first_edition_applicable_remains_fail_closed_when_edition_is_unknown(self):
        """When 1st edition is applicable (Base Set), unknown edition on listing blocks economics."""
        card_data = {
            "id": "base-4",
            "variants": {
                "normal": False,
                "reverse": False,
                "holo": True,
                "firstEdition": True,
            },
        }
        applicability = tcgdex_microvariant_applicability(card_data)
        self.assertEqual(applicability.status, MICROVARIANT_APPLICABLE)
        self.assertTrue(applicability.edition_multiple_variants)

        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            finish="holo",
            edition=None,  # Unknown edition on listing
        )
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            target_identity,
            applicability=applicability,
            candidate={"variant": "1st Edition Holofoil"},
        )
        self.assertTrue(resolution.blocks_economics)
        self.assertEqual(resolution.edition_status, EDITION_UNKNOWN)

    def test_provider_metadata_never_establishes_single_variant_proof_without_catalog(self):
        """Provider candidate variant must never bypass block when catalog proof is missing."""
        empty_applicability = MicrovariantApplicability()  # UNAVAILABLE
        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            finish=None,
            edition=None,
        )
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            target_identity,
            applicability=empty_applicability,
            candidate={"variant": "Holofoil"},
        )
        self.assertTrue(resolution.blocks_economics)
        self.assertEqual(resolution.edition_status, EDITION_UNKNOWN)

    def test_unknown_and_malformed_catalog_applicability_strictly_fails_closed(self):
        """UNKNOWN, missing, or malformed catalog applicability MUST remain blocks_economics=True."""
        validator = LocalMicrovariantValidator()
        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Pikachu",
            set="Crown Zenith",
            card_number="160/159",
            language="English",
            finish=None,
            edition=None,
        )
        for malformed in [
            MicrovariantApplicability(),
            MicrovariantApplicability(status="MICROVARIANT_APPLICABILITY_UNKNOWN", source="UNAVAILABLE"),
            MicrovariantApplicability(status="MALFORMED_STATUS", source="UNAVAILABLE"),
            MicrovariantApplicability(status="MICROVARIANT_APPLICABLE", source="UNAVAILABLE"),
            MicrovariantApplicability(
                status=MICROVARIANT_NOT_APPLICABLE,
                source="TEST_CATALOG",
                finish_proven_single=True,
                single_finish="holofoil",
                edition_proven_single=True,
            ),
        ]:
            with self.subTest(applicability=malformed):
                res = validator.resolve(target_identity, applicability=malformed, candidate={"variant": "Normal"})
                self.assertTrue(res.blocks_economics)

    def test_provider_metadata_never_determines_materialness_or_single_compatible(self):
        """Provider candidate saying 'Normal' or 'Holofoil' cannot make a multi-finish card non-blocking."""
        validator = LocalMicrovariantValidator()
        # Catalog proves multiple finishes exist
        multi_card_data = {
            "id": "sv1-025",
            "variants": {
                "normal": True,
                "reverse": True,
                "holo": False,
                "firstEdition": False,
            },
        }
        applicability = tcgdex_microvariant_applicability(multi_card_data)
        target_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Pikachu",
            set="Scarlet & Violet",
            card_number="025/198",
            language="English",
            finish=None,
            edition=None,
        )
        # Even if candidate says "Normal", it cannot bypass the block because listing finish is unknown
        res = validator.resolve(
            target_identity,
            applicability=applicability,
            candidate={"variant": "Normal"},
        )
        self.assertTrue(res.blocks_economics)

    def test_generic_151_excluded_from_canonical_set_inference(self):
        """Title containing only '151' without set code (e.g. sv2a) must not infer set='151'."""
        payload = {
            "title": "Pokemon 151 Pikachu Rare",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertIsNone(res.identity.set)

    # ----------------------------------------------------------------------
    # 4. Live V5 #24 Regressions (Records #8, #9, #13, #14, #19)
    # ----------------------------------------------------------------------

    def test_live24_record_8_sv2a_169_165_extraction(self):
        payload = {
            "title": "Pokemon Charmeleon sv2a 169/165 Japanese 151",
            "localizedAspects": [{"name": "Game", "value": "Pokémon TCG"}],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "sv2a")
        self.assertEqual(res.identity.card_number, "169/165")

    def test_live24_record_9_journey_together_167_159_extraction(self):
        payload = {
            "title": "Pokemon N's Reshiram Journey Together 167/159 English",
            "localizedAspects": [{"name": "Game", "value": "Pokémon TCG"}],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "Journey Together")
        self.assertEqual(res.identity.card_number, "167/159")

    def test_live24_record_13_svp_027_extraction(self):
        payload = {
            "title": "Pikachu SVP 027 Black Star Promo English",
            "localizedAspects": [{"name": "Game", "value": "Pokémon TCG"}],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "SVP")
        self.assertEqual(res.identity.card_number, "027")

    def test_live24_record_14_cs4_1c_014_extraction(self):
        payload = {
            "title": "Pokemon Centiskorch CS4.1C-014 Simplified Chinese",
            "localizedAspects": [{"name": "Game", "value": "Pokémon TCG"}],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "CS4.1C")
        self.assertEqual(res.identity.card_number, "014")

    def test_regression_v5_record_8_promo_code_extraction(self):
        """Record #8 regression: Promo code SVP 027 extracted from title."""
        payload = {
            "title": "Pikachu SVP 027 Black Star Promo Card Sealed Mint",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Language", "value": "English"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "SVP")
        self.assertEqual(res.identity.card_number, "027")

    def test_regression_v5_record_9_visual_rescued_single_finish_not_blocked(self):
        """Record #9 regression: Rescued modern card with single catalog finish passes microvariant gate."""
        rescued_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Mew ex",
            set="151",
            card_number="151/165",
            language="English",
            finish=None,
            edition=None,
        )
        catalog_card = {
            "id": "me-151",
            "variants": {
                "normal": False,
                "reverse": False,
                "holo": True,
                "firstEdition": False,
            },
        }
        applicability = tcgdex_microvariant_applicability(catalog_card)
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            rescued_identity,
            applicability=applicability,
            candidate={"variant": "Holofoil"},
        )
        self.assertFalse(resolution.blocks_economics)

    def test_regression_v5_record_13_choose_one_bundle_early_rejected(self):
        """Record #13 regression: Choose-one / lot listing is rejected early."""
        payload = {
            "title": "Pokemon 151 Choose Your Card Holo Reverse Normal - Pick 1",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
            ],
        }
        self.assertTrue(is_bundle_or_multi_card_listing(payload))

    def test_regression_v5_record_14_single_finish_not_blocked_after_rescue(self):
        """Record #14 regression: Modern Illustration Rare with single holo finish passes microvariant gate."""
        rescued_identity = CardIdentity(
            game="Pokemon TCG",
            card_name="Dragonite V",
            set="Evolving Skies",
            card_number="192/203",
            language="English",
            finish=None,
            edition=None,
        )
        catalog_card = {
            "id": "swsh7-192",
            "variants": {
                "normal": False,
                "reverse": False,
                "holo": True,
                "firstEdition": False,
            },
        }
        applicability = tcgdex_microvariant_applicability(catalog_card)
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(
            rescued_identity,
            applicability=applicability,
            candidate={"variant": "Ultra Rare Holofoil"},
        )
        self.assertFalse(resolution.blocks_economics)

    def test_regression_v5_record_19_journey_together_fractional_title_extraction(self):
        """Record #19 regression: Journey Together 167/159 set name and card number extracted from title."""
        payload = {
            "title": "Pokemon Journey Together 167/159 Pikachu Illustration Rare NM",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Language", "value": "English"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "Journey Together")
        self.assertEqual(res.identity.card_number, "167/159")


if __name__ == "__main__":
    unittest.main()
