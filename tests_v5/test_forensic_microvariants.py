from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from tests_v5.test_ebay_live_diagnostic import complete_item
from tests_v5.test_visual_identity import (
    PokeTraceSession,
    card_image,
    card_payload,
    ebay_photo,
    identity,
    provider,
)
from v5.ebay import parse_ebay_item
from v5.ebay_live_diagnostic import MarketplaceAggregate, OAuthAggregate
from v5.live_raw_pipeline import (
    IDENTITY_AMBIGUOUS,
    IDENTITY_INSUFFICIENT,
    IDENTITY_OK,
    RESCUED_FROM_AMBIGUOUS,
    RESCUED_FROM_INSUFFICIENT,
    STILL_AMBIGUOUS,
    STILL_INSUFFICIENT,
    STRUCTURED_USABLE,
    LiveRawPipelineDiagnostic,
    LiveRawPipelineSummary,
    PipelineEconomicAggregate,
    PipelineForensicAggregate,
    PipelineMarketAggregate,
    PipelineMicrovariantAggregate,
    _PipelineCandidate,
    _forensic_state,
    render_live_raw_pipeline_summary,
)
from v5.market_values.models import MarketValues
from v5.microvariants import (
    EDITION_CONFLICT,
    EDITION_UNKNOWN,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    UNLIMITED_CONFIRMED,
    EditionRegionEvidence,
    LocalMicrovariantValidator,
    MicrovariantApplicability,
    tcgdex_microvariant_applicability,
)
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver, _resolved_identity
from v5.visual_identity import LocalVisualIdentityResolver


def lugia(**changes) -> CardIdentity:
    values = dict(
        game="Pokemon TCG",
        card_name="Lugia",
        set="Neo Genesis",
        card_number="9/111",
        language="English",
        finish="Holo",
    )
    values.update(changes)
    return CardIdentity(**values)


def poketrace_lugia(variant="1st Edition Holofoil"):
    return {
        "id": "provider-provenance-only",
        "name": "Lugia",
        "cardNumber": "9/111",
        "set": {"name": "Neo Genesis", "slug": "neo-genesis"},
        "variant": variant,
        "rarity": "Rare Holo",
        "productType": "single",
    }


class OfflineValues:
    def values_for(self, card_identity):
        return MarketValues(
            source="offline fixture",
            currency="USD",
            ungraded_value=Decimal("100"),
            grade8_generic_value=None,
            grade9_generic_value=None,
            psa10_value=None,
            matched_identity=card_identity,
            match_confidence=Decimal("1"),
            matched_product_id="offline-record",
        )


class ForensicMicrovariantTests(unittest.TestCase):
    def setUp(self):
        self.validator = LocalMicrovariantValidator()

    def test_tcgdex_first_edition_false_makes_gate_not_applicable(self):
        applicability = tcgdex_microvariant_applicability(
            {"variants": {"firstEdition": False}}
        )
        result = self.validator.resolve(lugia(), applicability)
        self.assertEqual(applicability.status, MICROVARIANT_NOT_APPLICABLE)
        self.assertFalse(result.blocks_economics)

    def test_tcgdex_first_edition_family_activates_unknown_gate(self):
        applicability = tcgdex_microvariant_applicability(
            {"variants": {"firstEdition": True}}
        )
        result = self.validator.resolve(lugia(), applicability)
        self.assertEqual(applicability.status, MICROVARIANT_APPLICABLE)
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)
        self.assertTrue(result.blocks_economics)

    def test_explicit_first_edition_with_matching_candidate_is_allowed(self):
        result = self.validator.resolve(
            lugia(edition="1st Edition"),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            candidate=poketrace_lugia(),
        )
        self.assertEqual(result.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertFalse(result.blocks_economics)

    def test_explicit_first_edition_with_unlimited_candidate_conflicts(self):
        result = self.validator.resolve(
            lugia(edition="1st Edition"),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            candidate=poketrace_lugia("Unlimited Holofoil"),
        )
        self.assertEqual(result.edition_status, EDITION_CONFLICT)
        self.assertTrue(result.blocks_economics)

    def test_provider_first_edition_is_not_inherited_when_listing_is_silent(self):
        original = lugia()
        resolved = _resolved_identity(original, poketrace_lugia())
        result = self.validator.resolve(
            resolved,
            candidate=poketrace_lugia(),
            visual_attempted=True,
        )
        self.assertIsNone(resolved.edition)
        self.assertIsNone(resolved.variant)
        self.assertEqual(resolved.rarity, original.rarity)
        self.assertTrue(result.premium_candidate_not_inherited)
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)
        self.assertTrue(result.blocks_economics)

    def test_whole_card_match_without_stamp_proof_stays_unknown(self):
        scan = card_image("a")
        payload_card = card_payload(
            "first-edition-provenance",
            "004/102",
            "https://cdn.poketrace.com/first.png",
            variant="1st Edition Holofoil",
        )
        session = PokeTraceSession({"data": [payload_card]})
        market = provider(session)
        visual = LocalVisualIdentityResolver(
            PokeTraceIdentityResolver(market),
            ebay_image_fetcher=lambda _url: ebay_photo(scan),
            candidate_image_fetcher=lambda _url: scan,
            enabled=True,
            minimum_score=0.60,
            minimum_margin=0.06,
        )
        result = visual.resolve_identity(
            identity(number=None),
            ("https://i.ebayimg.com/front.png",),
            microvariant_applicability=MicrovariantApplicability(
                MICROVARIANT_APPLICABLE, "fixture"
            ),
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.microvariant.edition_status, EDITION_UNKNOWN)
        self.assertTrue(result.microvariant.blocks_economics)
        self.assertEqual(visual.counters.market_snapshots_primed, 0)

    def test_localized_positive_marker_confirms_first_edition(self):
        result = self.validator.resolve(
            lugia(),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            evidence=EditionRegionEvidence(
                stamp_region_visible=True,
                first_edition_marker=True,
                method="EXACT_LAYOUT_REGION",
            ),
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, FIRST_EDITION_CONFIRMED)
        self.assertTrue(result.visual_confirmed)

    def test_absence_of_stamp_alone_never_confirms_unlimited(self):
        result = self.validator.resolve(
            lugia(),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            evidence=EditionRegionEvidence(stamp_region_visible=True),
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, EDITION_UNKNOWN)
        self.assertFalse(result.visual_confirmed)

    def test_sufficient_exact_unlimited_reference_can_confirm_unlimited(self):
        result = self.validator.resolve(
            lugia(),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            evidence=EditionRegionEvidence(
                stamp_region_visible=True,
                unlimited_reference_match=True,
                method="EXACT_LAYOUT_REFERENCE",
            ),
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, UNLIMITED_CONFIRMED)
        self.assertTrue(result.visual_confirmed)

    def test_conflicting_visual_evidence_blocks_economics(self):
        result = self.validator.resolve(
            lugia(),
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
            evidence=EditionRegionEvidence(conflicting_markers=True),
            visual_attempted=True,
        )
        self.assertEqual(result.edition_status, EDITION_CONFLICT)
        self.assertTrue(result.blocks_economics)

    def test_macro_resolution_preserves_all_seller_microvariant_fields(self):
        original = lugia(
            variant="Seller parallel",
            rarity="Seller rarity",
            edition=None,
            finish="Holo",
        )
        resolved = _resolved_identity(original, poketrace_lugia())
        self.assertEqual(resolved.variant, "Seller parallel")
        self.assertEqual(resolved.rarity, "Seller rarity")
        self.assertEqual(resolved.finish, "Holo")
        self.assertIsNone(resolved.edition)

    def test_all_five_forensic_state_transitions_are_distinct(self):
        self.assertEqual(_forensic_state(IDENTITY_OK, IDENTITY_OK), STRUCTURED_USABLE)
        self.assertEqual(
            _forensic_state(IDENTITY_INSUFFICIENT, IDENTITY_OK),
            RESCUED_FROM_INSUFFICIENT,
        )
        self.assertEqual(
            _forensic_state(IDENTITY_AMBIGUOUS, IDENTITY_OK),
            RESCUED_FROM_AMBIGUOUS,
        )
        self.assertEqual(
            _forensic_state(IDENTITY_INSUFFICIENT, IDENTITY_INSUFFICIENT),
            STILL_INSUFFICIENT,
        )
        self.assertEqual(
            _forensic_state(IDENTITY_AMBIGUOUS, IDENTITY_AMBIGUOUS),
            STILL_AMBIGUOUS,
        )

    def test_microvariant_unknown_blocks_existing_economic_path(self):
        listing = parse_ebay_item(complete_item())
        unresolved_identity = replace(listing.identity, edition=None)
        blocked = self.validator.resolve(
            unresolved_identity,
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "fixture"),
        )
        candidate = _PipelineCandidate(
            listing,
            unresolved_identity,
            "BACK_IMAGE_UNKNOWN",
            "EBAY_US",
            True,
            RESCUED_FROM_INSUFFICIENT,
            blocked,
        )
        diagnostic = LiveRawPipelineDiagnostic(
            "client",
            "secret",
            offline_market_sources=(OfflineValues(),),
        )
        market = PipelineMarketAggregate()
        economic = PipelineEconomicAggregate()
        forensic = PipelineForensicAggregate()
        forensic.for_state(RESCUED_FROM_INSUFFICIENT).records = 1
        microvariants = PipelineMicrovariantAggregate()
        microvariants.record(blocked)
        diagnostic._evaluate_candidate(
            candidate,
            MarketplaceAggregate("EBAY_US"),
            market,
            economic,
            forensic,
            microvariants,
        )
        self.assertEqual(market.values_found, 1)
        self.assertEqual(economic.raw_path_evaluated, 0)
        self.assertEqual(
            microvariants.economics_blocked_microvariant_unknown, 1
        )
        self.assertEqual(
            forensic.for_state(RESCUED_FROM_INSUFFICIENT).economics_deferred,
            1,
        )

    def test_aggregate_renderer_never_exposes_listing_or_provider_details(self):
        forensic = PipelineForensicAggregate()
        forensic.for_state(STILL_INSUFFICIENT).records = 7
        summary = LiveRawPipelineSummary(
            OAuthAggregate("200", True, 7200),
            (MarketplaceAggregate("EBAY_US"),),
            forensic=forensic,
        )
        rendered = render_live_raw_pipeline_summary(summary)
        self.assertIn("STILL_INSUFFICIENT", rendered)
        self.assertIn("records: 7", rendered)
        for forbidden in (
            "provider-provenance-only",
            "Lugia",
            "9/111",
            "ebayimg.com",
            "secret",
        ):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
