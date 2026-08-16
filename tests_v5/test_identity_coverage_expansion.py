from __future__ import annotations

import unittest
from typing import Mapping

from v5.card_identity_catalog import (
    MultilingualPokemonCardResolver,
    _local_card_number_candidates,
)
from v5.ebay import (
    CardIdentity,
    canonicalize_chinese_card_number,
    card_identity_from_ebay_payload,
    extract_title_edition,
    extract_title_finish,
    is_bundle_or_multi_card_listing,
    resolve_card_identity,
)
from v5.live_raw_pipeline import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_INSUFFICIENT,
    IDENTITY_OK,
    identity_status,
)
from v5.variant_semantics import (
    EDITION_FIRST,
    EDITION_SHADOWLESS,
    EDITION_UNLIMITED,
    FINISH_HOLO,
    FINISH_REVERSE,
    FINISH_STANDARD,
    semantics_from_identity,
    semantics_from_text,
)
from v5.microvariants import (
    EDITION_CONFLICT,
    EDITION_UNKNOWN,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    MICROVARIANT_NOT_REQUIRED,
    UNLIMITED_CONFIRMED,
    EditionRegionEvidence,
    LocalMicrovariantValidator,
    MicrovariantApplicability,
    tcgdex_microvariant_applicability,
)
from v5.identity_observability import (
    VARIANT_FINISH_UNKNOWN,
    VARIANT_FIRST_EDITION_UNKNOWN,
    VARIANT_SINGLE_COMPATIBLE,
    VARIANT_UNKNOWN_FIELD_ONLY,
    analyze_variant_blocking,
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

    def test_chinese_card_number_canonicalization_rules(self):
        # CSV9.5C + CSV9.5C-233/208 -> 233/208
        self.assertEqual(
            canonicalize_chinese_card_number("CSV9.5C", "CSV9.5C-233/208"),
            "233/208",
        )
        # CSV10C + CSV10C-268/222 -> 268/222
        self.assertEqual(
            canonicalize_chinese_card_number("CSV10C", "CSV10C-268/222"),
            "268/222",
        )
        # Underscore separator
        self.assertEqual(
            canonicalize_chinese_card_number("CSV9.5C", "CSV9.5C_014"),
            "014",
        )
        # CS4.1C + CS4.1C-014 -> 014
        self.assertEqual(
            canonicalize_chinese_card_number("CS4.1C", "CS4.1C-014"),
            "014",
        )
        # Mismatched set prefix -> untouched
        self.assertEqual(
            canonicalize_chinese_card_number("CSV9C", "CSV9.5C-233/208"),
            "CSV9.5C-233/208",
        )
        # Non-Chinese set code -> untouched
        self.assertEqual(
            canonicalize_chinese_card_number("SVP", "SVP-027"),
            "SVP-027",
        )
        self.assertEqual(
            canonicalize_chinese_card_number("Base Set", "Base-004"),
            "Base-004",
        )
        # Non-bounded / invalid collector suffix -> untouched
        self.assertEqual(
            canonicalize_chinese_card_number("CSV9.5C", "CSV9.5C-INVALID"),
            "CSV9.5C-INVALID",
        )

    def test_chinese_prefixed_card_number_in_ebay_aspects(self):
        payload = {
            "title": "Pokemon Chinese Booster Fresh Card",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Set", "value": "CSV9.5C"},
                {"name": "Card Number", "value": "CSV9.5C-233/208"},
                {"name": "Language", "value": "Chinese"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.set, "CSV9.5C")
        self.assertEqual(res.identity.card_number, "233/208")

        payload2 = {
            "title": "Pokemon Chinese Card",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Set", "value": "CSV10C"},
                {"name": "Card Number", "value": "CSV10C-268/222"},
                {"name": "Language", "value": "Chinese"},
            ],
        }
        res2 = resolve_card_identity(payload2)
        self.assertEqual(res2.identity.set, "CSV10C")
        self.assertEqual(res2.identity.card_number, "268/222")

    # ----------------------------------------------------------------------
    # 5. Explicit Title Finish Evidence & Conflict Handling
    # ----------------------------------------------------------------------

    def test_title_finish_sylveon_sar_holo_extracts_holofoil(self):
        """Sylveon ex SAR Holo -> finish Holo extracted (holofoil), SAR ignored."""
        payload = {
            "title": "Pokémon TCG Sylveon ex SAR Holo CSV9.5C-233/208",
            "localizedAspects": {},
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.finish, "Holo")
        semantics, is_ambiguous = semantics_from_identity(res.identity)
        self.assertFalse(is_ambiguous)
        self.assertEqual(semantics.finish, FINISH_HOLO)
        self.assertIsNone(semantics.special_finish)

    def test_title_finish_non_holo_extracts_standard(self):
        """Non-Holo -> standard finish, and Holo token inside Non-Holo is not matched."""
        variants = [
            "Pikachu 025/165 Non-Holo Scarlet & Violet 151",
            "Pikachu 025/165 Non Holo Scarlet & Violet 151",
            "Pikachu 025/165 Nonholo Scarlet & Violet 151",
        ]
        for title in variants:
            with self.subTest(title=title):
                payload = {"title": title, "localizedAspects": {}}
                res = resolve_card_identity(payload)
                self.assertEqual(res.identity.finish, "Non-Holo")
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertEqual(semantics.finish, FINISH_STANDARD)
                self.assertNotEqual(semantics.finish, FINISH_HOLO)

    def test_title_finish_reverse_holo_extracts_reverse(self):
        """Reverse Holo -> reverse_holofoil, not generic holofoil."""
        variants = [
            "Mewtwo Reverse Holo 150/165 Pokemon 151",
            "Mewtwo Reverse-Holo 150/165 Pokemon 151",
            "Mewtwo Reverse Holofoil 150/165 Pokemon 151",
        ]
        for title in variants:
            with self.subTest(title=title):
                payload = {"title": title, "localizedAspects": {}}
                res = resolve_card_identity(payload)
                self.assertEqual(res.identity.finish, "Reverse Holo")
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertEqual(semantics.finish, FINISH_REVERSE)

    def test_title_finish_holofoil_and_holographic(self):
        """Holofoil, Holographic, and French Holographique map to holofoil."""
        variants = [
            ("Charizard Holofoil 4/102 Base Set", FINISH_HOLO),
            ("Charizard Holographic 4/102 Base Set", FINISH_HOLO),
            ("Dracaufeu Holographique 4/102 Set de Base", FINISH_HOLO),
        ]
        for title, expected_finish in variants:
            with self.subTest(title=title):
                payload = {"title": title, "localizedAspects": {}}
                res = resolve_card_identity(payload)
                self.assertEqual(res.identity.finish, "Holo")
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertEqual(semantics.finish, expected_finish)

    def test_title_special_finishes_not_collapsed_to_generic(self):
        """Special finishes populate their exact special_finish semantic value."""
        cases = [
            ("Pikachu Master Ball Reverse 025/165 Japanese sv2a", FINISH_REVERSE, "masterball_reverse"),
            ("Pikachu Poké Ball Reverse 025/165 Japanese sv2a", FINISH_REVERSE, "pokeball_reverse"),
            ("Pikachu Poke Ball Reverse 025/165 Japanese sv2a", FINISH_REVERSE, "pokeball_reverse"),
            ("Pikachu Cosmos Holo 025/165 Promo", FINISH_HOLO, "cosmos_holo"),
            ("Pikachu Galaxy Holo 025/165 Promo", FINISH_HOLO, "galaxy_holo"),
            ("Pikachu Cracked Ice Holo 025/165 Promo", FINISH_HOLO, "cracked_ice_holo"),
            ("Pikachu Stamped Holo 025/165 Promo", FINISH_HOLO, "stamped_holo"),
        ]
        for title, exp_finish, exp_special in cases:
            with self.subTest(title=title):
                payload = {"title": title, "localizedAspects": {}}
                res = resolve_card_identity(payload)
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertEqual(semantics.finish, exp_finish)
                self.assertEqual(semantics.special_finish, exp_special)

    def test_rarity_labels_alone_never_prove_finish(self):
        """SAR, AR, SR, IR, SIR, UR, HR, CHR, CSR, TG, GG alone must never prove finish."""
        rarities = ["SAR", "AR", "SR", "IR", "SIR", "UR", "HR", "CHR", "CSR", "TG", "GG"]
        for r in rarities:
            with self.subTest(rarity=r):
                payload = {
                    "title": f"Sylveon ex {r} CSV9.5C-233/208 Chinese",
                    "localizedAspects": {},
                }
                res = resolve_card_identity(payload)
                self.assertIsNone(res.identity.finish)
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertIsNone(semantics.finish)

    def test_generic_words_alone_never_create_finish(self):
        """'foil', 'reverse', 'normal', 'standard' alone must never produce finish evidence."""
        generic_words = ["foil", "reverse", "normal", "standard"]
        for w in generic_words:
            with self.subTest(word=w):
                payload = {
                    "title": f"Charizard {w} 006/165 Pokemon Card",
                    "localizedAspects": {},
                }
                res = resolve_card_identity(payload)
                self.assertIsNone(res.identity.finish)
                semantics, is_ambiguous = semantics_from_identity(res.identity)
                self.assertFalse(is_ambiguous)
                self.assertIsNone(semantics.finish)

    def test_structured_finish_retained_on_title_agreement(self):
        """Structured finish is authoritative and retained when title agrees."""
        payload = {
            "title": "Gengar Holo 094/165 Pokemon 151",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Gengar"},
                {"name": "Set", "value": "151"},
                {"name": "Card Number", "value": "094/165"},
                {"name": "Finish", "value": "Holo"},
                {"name": "Language", "value": "English"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.finish, "Holo")
        self.assertEqual(identity_status(res.identity), IDENTITY_OK)
        self.assertEqual(len(res.identity.ambiguities), 0)

    def test_structured_finish_conflicts_with_title_fails_closed(self):
        """Structured finish conflicting with explicit title finish must mark AMBIGUOUS."""
        # Structured Reverse Holo vs Title Holo
        payload_rev_vs_holo = {
            "title": "Gengar Holo 094/165 Pokemon 151",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Gengar"},
                {"name": "Set", "value": "151"},
                {"name": "Card Number", "value": "094/165"},
                {"name": "Finish", "value": "Reverse Holo"},
            ],
        }
        res1 = resolve_card_identity(payload_rev_vs_holo)
        self.assertEqual(identity_status(res1.identity), IDENTITY_AMBIGUOUS)
        self.assertTrue(any("finish:" in amb.lower() for amb in res1.identity.ambiguities))

        # Structured Holo vs Title Non-Holo
        payload_holo_vs_non = {
            "title": "Gengar Non-Holo 094/165 Pokemon 151",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Gengar"},
                {"name": "Set", "value": "151"},
                {"name": "Card Number", "value": "094/165"},
                {"name": "Finish", "value": "Holo"},
            ],
        }
        res2 = resolve_card_identity(payload_holo_vs_non)
        self.assertEqual(identity_status(res2.identity), IDENTITY_AMBIGUOUS)
        self.assertTrue(any("finish:" in amb.lower() for amb in res2.identity.ambiguities))

    def test_title_contradictory_finishes_fails_closed(self):
        """Multiple contradictory finishes in title must fail closed."""
        payload = {
            "title": "Gengar Non-Holo Reverse Holo 094/165",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Gengar"},
                {"name": "Set", "value": "151"},
                {"name": "Card Number", "value": "094/165"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(identity_status(res.identity), IDENTITY_AMBIGUOUS)
        self.assertTrue(any("finish:" in amb.lower() for amb in res.identity.ambiguities))


    def test_structured_holo_with_title_cosmos_holo_preserves_cosmos_holo(self):
        """Structured generic Holo + title Cosmos Holo preserves material cosmos_holo."""
        payload = {
            "title": "Pikachu Cosmos Holo 025/165 Promo",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Pikachu"},
                {"name": "Set", "value": "Scarlet & Violet Promos"},
                {"name": "Card Number", "value": "SVP 025"},
                {"name": "Language", "value": "English"},
                {"name": "Finish", "value": "Holo"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.finish, "Cosmos Holo")
        semantics, is_ambiguous = semantics_from_identity(res.identity)
        self.assertFalse(is_ambiguous)
        self.assertEqual(semantics.finish, FINISH_HOLO)
        self.assertEqual(semantics.special_finish, "cosmos_holo")
        self.assertEqual(identity_status(res.identity), IDENTITY_OK)
        self.assertEqual(len(res.identity.ambiguities), 0)

    def test_structured_reverse_holo_with_title_masterball_reverse_preserves_masterball(self):
        """Structured generic Reverse Holo + title Master Ball Reverse preserves masterball_reverse."""
        payload = {
            "title": "Pikachu Master Ball Reverse 025/165 sv2a",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Pikachu"},
                {"name": "Set", "value": "sv2a"},
                {"name": "Card Number", "value": "025/165"},
                {"name": "Language", "value": "Japanese"},
                {"name": "Finish", "value": "Reverse Holo"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(res.identity.finish, "Master Ball Reverse")
        semantics, is_ambiguous = semantics_from_identity(res.identity)
        self.assertFalse(is_ambiguous)
        self.assertEqual(semantics.finish, FINISH_REVERSE)
        self.assertEqual(semantics.special_finish, "masterball_reverse")
        self.assertEqual(identity_status(res.identity), IDENTITY_OK)
        self.assertEqual(len(res.identity.ambiguities), 0)

    def test_structured_non_holo_with_title_cosmos_holo_fails_closed(self):
        """Structured Non-Holo + title Cosmos Holo is an explicit conflict and must fail closed."""
        payload = {
            "title": "Pikachu Cosmos Holo 025/165 Promo",
            "localizedAspects": [
                {"name": "Game", "value": "Pokémon TCG"},
                {"name": "Character", "value": "Pikachu"},
                {"name": "Set", "value": "Scarlet & Violet Promos"},
                {"name": "Card Number", "value": "SVP 025"},
                {"name": "Language", "value": "English"},
                {"name": "Finish", "value": "Non-Holo"},
            ],
        }
        res = resolve_card_identity(payload)
        self.assertEqual(identity_status(res.identity), IDENTITY_AMBIGUOUS)
        self.assertTrue(any("finish:" in amb.lower() for amb in res.identity.ambiguities))

    def test_special_finish_span_masking_consumes_trailing_holo_and_holofoil(self):
        """Special finish phrases containing trailing holo tokens must not leave orphan holo."""
        cases = [
            ("Pikachu Master Ball Reverse Holo 025/165", "Master Ball Reverse", FINISH_REVERSE, "masterball_reverse"),
            ("Pikachu Master Ball Reverse Holofoil 025/165", "Master Ball Reverse", FINISH_REVERSE, "masterball_reverse"),
            ("Pikachu Masterball Reverse Holo 025/165", "Master Ball Reverse", FINISH_REVERSE, "masterball_reverse"),
            ("Pikachu Poké Ball Reverse Holo 025/165", "Poké Ball Reverse", FINISH_REVERSE, "pokeball_reverse"),
            ("Pikachu Poké Ball Reverse Holofoil 025/165", "Poké Ball Reverse", FINISH_REVERSE, "pokeball_reverse"),
            ("Pikachu Poke Ball Reverse Holo 025/165", "Poké Ball Reverse", FINISH_REVERSE, "pokeball_reverse"),
            ("Pikachu Cosmos Holofoil 025/165", "Cosmos Holo", FINISH_HOLO, "cosmos_holo"),
            ("Pikachu Galaxy Holographic 025/165", "Galaxy Holo", FINISH_HOLO, "galaxy_holo"),
            ("Pikachu Cracked Ice Holofoil 025/165", "Cracked Ice Holo", FINISH_HOLO, "cracked_ice_holo"),
            ("Pikachu Stamped Holofoil 025/165", "Stamped Holo", FINISH_HOLO, "stamped_holo"),
        ]
        for title, exp_display, exp_finish, exp_special in cases:
            with self.subTest(title=title):
                finish, contra = extract_title_finish(title)
                self.assertFalse(contra, f"Unexpected contradiction in title: {title}")
                self.assertEqual(finish, exp_display)
                sem = semantics_from_text(finish)
                self.assertEqual(sem.finish, exp_finish)
                self.assertEqual(sem.special_finish, exp_special)

    def test_pokeball_reverse_regex_is_tightened(self):
        """Poké Ball reverse matches exact poke/poké forms and not typo strings like polkeball."""
        valid_titles = [
            "Pikachu Poké Ball Reverse 025/165",
            "Pikachu Poke Ball Reverse 025/165",
            "Pikachu Pokéball Reverse 025/165",
            "Pikachu Pokeball Reverse 025/165",
        ]
        for title in valid_titles:
            with self.subTest(title=title):
                finish, contra = extract_title_finish(title)
                self.assertFalse(contra)
                self.assertEqual(finish, "Poké Ball Reverse")

        invalid_title = "Pikachu Polkeball Reverse 025/165"
        finish, contra = extract_title_finish(invalid_title)
        # Should not match as Poké Ball Reverse
        self.assertNotEqual(finish, "Poké Ball Reverse")

    # ----------------------------------------------------------------------
    # 7. Explicit eBay Title Edition Parsing and Reconciliation
    # ----------------------------------------------------------------------

    def test_title_edition_extraction_english(self):
        """English explicit edition phrases must resolve to canonical edition names."""
        cases = [
            ("Charizard 4/102 1st Edition Base Set Holo", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 First Edition Base Set Holo", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 1st ed Base Set Holo", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 1st ed. Base Set Holo", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 Shadowless Base Set Holo", "Shadowless", EDITION_SHADOWLESS),
            ("Charizard 4/102 Unlimited Base Set Holo", "Unlimited", EDITION_UNLIMITED),
        ]
        for title, exp_display, exp_edition in cases:
            with self.subTest(title=title):
                edition, contra = extract_title_edition(title)
                self.assertFalse(contra, f"Unexpected contradiction in title: {title}")
                self.assertEqual(edition, exp_display)
                sem = semantics_from_text(edition)
                self.assertEqual(sem.edition, exp_edition)

    def test_title_edition_extraction_multilingual(self):
        """Multilingual explicit edition phrases (FR, DE, IT, ES) must resolve safely."""
        cases = [
            ("Dracaufeu 4/102 1ère Édition Base Set", "1st Edition", EDITION_FIRST),
            ("Dracaufeu 4/102 1ere Edition Set de Base", "1st Edition", EDITION_FIRST),
            ("Dracaufeu 4/102 Première Édition", "1st Edition", EDITION_FIRST),
            ("Dracaufeu 4/102 Illimitée Set de Base", "Unlimited", EDITION_UNLIMITED),
            ("Glurak 4/102 1. Auflage Basis Set", "1st Edition", EDITION_FIRST),
            ("Glurak 4/102 1. Edition Basis Set", "1st Edition", EDITION_FIRST),
            ("Glurak 4/102 1 Auflage Basis Set", "1st Edition", EDITION_FIRST),
            ("Glurak 4/102 Erste Auflage Basis Set", "1st Edition", EDITION_FIRST),
            ("Glurak 4/102 Unbegrenzt Basis Set", "Unlimited", EDITION_UNLIMITED),
            ("Charizard 4/102 1ª Edizione Set Base", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 1a Edizione Set Base", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 Prima Edizione Set Base", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 1ª Edición Set Base", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 1a Edicion Set Base", "1st Edition", EDITION_FIRST),
            ("Charizard 4/102 Primera Edición Set Base", "1st Edition", EDITION_FIRST),
        ]
        for title, exp_display, exp_edition in cases:
            with self.subTest(title=title):
                edition, contra = extract_title_edition(title)
                self.assertFalse(contra, f"Unexpected contradiction in title: {title}")
                self.assertEqual(edition, exp_display)
                sem = semantics_from_text(edition)
                self.assertEqual(sem.edition, exp_edition)

    def test_title_edition_lone_words_and_false_positives_rejected(self):
        """Generic single words or non-edition markers must never prove edition."""
        cases = [
            "Charizard 4/102 Base Set Edition 2021",
            "Charizard 4/102 1st Place Trophy Card",
            "Charizard 4/102 First Place Winner",
            "Charizard 4/102 Auflage 2000",
            "Charizard 4/102 Print 1999",
            "Charizard 4/102 Standard Print",
        ]
        for title in cases:
            with self.subTest(title=title):
                edition, contra = extract_title_edition(title)
                self.assertFalse(contra)
                self.assertIsNone(edition, f"Expected no edition for title: {title}")

    def test_title_edition_contradictory_phrases_fail_closed(self):
        """Contradictory edition phrases within a title must return contradiction flag."""
        contradictory_titles = [
            "Charizard 4/102 1st Edition Unlimited Base Set",
            "Charizard 4/102 1st Edition Shadowless Base Set",
            "Charizard 4/102 First Edition Unlimited",
        ]
        for title in contradictory_titles:
            with self.subTest(title=title):
                edition, contra = extract_title_edition(title)
                self.assertTrue(contra, f"Expected contradiction for title: {title}")
                self.assertIsNone(edition)

    def test_resolve_card_identity_edition_reconciliation(self):
        """Structured aspect and title edition reconciliation rules."""
        # Case 1: Structured agreement
        payload_agree = {
            "title": "Charizard 4/102 1st Edition Base Set Holo",
            "localizedAspects": [
                {"name": "Card Name", "value": "Charizard"},
                {"name": "Set", "value": "Base Set"},
                {"name": "Card Number", "value": "4/102"},
                {"name": "Edition", "value": "1st Edition"},
            ],
        }
        res_agree = resolve_card_identity(payload_agree)
        self.assertEqual(res_agree.identity.edition, "1st Edition")
        self.assertFalse(res_agree.identity.ambiguities)

        # Case 2: Structured conflict with title
        payload_conflict = {
            "title": "Charizard 4/102 1st Edition Base Set Holo",
            "localizedAspects": [
                {"name": "Card Name", "value": "Charizard"},
                {"name": "Set", "value": "Base Set"},
                {"name": "Card Number", "value": "4/102"},
                {"name": "Edition", "value": "Unlimited"},
            ],
        }
        res_conflict = resolve_card_identity(payload_conflict)
        self.assertEqual(res_conflict.identity.edition, "Unlimited")
        self.assertTrue(any("edition: conflit" in a for a in res_conflict.identity.ambiguities))

        # Case 3: Structured missing + title edition fallback
        payload_title_only = {
            "title": "Charizard 4/102 1st Edition Base Set Holo",
            "localizedAspects": [
                {"name": "Card Name", "value": "Charizard"},
                {"name": "Set", "value": "Base Set"},
                {"name": "Card Number", "value": "4/102"},
            ],
        }
        res_title_only = resolve_card_identity(payload_title_only)
        self.assertEqual(res_title_only.identity.edition, "1st Edition")
        self.assertFalse(res_title_only.identity.ambiguities)

        # Case 4: Structured missing + contradictory title edition
        payload_title_contra = {
            "title": "Charizard 4/102 1st Edition Unlimited Base Set",
            "localizedAspects": [
                {"name": "Card Name", "value": "Charizard"},
                {"name": "Set", "value": "Base Set"},
                {"name": "Card Number", "value": "4/102"},
            ],
        }
        res_title_contra = resolve_card_identity(payload_title_contra)
        self.assertIsNone(res_title_contra.identity.edition)
        self.assertTrue(any("edition: valeurs contradictoires" in a for a in res_title_contra.identity.ambiguities))

    def test_extended_structured_aspect_aliases(self):
        """German Auflage, Finish aliases and Italian Caratteristiche are recognized."""
        payload_de = {
            "title": "Glurak 4/102 Basis Set",
            "localizedAspects": [
                {"name": "Kartenname", "value": "Glurak"},
                {"name": "Kartenset", "value": "Basis Set"},
                {"name": "Kartennummer", "value": "4/102"},
                {"name": "Auflage", "value": "1. Auflage"},
                {"name": "Card Finish", "value": "Holo"},
            ],
        }
        res_de = resolve_card_identity(payload_de)
        self.assertEqual(res_de.identity.edition, "1. Auflage")
        self.assertEqual(res_de.identity.finish, "Holo")

        payload_it = {
            "title": "Charizard 4/102 Set Base",
            "localizedAspects": [
                {"name": "Nome carta", "value": "Charizard"},
                {"name": "Set", "value": "Set Base"},
                {"name": "Numero carta", "value": "4/102"},
                {"name": "Caratteristiche", "value": "1ª Edizione"},
            ],
        }
        res_it = resolve_card_identity(payload_it)
        self.assertEqual(res_it.identity.edition, "first_edition")
        self.assertEqual(semantics_from_text(res_it.identity.edition).edition, EDITION_FIRST)

    def test_local_microvariant_validator_unblocks_proven_edition(self):
        """When TCGdex proves both 1st Edition and Unlimited exist, proven edition unblocks economics."""
        card_data = {
            "id": "base1-4",
            "variants": {
                "normal": False,
                "reverse": False,
                "holo": True,
                "firstEdition": True,
            },
        }
        applicability = tcgdex_microvariant_applicability(card_data)
        self.assertEqual(applicability.status, MICROVARIANT_APPLICABLE)
        self.assertFalse(applicability.edition_proven_single)
        self.assertTrue(applicability.finish_proven_single)

        validator = LocalMicrovariantValidator()

        # 1. 1st Edition proven on listing -> FIRST_EDITION_CONFIRMED, unblocked!
        id_1st = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            edition="1st Edition",
        )
        res_1st = validator.resolve(id_1st, applicability=applicability)
        self.assertFalse(res_1st.blocks_economics)
        self.assertEqual(res_1st.edition_status, FIRST_EDITION_CONFIRMED)

        # 2. Unlimited proven on listing -> UNLIMITED_CONFIRMED, unblocked!
        id_unl = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            edition="Unlimited",
        )
        res_unl = validator.resolve(id_unl, applicability=applicability)
        self.assertFalse(res_unl.blocks_economics)
        self.assertEqual(res_unl.edition_status, UNLIMITED_CONFIRMED)

        # 3. German 1. Auflage proven on listing -> FIRST_EDITION_CONFIRMED, unblocked!
        id_de = CardIdentity(
            card_name="Glurak",
            set="Basis Set",
            card_number="4/102",
            language="German",
            edition="1. Auflage",
        )
        res_de = validator.resolve(id_de, applicability=applicability)
        self.assertFalse(res_de.blocks_economics)
        self.assertEqual(res_de.edition_status, FIRST_EDITION_CONFIRMED)

        # 4. French 1ère Édition proven on listing -> FIRST_EDITION_CONFIRMED, unblocked!
        id_fr = CardIdentity(
            card_name="Dracaufeu",
            set="Set de Base",
            card_number="4/102",
            language="French",
            edition="1ère Édition",
        )
        res_fr = validator.resolve(id_fr, applicability=applicability)
        self.assertFalse(res_fr.blocks_economics)
        self.assertEqual(res_fr.edition_status, FIRST_EDITION_CONFIRMED)

        # 5. Shadowless proven on listing -> MICROVARIANT_NOT_REQUIRED, unblocked!
        id_shadow = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            edition="Shadowless",
        )
        res_shadow = validator.resolve(id_shadow, applicability=applicability)
        self.assertFalse(res_shadow.blocks_economics)
        self.assertEqual(res_shadow.edition_status, MICROVARIANT_NOT_REQUIRED)

        # 6. Unproven edition on listing -> EDITION_UNKNOWN, blocked! (fail closed preserved)
        id_unknown = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
            edition=None,
        )
        res_unknown = validator.resolve(id_unknown, applicability=applicability)
        self.assertTrue(res_unknown.blocks_economics)
        self.assertEqual(res_unknown.edition_status, EDITION_UNKNOWN)

    def test_visual_hallucination_plus_not_applicable_yields_conflict_and_blocks(self):
        """P0: Visual first-edition marker must NEVER override catalog MICROVARIANT_NOT_APPLICABLE."""
        validator = LocalMicrovariantValidator()
        applicability = MicrovariantApplicability(
            status=MICROVARIANT_NOT_APPLICABLE,
            source="TCGDEX_EXACT",
            edition_proven_single=True,
            edition_multiple_variants=False,
            single_finish="holo",
            finish_proven_single=True,
        )
        card_id = CardIdentity(
            card_name="Charizard ex",
            set="Obsidian Flames",
            card_number="125/197",
            language="English",
            finish="holo",
        )
        evidence = EditionRegionEvidence(
            stamp_region_visible=True,
            first_edition_marker=True,  # Visual detector hallucinated 1st edition marker on modern card
        )
        res = validator.resolve(card_id, evidence=evidence, applicability=applicability)
        self.assertTrue(res.blocks_economics)
        self.assertEqual(res.edition_status, EDITION_CONFLICT)

    def test_provider_metadata_alone_never_yields_single_compatible(self):
        """P0: Observability must NEVER infer SINGLE_COMPATIBLE from provider metadata alone."""
        card_id = CardIdentity(
            card_name="Pikachu",
            set="Lost Origin",
            card_number="TG05/TG30",
            language="English",
        )
        validator = LocalMicrovariantValidator()
        resolution = validator.resolve(card_id)  # blocks_economics=True, blocker_dimension="finish"

        # 1. Without catalog proof, provider candidate with variant info should NOT produce SINGLE_COMPATIBLE
        diag_finish = analyze_variant_blocking(
            record={"item_id": "123456"},
            item_id="123456",
            identity=card_id,
            microvariant_resolution=resolution,
            microvariant_applicability=MicrovariantApplicability(
                status="MICROVARIANT_APPLICABILITY_UNKNOWN",
                source="UNAVAILABLE",
            ),
            card_catalog_card=None,
            poketrace_candidate={"variant": "Holo", "finish": "Holo"},
        )
        self.assertEqual(diag_finish.variant_block_basis, "UNKNOWN_FIELD_ONLY")
        self.assertFalse(diag_finish.variant_block_maybe_unnecessary)
        self.assertEqual(diag_finish.current_block_reason, VARIANT_FINISH_UNKNOWN)

        # 2. Edition dimension without catalog proof
        resolution_edition = validator.resolve(
            card_id,
            evidence=EditionRegionEvidence(dimension="edition"),
        )
        diag_edition = analyze_variant_blocking(
            record={"item_id": "123456"},
            item_id="123456",
            identity=card_id,
            microvariant_resolution=resolution_edition,
            microvariant_applicability=MicrovariantApplicability(
                status="MICROVARIANT_APPLICABILITY_UNKNOWN",
                source="UNAVAILABLE",
            ),
            card_catalog_card=None,
            poketrace_candidate={"edition": "Unlimited"},
        )
        self.assertEqual(diag_edition.variant_block_basis, "UNKNOWN_FIELD_ONLY")
        self.assertFalse(diag_edition.variant_block_maybe_unnecessary)
        self.assertEqual(diag_edition.current_block_reason, VARIANT_FIRST_EDITION_UNKNOWN)

    def test_provider_finish_conflicting_with_catalog_single_finish_fails_closed(self):
        """P1: If catalog proves a single finish, conflicting provider finish must fail closed."""
        validator = LocalMicrovariantValidator()
        applicability = MicrovariantApplicability(
            status=MICROVARIANT_NOT_APPLICABLE,
            source="TCGDEX_EXACT",
            edition_proven_single=True,
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
        )
        # Listing has no finish explicitly stated
        listing_id = CardIdentity(
            card_name="Gengar",
            set="Fossil",
            card_number="5/62",
            language="English",
            finish=None,
        )
        # Provider candidate has conflicting finish (Reverse Holo instead of catalog single Holo)
        provider_candidate = {
            "card_name": "Gengar",
            "set": "Fossil",
            "card_number": "5/62",
            "finish": "Reverse Holo",
        }
        res = validator.resolve(
            listing_id,
            candidate=provider_candidate,
            applicability=applicability,
        )
        self.assertTrue(res.blocks_economics)
        self.assertEqual(res.edition_status, EDITION_CONFLICT)

    def test_catalog_exclusive_promo_and_special_finish_unblocks_safe_candidates(self):
        """P1: Catalog proof of exclusive promo or special finish unblocks without false collision."""
        validator = LocalMicrovariantValidator()
        # Catalog proves promo is single & exclusive (e.g. SVP 001)
        applicability_promo = MicrovariantApplicability(
            status=MICROVARIANT_NOT_APPLICABLE,
            source="TCGDEX_EXACT",
            edition_proven_single=True,
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
            single_promo=True,
            promo_proven_single=True,
        )
        listing_id = CardIdentity(
            card_name="Pikachu",
            set="SVP",
            card_number="001",
            language="English",
            finish="holo",
        )
        provider_candidate = {
            "card_name": "Pikachu",
            "set": "SVP",
            "card_number": "001",
            "promo": True,
            "finish": "Holo",
        }
        res_promo = validator.resolve(
            listing_id,
            candidate=provider_candidate,
            applicability=applicability_promo,
        )
        self.assertFalse(res_promo.blocks_economics)

        # But if catalog does NOT prove exclusive promo, provider promo=True must block!
        applicability_non_promo = MicrovariantApplicability(
            status=MICROVARIANT_NOT_APPLICABLE,
            source="TCGDEX_EXACT",
            edition_proven_single=True,
            single_finish=FINISH_HOLO,
            finish_proven_single=True,
            single_promo=False,
            promo_proven_single=True,
        )
        res_non_promo = validator.resolve(
            listing_id,
            candidate=provider_candidate,
            applicability=applicability_non_promo,
        )
        self.assertTrue(res_non_promo.blocks_economics)

    def test_bidirectional_and_multilingual_title_finishes(self):
        """Bidirectional phrases like 'Holo Reverse' or 'Reverse Pokeball' must be extracted safely."""
        # 1. Holo Reverse -> Reverse Holo (never misclassified as lone Holo)
        finish, contra = extract_title_finish("Pokemon Pikachu 025/165 Holo Reverse FR")
        self.assertEqual(finish, "Reverse Holo")
        self.assertFalse(contra)

        finish_de, contra_de = extract_title_finish("Glurak 006/165 Holo-Reverse Deutsch")
        self.assertEqual(finish_de, "Reverse Holo")
        self.assertFalse(contra_de)

        finish_fr, contra_fr = extract_title_finish("Dracaufeu Reverse Holographique 006/165")
        self.assertEqual(finish_fr, "Reverse Holo")
        self.assertFalse(contra_fr)

        # 2. Reverse Poké Ball / Reverse Master Ball
        finish_pb, contra_pb = extract_title_finish("Pikachu Reverse Pokeball 025/165")
        self.assertEqual(finish_pb, "Poké Ball Reverse")
        self.assertFalse(contra_pb)

        finish_mb, contra_mb = extract_title_finish("Pikachu Reverse Master Ball 025/165")
        self.assertEqual(finish_mb, "Master Ball Reverse")
        self.assertFalse(contra_mb)

        # 3. Multilingual Nicht-Holo / Holographisch / Olografica
        finish_nh, contra_nh = extract_title_finish("Glurak Nicht-Holo 006/165")
        self.assertEqual(finish_nh, "Non-Holo")
        self.assertFalse(contra_nh)

        finish_hg, contra_hg = extract_title_finish("Gengar Holographisch 094/165")
        self.assertEqual(finish_hg, "Holo")
        self.assertFalse(contra_hg)

        finish_ol, contra_ol = extract_title_finish("Umbreon Olografica 133/165")
        self.assertEqual(finish_ol, "Holo")
        self.assertFalse(contra_ol)

    def test_wpromo_stamp_does_not_prove_generic_promo_or_finish(self):
        """TCGdex wPromo is W-stamp availability, not generic promo/finish proof."""
        card_promo = {
            "id": "svp-001",
            "name": "Pikachu",
            "variants": {
                "firstEdition": False,
                "holo": False,
                "normal": False,
                "reverse": False,
                "wPromo": True,
            },
        }
        app = tcgdex_microvariant_applicability(card_promo)
        self.assertFalse(app.finish_proven_single)
        self.assertFalse(app.finish_multiple_variants)
        self.assertFalse(app.promo_proven_single)
        self.assertIsNone(app.single_promo)



if __name__ == "__main__":
    unittest.main()
