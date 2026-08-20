from __future__ import annotations

import unittest

import watcher
import v4_canonical_multimarket as multimarket
from v4_global_market_core import CommercialIdentity
import v4_global_provider_exact_bridge as bridge


class GlobalProviderExactBridgeTests(unittest.TestCase):
    def lot(self, *, name="Raikou", number="218/172", variant="Unlimited Full Art | Special Art Rare"):
        return watcher.Lot(
            url="https://example.invalid/read-only",
            title=name,
            current_price=1.0,
            source_type="FIXED_PRICE",
            grader="PSA",
            grade="10",
            listing_text=name,
            card_set="VSTAR Universe",
            card_number=number,
            language="Japanese",
            variant=variant,
        )

    def canonical(
        self,
        *,
        name="Raikou",
        number="218/172",
        card_id="S12a-218",
        set_id="S12a",
        set_name="VSTAR Universe",
        first_edition=False,
    ):
        return multimarket.CanonicalCard(
            status="EXACT",
            card_id=card_id,
            set_id=set_id,
            set_name=set_name,
            local_id=number.split("/", 1)[0],
            full_number=number,
            name=name,
            language_code="ja",
            variants={
                "firstEdition": first_edition,
                "holo": True,
                "normal": False,
                "reverse": False,
            },
            reason="PINNED_TEST",
            unique_name_number=False,
        )

    def pt_candidate(self, **overrides):
        row = {
            "name": "Raikou V (Japanese)",
            "cardNumber": "218/172",
            "game": "pokemon-japanese",
            "productType": "single",
            "set": {"name": "S12a: VSTAR Universe"},
            "variant": "Holofoil",
            "rarity": "Special Art Rare",
        }
        row.update(overrides)
        return row

    def test_live_raikou_shape_becomes_exact_after_macro_proof(self):
        self.assertTrue(
            bridge.global_candidate_exact_for_canonical(
                self.lot(), self.canonical(), self.pt_candidate()
            )
        )

    def test_live_mega_dragonite_shape_becomes_exact(self):
        lot = self.lot(
            name="Dragonite",
            number="246/193",
            variant="Unlimited Ex Special Alt Rare",
        )
        lot.card_set = "Mega Dream Ex"
        canonical = self.canonical(
            name="Dragonite",
            number="246/193",
            card_id="M2a-246",
            set_id="M2a",
            set_name="Mega Dream Ex",
        )
        candidate = self.pt_candidate(
            name="Mega Dragonite ex (Japanese)",
            cardNumber="246/193",
            set={"name": "M2a: High Class Pack: MEGA Dream ex"},
        )
        self.assertTrue(
            bridge.global_candidate_exact_for_canonical(lot, canonical, candidate)
        )

    def test_wrong_full_number_never_bridges(self):
        self.assertFalse(
            bridge.global_candidate_exact_for_canonical(
                self.lot(), self.canonical(), self.pt_candidate(cardNumber="218/190")
            )
        )

    def test_wrong_set_prefix_never_bridges(self):
        self.assertFalse(
            bridge.global_candidate_exact_for_canonical(
                self.lot(),
                self.canonical(),
                self.pt_candidate(set={"name": "SV4a: Shiny Treasure ex"}),
            )
        )

    def test_arbitrary_name_extra_token_never_bridges(self):
        self.assertFalse(
            bridge.global_candidate_exact_for_canonical(
                self.lot(),
                self.canonical(),
                self.pt_candidate(name="Rocket Raikou V (Japanese)"),
            )
        )

    def test_catalog_first_edition_applicable_keeps_unlimited_gate(self):
        self.assertFalse(
            bridge.global_candidate_exact_for_canonical(
                self.lot(),
                self.canonical(first_edition=True),
                self.pt_candidate(),
            )
        )

    def test_strict_mewtwo_name_can_use_catalog_non_applicable_edition(self):
        lot = self.lot(
            name="Mewtwo",
            number="183/165",
            variant="Unlimited Full Art | Art Rare",
        )
        lot.card_set = "151"
        canonical = self.canonical(
            name="Mewtwo",
            number="183/165",
            card_id="SV2a-183",
            set_id="SV2a",
            set_name="151",
        )
        candidate = self.pt_candidate(
            name="Mewtwo (Japanese)",
            cardNumber="183/165",
            set={"name": "SV2a: Pokemon Card 151"},
            rarity="Art Rare",
        )
        self.assertTrue(
            bridge.global_candidate_exact_for_canonical(lot, canonical, candidate)
        )

    def identity(self, *, name="Raikou", number="218/172", set_name="VSTAR Universe"):
        return CommercialIdentity(
            name=name,
            set_name=set_name,
            number=number,
            language="ja",
            grader="PSA",
            grade="10",
        )

    def test_live_ppt_s12a_shape_matches_generically(self):
        row = {
            "externalCatalogId": "",
            "tcgPlayerId": "571756",
            "name": "Raikou V - 218/172",
            "cardNumber": "218/172",
            "setId": "23645",
            "setName": "S12a: VSTAR Universe",
        }
        status, matched, proof = bridge.global_ppt_match_canonical(
            self.identity(), self.canonical(), [row]
        )
        self.assertEqual(status, "EXACT")
        self.assertIs(matched, row)
        self.assertEqual(proof, "TCGDEX_FULL_NUMBER_SET_PREFIX_MECHANIC_NAME")

    def test_live_ppt_m2a_shape_matches_generically(self):
        identity = self.identity(
            name="Dragonite", number="246/193", set_name="Mega Dream Ex"
        )
        canonical = self.canonical(
            name="Dragonite",
            number="246/193",
            card_id="M2a-246",
            set_id="M2a",
            set_name="Mega Dream Ex",
        )
        row = {
            "externalCatalogId": "",
            "tcgPlayerId": "665917",
            "name": "Mega Dragonite ex - 246/193",
            "cardNumber": "246/193",
            "setId": "24499",
            "setName": "M2a: High Class Pack: MEGA Dream ex",
        }
        self.assertEqual(
            bridge.global_ppt_match_canonical(identity, canonical, [row])[0], "EXACT"
        )

    def test_ppt_present_conflicting_external_catalog_id_never_falls_through(self):
        row = {
            "externalCatalogId": "wrong-card",
            "tcgPlayerId": "571756",
            "name": "Raikou V - 218/172",
            "cardNumber": "218/172",
            "setId": "23645",
            "setName": "S12a: VSTAR Universe",
        }
        self.assertEqual(
            bridge.global_ppt_match_canonical(
                self.identity(), self.canonical(), [row]
            )[0],
            "CLEAN_NO_MATCH",
        )

    def test_ppt_same_set_wrong_full_number_never_matches(self):
        row = {
            "externalCatalogId": "",
            "tcgPlayerId": "571756",
            "name": "Raikou V - 218/190",
            "cardNumber": "218/190",
            "setId": "23645",
            "setName": "S12a: VSTAR Universe",
        }
        self.assertEqual(
            bridge.global_ppt_match_canonical(
                self.identity(), self.canonical(), [row]
            )[0],
            "CLEAN_NO_MATCH",
        )


if __name__ == "__main__":
    unittest.main()
