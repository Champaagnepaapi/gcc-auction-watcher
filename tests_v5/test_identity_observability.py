from __future__ import annotations

import unittest
from decimal import Decimal
from typing import Mapping

from v5.models import CardIdentity
from v5.microvariants import (
    EDITION_FIRST,
    EDITION_UNKNOWN,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    MicrovariantApplicability,
    MicrovariantResolution,
)
from v5.identity_observability import (
    COMMERCIAL_COLLISION_PROVEN,
    DENOMINATOR_CONFLICT,
    MISSING_NAME,
    MISSING_SET,
    MULTIPLE_CANONICAL_CANDIDATES,
    NUMBER_UNPROVEN,
    LISTING_FIELD_CONFLICT,
    POKETRACE_NAME_MISMATCH,
    POKETRACE_NUMBER_MISMATCH,
    POKETRACE_SET_MISMATCH,
    SET_UNPROVEN,
    UnresolvedIdentityDiagnostic,
    VARIANT_FIRST_EDITION_UNKNOWN,
    VARIANT_FINISH_UNKNOWN,
    VARIANT_MULTIPLE_COMPATIBLE,
    VARIANT_SINGLE_COMPATIBLE,
    VARIANT_UNKNOWN_FIELD_ONLY,
    VISUAL_MARGIN_TOO_SMALL,
    VISUAL_NO_CANDIDATE,
    ambiguity_fields,
    analyze_coordinates,
    analyze_variant_blocking,
    determine_reason_code,
    extract_near_matches,
    sanitize_title,
)
from v5.visual_identity import VisualIdentityResolution


class IdentityObservabilityTests(unittest.TestCase):
    def test_insufficient_record_exposes_missing_coordinate(self):
        # Missing number
        id_no_num = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number=None,
            language="English",
        )
        coords = analyze_coordinates(id_no_num)
        self.assertEqual(coords.name, "known")
        self.assertEqual(coords.set_name, "known")
        self.assertEqual(coords.number, "missing")
        self.assertEqual(coords.denominator, "missing")

        reason, expl = determine_reason_code("INSUFFICIENT", id_no_num, coords)
        self.assertEqual(reason, NUMBER_UNPROVEN)
        self.assertIn("Collector number", expl)

        # Missing name
        id_no_name = CardIdentity(
            card_name=None,
            set="Base Set",
            card_number="4/102",
            language="English",
        )
        coords_name = analyze_coordinates(id_no_name)
        self.assertEqual(coords_name.name, "missing")
        self.assertEqual(coords_name.set_name, "known")
        self.assertEqual(coords_name.number, "known")
        reason_name, _ = determine_reason_code("INSUFFICIENT", id_no_name, coords_name)
        self.assertEqual(reason_name, MISSING_NAME)

    def test_denominator_conflict_distinguishable_from_generic_insufficiency(self):
        id_denom = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/999",
            language="English",
            ambiguities=("catalog_denominator_conflict",),
        )
        coords = analyze_coordinates(id_denom)
        self.assertEqual(coords.number, "conflicting")
        self.assertEqual(coords.denominator, "conflicting")

        reason, expl = determine_reason_code("INSUFFICIENT", id_denom, coords)
        self.assertEqual(reason, DENOMINATOR_CONFLICT)
        self.assertIn("denominator", expl.lower())

    def test_all_known_coordinates_report_actual_ambiguity_field(self):
        identity = CardIdentity(
            game="Pokémon TCG",
            card_name="Dark Blastoise",
            set="Team Rocket",
            card_number="3/82",
            language="English",
            ambiguities=("variant: valeurs contradictoires",),
        )
        coords = analyze_coordinates(identity)
        self.assertEqual(ambiguity_fields(identity), ("variant",))
        reason, explanation = determine_reason_code(
            "AMBIGUOUS",
            identity,
            coords,
            tcgdex_status="matched=True, ambiguous=False, source=TCGDEX",
        )
        self.assertEqual(reason, LISTING_FIELD_CONFLICT)
        self.assertIn("variant", explanation)

    def test_tcgdex_multi_catalog_is_not_misreported_as_number_unproven(self):
        identity = CardIdentity(
            game="Pokémon TCG",
            card_name="Pikachu",
            set="SVP",
            card_number="027",
            language="French",
        )
        coords = analyze_coordinates(identity)
        reason, explanation = determine_reason_code(
            "AMBIGUOUS",
            identity,
            coords,
            tcgdex_status="matched=False, ambiguous=True, source=MULTI_CATALOG",
        )
        self.assertEqual(reason, MULTIPLE_CANONICAL_CANDIDATES)
        self.assertIn("TCGdex", explanation)

    def test_poketrace_near_matches_distinguishable(self):
        target = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )
        candidates = [
            # Set mismatch only
            {"id": "pt-1", "name": "Charizard", "set": {"name": "Base Set 2"}, "number": "4/102"},
            # Number mismatch only
            {"id": "pt-2", "name": "Charizard", "set": {"name": "Base Set"}, "number": "100/102"},
            # Name mismatch only
            {"id": "pt-3", "name": "Dark Charizard", "set": {"name": "Base Set"}, "number": "4/102"},
        ]
        diffs = extract_near_matches(target, candidates)
        self.assertEqual(len(diffs), 3)

        self.assertEqual(diffs[0].diff_kind, "SET_ONLY")
        self.assertEqual(diffs[0].differences, ("set",))

        self.assertEqual(diffs[1].diff_kind, "NUMBER_ONLY")
        self.assertEqual(diffs[1].differences, ("number",))

        self.assertEqual(diffs[2].diff_kind, "NAME_ONLY")
        self.assertEqual(diffs[2].differences, ("name",))

    def test_visual_failure_reasons_distinguishable(self):
        id_target = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )
        coords = analyze_coordinates(id_target)

        # No visual candidate
        r1, expl1 = determine_reason_code(
            "INSUFFICIENT", id_target, coords, visual_status="NO_CANDIDATE"
        )
        self.assertEqual(r1, VISUAL_NO_CANDIDATE)

        # Margin too small / close second
        r2, expl2 = determine_reason_code(
            "INSUFFICIENT", id_target, coords, visual_status="MARGIN_TOO_SMALL"
        )
        self.assertEqual(r2, VISUAL_MARGIN_TOO_SMALL)

    def test_variant_blocker_distinguishes_single_variant_vs_real_collision(self):
        identity = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )

        # Case A: Real collision (TCGdex 1st Edition applicable, both 1st and Unlimited exist)
        app_applicable = MicrovariantApplicability(MICROVARIANT_APPLICABLE, "TCGDEX_EXACT")
        res_blocked_edition = MicrovariantResolution(
            applicability=MICROVARIANT_APPLICABLE,
            edition_status=EDITION_UNKNOWN,
            blocks_economics=True,
            blocker_dimension="edition",
        )
        diag_collision = analyze_variant_blocking(
            record=1,
            item_id="ebay-101",
            identity=identity,
            microvariant_applicability=app_applicable,
            microvariant_resolution=res_blocked_edition,
            card_catalog_card={"variants": {"firstEdition": True, "unlimited": True}},
        )
        self.assertTrue(diag_collision.collision_proven)
        self.assertFalse(diag_collision.variant_block_maybe_unnecessary)
        self.assertEqual(diag_collision.variant_block_basis, "REAL_COLLISION")
        self.assertEqual(diag_collision.current_block_reason, COMMERCIAL_COLLISION_PROVEN)

        # Case B: Single compatible variant (only 1 variant exists in catalog for finish)
        diag_single = analyze_variant_blocking(
            record=2,
            item_id="ebay-102",
            identity=identity,
            microvariant_applicability=MicrovariantApplicability(MICROVARIANT_NOT_APPLICABLE, "TCGDEX_EXACT"),
            microvariant_resolution=MicrovariantResolution(
                applicability=MICROVARIANT_NOT_APPLICABLE,
                blocks_economics=True,
                blocker_dimension="finish",
            ),
            card_catalog_card={"variants": {"normal": True, "holo": False, "reverse": False}},
        )
        self.assertFalse(diag_single.collision_proven)
        self.assertTrue(diag_single.variant_block_maybe_unnecessary)
        self.assertEqual(diag_single.variant_block_basis, "SINGLE_COMPATIBLE")
        self.assertEqual(diag_single.current_block_reason, VARIANT_SINGLE_COMPATIBLE)

    def test_red_team_orthogonal_variant_flags_do_not_create_false_real_collision(self):
        """Red Team Blocker 1: {firstEdition: True, holo: True, reverse: False} on finish blocker."""
        identity = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )
        card_catalog_card = {
            "variants": {
                "firstEdition": True,
                "holo": True,
                "reverse": False,
                "normal": False,
            }
        }
        # When blocked on finish: only holo is True -> exactly 1 finish option!
        diag_finish = analyze_variant_blocking(
            record=5,
            item_id="ebay-505",
            identity=identity,
            microvariant_applicability=MicrovariantApplicability(MICROVARIANT_APPLICABLE, "TCGDEX_EXACT"),
            microvariant_resolution=MicrovariantResolution(
                applicability=MICROVARIANT_APPLICABLE,
                blocks_economics=True,
                blocker_dimension="finish",
            ),
            card_catalog_card=card_catalog_card,
        )
        self.assertFalse(
            diag_finish.collision_proven,
            "Orthogonal firstEdition+holo flags must not prove a finish collision",
        )
        self.assertEqual(diag_finish.commercially_distinct_candidates, 1)
        self.assertTrue(diag_finish.variant_block_maybe_unnecessary)
        self.assertEqual(diag_finish.variant_block_basis, "SINGLE_COMPATIBLE")
        self.assertEqual(diag_finish.possible_variant_values, ("holo",))

    def test_red_team_provider_metadata_never_influences_proof(self):
        """Red Team Blocker 2: Provider metadata must never establish catalog proof or block bypass."""
        identity = CardIdentity(
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            language="English",
        )
        # Catalog has NO finish proof (empty variants)
        card_catalog_card = {"variants": {}}
        # PokeTrace candidate claims "Holo"
        poketrace_cand = {
            "name": "Charizard",
            "set": {"name": "Base Set"},
            "number": "4/102",
            "variant": "Holo",
        }
        diag = analyze_variant_blocking(
            record=6,
            item_id="ebay-606",
            identity=identity,
            microvariant_applicability=MicrovariantApplicability(MICROVARIANT_NOT_APPLICABLE, "TCGDEX_EXACT"),
            microvariant_resolution=MicrovariantResolution(
                applicability=MICROVARIANT_NOT_APPLICABLE,
                blocks_economics=True,
                blocker_dimension="finish",
            ),
            card_catalog_card=card_catalog_card,
            poketrace_candidate=poketrace_cand,
        )
        # Provider metadata must be recorded in provider_evidence ONLY
        self.assertIn("holofoil", diag.provider_evidence)
        # But it must NEVER make variant_block_maybe_unnecessary True or prove SINGLE_COMPATIBLE
        self.assertFalse(diag.variant_block_maybe_unnecessary)
        self.assertFalse(diag.collision_proven)
        self.assertEqual(diag.variant_block_basis, "UNKNOWN_FIELD_ONLY")
        self.assertEqual(diag.current_block_reason, VARIANT_FINISH_UNKNOWN)

    def test_red_team_raw_title_sanitization_and_bounding(self):
        """Red Team Blocker 3: Raw listing title must be bounded, control-character stripped, and clean."""
        raw_title = "Rare Pokemon Card \n\r\t \x00 Charizard Base Set 4/102 1st Edition Holo Mint Condition PSA 10 Candidate Gem Rare Vintage"
        sanitized = sanitize_title(raw_title, max_length=50)
        self.assertNotIn("\n", sanitized)
        self.assertNotIn("\r", sanitized)
        self.assertNotIn("\t", sanitized)
        self.assertNotIn("\x00", sanitized)
        self.assertTrue(len(sanitized) <= 53)  # max_length + "..."
        self.assertTrue(sanitized.endswith("..."))

        # In formatted block
        diag = UnresolvedIdentityDiagnostic(
            record=7,
            item_id="ebay-707",
            title=raw_title,
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            final_status="INSUFFICIENT",
            coordinates=analyze_coordinates(CardIdentity(card_name="Charizard", set="Base Set", card_number="4/102", language="English")),
            reason_code=NUMBER_UNPROVEN,
            explanation="Unproven",
        )
        block = diag.format_block()
        self.assertNotIn("\n\r\t", block)
        self.assertIn("title=Rare Pokemon Card Charizard Base Set 4/102 1st Edition Holo Mint Condition PSA 1...", block)

    def test_formatted_block_contains_structured_fields(self):
        diag = UnresolvedIdentityDiagnostic(
            record=4,
            item_id="1234567890",
            title="Pikachu Base Set 58/102 Card",
            card_name="Pikachu",
            set_name="Base Set",
            card_number=None,
            language="English",
            final_status="INSUFFICIENT",
            coordinates=analyze_coordinates(CardIdentity(card_name="Pikachu", set="Base Set", card_number=None, language="English")),
            tcgdex_detail="NO_EXACT_NUMBER",
            poketrace_detail="NEAR_MATCH_NUMBER_ONLY",
            visual_detail="NO_COMPATIBLE_CANDIDATE",
            reason_code=NUMBER_UNPROVEN,
            explanation="Collector number could not be proven",
        )
        block = diag.format_block()
        self.assertIn("[V5_IDENTITY_DIAG]", block)
        self.assertIn("record=4", block)
        self.assertIn("item_id=1234567890", block)
        self.assertIn("final=INSUFFICIENT", block)
        self.assertIn("number_coordinate=missing", block)
        self.assertIn("reason=NUMBER_UNPROVEN", block)


if __name__ == "__main__":
    unittest.main()
