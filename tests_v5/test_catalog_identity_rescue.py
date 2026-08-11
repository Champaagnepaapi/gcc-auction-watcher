from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal

from tests_v5.test_ebay_live_diagnostic import complete_item
from v5.card_identity_catalog import CatalogIdentityResult
from v5.ebay import CardNameLookupResult
from v5.ebay_live_diagnostic import MarketplaceAggregate, _DiscoveryRecord
from v5.live_raw_pipeline import (
    RESCUED_FROM_INSUFFICIENT,
    STILL_INSUFFICIENT,
    PipelineForensicAggregate,
    PipelineIdentityAggregate,
    PipelineImageAggregate,
    PipelineMicrovariantAggregate,
)
from v5.live_raw_pipeline_catalog import CatalogAwareLiveRawPipelineDiagnostic
from v5.market_values.models import MarketValues
from v5.market_values.poketrace import (
    CARDMARKET_NO_DISCOUNT,
    POKETRACE_MATCHED,
    CardmarketOpportunity,
    PokeTraceConfig,
    PokeTraceSnapshot,
)
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.microvariants import (
    EDITION_UNKNOWN,
    MICROVARIANT_APPLICABLE,
    MicrovariantResolution,
)
from v5.visual_identity import VisualIdentityResolution


class DisabledPokeTraceSession:
    def get(self, *_args, **_kwargs):
        raise AssertionError("PokeTrace network must not be used by this unit test")


class RescueResolver:
    """Fixture resolver that simulates a unique catalogue recovery."""

    def resolve(self, set_name, card_number, language, year, variant):
        return CardNameLookupResult(None)

    def resolve_identity(self, identity):
        if identity.card_name and identity.set and not identity.card_number:
            return CatalogIdentityResult(
                replace(identity, card_number="7/100"),
                source="POKETRACE",
                matched=True,
                ambiguous=False,
            )
        return CatalogIdentityResult(identity)


class NoRescueResolver:
    def resolve(self, set_name, card_number, language, year, variant):
        return CardNameLookupResult(None)

    def resolve_identity(self, identity):
        return CatalogIdentityResult(identity)


class CanonicalIdentityResolver:
    def __init__(self):
        self.name_only_calls = 0

    def resolve(self, set_name, card_number, language, year, variant):
        self.name_only_calls += 1
        return CardNameLookupResult("Name-only result must not be used")

    def resolve_identity(self, identity):
        return CatalogIdentityResult(
            replace(
                identity,
                card_name="Canonicalmon",
                set="Canonical Set",
                card_number="007/100",
            ),
            source="TCGDEX",
            matched=True,
        )


class StubVisualResolver:
    def __init__(self):
        self.calls = 0

    def resolve_identity(
        self,
        identity,
        image_urls,
        *,
        marketplace_id=None,
        microvariant_applicability=None,
    ):
        self.calls += 1
        self.image_urls = tuple(image_urls)
        self.marketplace_id = marketplace_id
        return VisualIdentityResolution(
            replace(identity, card_number="7/100", ambiguities=()),
            matched=True,
            card_id="visual-fixture",
            score=0.93,
            margin=0.31,
        )


class BlockedVisualResolver(StubVisualResolver):
    def resolve_identity(
        self,
        identity,
        image_urls,
        *,
        marketplace_id=None,
        microvariant_applicability=None,
    ):
        result = super().resolve_identity(
            identity,
            image_urls,
            marketplace_id=marketplace_id,
            microvariant_applicability=microvariant_applicability,
        )
        return replace(
            result,
            microvariant=MicrovariantResolution(
                applicability=MICROVARIANT_APPLICABLE,
                edition_status=EDITION_UNKNOWN,
                blocks_economics=True,
                visual_attempted=True,
                blocker_dimension="edition",
            ),
        )


def item_without_number():
    item = complete_item()
    item["localizedAspects"] = [
        aspect
        for aspect in item["localizedAspects"]
        if aspect["name"] != "Card Number"
    ]
    item["title"] = "Fixturemon Fixture Set Pokemon raw card"
    product = item.get("product")
    if isinstance(product, dict):
        product["title"] = item["title"]
    return item


def disabled_poketrace():
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(enabled=False, api_key=None),
        session=DisabledPokeTraceSession(),
    )


class CatalogIdentityRescueTests(unittest.TestCase):
    @staticmethod
    def _usd_values(identity):
        return MarketValues(
            source="offline PokeTrace fixture",
            currency="USD",
            ungraded_value=Decimal("25"),
            grade8_generic_value=None,
            grade9_generic_value=None,
            psa10_value=None,
            matched_identity=identity,
            match_confidence=Decimal("1"),
            matched_product_id="provider-record",
        )

    def test_pipeline_keeps_complete_catalog_identity_instead_of_name_only_adapter(self):
        resolver = CanonicalIdentityResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=resolver,
            poketrace_provider=disabled_poketrace(),
        )
        diagnostic.discovery._image_fetcher = lambda _url: None
        record = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="canonical-fixture-id",
            enriched=complete_item(),
            get_item_success=True,
        )

        candidate, raw = diagnostic._candidate_from_record(
            record,
            PipelineIdentityAggregate(),
            PipelineImageAggregate(),
        )

        self.assertTrue(raw)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.identity.card_name, "Canonicalmon")
        self.assertEqual(candidate.identity.set, "Canonical Set")
        self.assertEqual(candidate.identity.card_number, "007/100")
        self.assertEqual(resolver.name_only_calls, 0)

    def test_raw_missing_number_is_rescued_before_final_identity_gate(self):
        item = item_without_number()
        resolver = RescueResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=resolver,
            poketrace_provider=disabled_poketrace(),
        )
        diagnostic.discovery._image_fetcher = lambda _url: None

        record = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="fixture-id",
            enriched=item,
            get_item_success=True,
        )
        identities = PipelineIdentityAggregate()
        images = PipelineImageAggregate()

        candidate, raw = diagnostic._candidate_from_record(record, identities, images)

        self.assertTrue(raw)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.identity.card_number, "7/100")
        self.assertEqual(identities.ok, 1)
        self.assertEqual(identities.insufficient, 0)
        self.assertEqual(identities.card_number, 1)

    def test_visual_rescue_runs_before_final_insufficient_rejection(self):
        item = item_without_number()
        visual = StubVisualResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
            visual_identity_resolver=visual,
        )
        diagnostic.discovery._image_fetcher = lambda _url: None

        record = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="visual-fixture-id",
            enriched=item,
            get_item_success=True,
        )
        identities = PipelineIdentityAggregate()
        images = PipelineImageAggregate()

        candidate, raw = diagnostic._candidate_from_record(record, identities, images)

        self.assertTrue(raw)
        self.assertEqual(visual.calls, 1)
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate.identity.card_number, "7/100")
        self.assertEqual(identities.ok, 1)
        self.assertEqual(identities.insufficient, 0)
        self.assertTrue(visual.image_urls)
        self.assertEqual(visual.marketplace_id, "EBAY_US")

    def test_clean_identity_does_not_call_visual_resolver(self):
        visual = StubVisualResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
            visual_identity_resolver=visual,
        )
        diagnostic.discovery._image_fetcher = lambda _url: None
        item = complete_item()
        record = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="clean-fixture-id",
            enriched=item,
            get_item_success=True,
        )
        identities = PipelineIdentityAggregate()
        images = PipelineImageAggregate()

        candidate, raw = diagnostic._candidate_from_record(record, identities, images)

        self.assertTrue(raw)
        self.assertIsNotNone(candidate)
        self.assertEqual(visual.calls, 0)
        self.assertEqual(identities.ok, 1)

    def test_microvariant_unknown_stops_catalog_pipeline_before_market(self):
        visual = BlockedVisualResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
            visual_identity_resolver=visual,
        )
        diagnostic.discovery._image_fetcher = lambda _url: None
        forensic = PipelineForensicAggregate()
        microvariants = PipelineMicrovariantAggregate()
        candidate, raw = diagnostic._candidate_from_record(
            _DiscoveryRecord(
                marketplace_id="EBAY_US",
                summary={},
                item_id="blocked-before-market",
                enriched=item_without_number(),
                get_item_success=True,
            ),
            PipelineIdentityAggregate(),
            PipelineImageAggregate(),
            forensic,
            microvariants,
        )
        self.assertTrue(raw)
        self.assertIsNone(candidate)
        self.assertEqual(microvariants.microvariant_gate_blocked_before_market, 1)
        self.assertEqual(
            forensic.for_state(RESCUED_FROM_INSUFFICIENT).economics_deferred,
            1,
        )

    def test_forensic_queue_prioritizes_rescuable_insufficient_before_clean(self):
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
        )
        clean = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="clean",
            enriched=complete_item(),
            get_item_success=True,
        )
        insufficient = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="insufficient",
            enriched=item_without_number(),
            get_item_success=True,
        )

        ordered = diagnostic._order_records_for_identity((clean, insufficient))

        self.assertEqual(ordered[0].item_id, "insufficient")
        self.assertEqual(ordered[1].item_id, "clean")

    def test_visual_run_limit_keeps_proof_gate_and_final_insufficient_state(self):
        visual = StubVisualResolver()
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
            visual_identity_resolver=visual,
        )
        diagnostic.max_visual_identity_listings = 0
        diagnostic.discovery._image_fetcher = lambda _url: None
        record = _DiscoveryRecord(
            marketplace_id="EBAY_US",
            summary={},
            item_id="bounded-visual",
            enriched=item_without_number(),
            get_item_success=True,
        )
        forensic = PipelineForensicAggregate()

        candidate, raw = diagnostic._candidate_from_record(
            record,
            PipelineIdentityAggregate(),
            PipelineImageAggregate(),
            forensic,
        )

        self.assertTrue(raw)
        self.assertIsNone(candidate)
        self.assertEqual(visual.calls, 0)
        self.assertEqual(forensic.for_state(STILL_INSUFFICIENT).records, 1)
        self.assertEqual(
            forensic.for_state(RESCUED_FROM_INSUFFICIENT).records,
            0,
        )

    def test_market_provenance_is_aggregate_and_marketplace_scoped(self):
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=NoRescueResolver(),
            poketrace_provider=disabled_poketrace(),
        )
        diagnostic.discovery._image_fetcher = lambda _url: None
        item = complete_item()
        item["price"] = {"value": "12.50", "currency": "EUR"}
        record = _DiscoveryRecord(
            marketplace_id="EBAY_IT",
            summary={},
            item_id="aggregate-only-fixture",
            enriched=item,
            get_item_success=True,
        )
        candidate, _raw = diagnostic._candidate_from_record(
            record,
            PipelineIdentityAggregate(),
            PipelineImageAggregate(),
        )
        self.assertIsNotNone(candidate)
        aggregate = MarketplaceAggregate("EBAY_IT")

        diagnostic.poketrace_market_source.last_snapshot = PokeTraceSnapshot(
            POKETRACE_MATCHED,
            us_values=self._usd_values(candidate.identity),
            us_record_id="us-record",
        )
        diagnostic._record_market_provenance(candidate, aggregate)

        self.assertEqual(aggregate.poketrace_us_usd_accepted, 1)
        self.assertEqual(aggregate.poketrace_eu_eur_accepted, 0)
        self.assertEqual(aggregate.non_us_with_us_only_snapshot, 1)
        self.assertEqual(aggregate.eur_without_usable_eu_value, 1)

        diagnostic.poketrace_market_source.last_snapshot = PokeTraceSnapshot(
            POKETRACE_MATCHED,
            cardmarket=CardmarketOpportunity(
                CARDMARKET_NO_DISCOUNT,
                robust_reference=Decimal("80"),
            ),
            eu_record_id="eu-record",
        )
        diagnostic._record_market_provenance(candidate, aggregate)
        self.assertEqual(aggregate.poketrace_eu_eur_accepted, 1)
        self.assertEqual(aggregate.eur_with_usable_eu_value, 1)

        us_candidate = replace(
            candidate,
            marketplace_id="EBAY_US",
            listing=replace(candidate.listing, currency="USD"),
        )
        us_aggregate = MarketplaceAggregate("EBAY_US")
        diagnostic.poketrace_market_source.last_snapshot = None
        diagnostic._record_market_provenance(us_candidate, us_aggregate)
        diagnostic.poketrace_market_source.last_snapshot = PokeTraceSnapshot(
            POKETRACE_MATCHED,
            us_values=self._usd_values(us_candidate.identity),
            us_record_id="us-record",
        )
        diagnostic._record_market_provenance(us_candidate, us_aggregate)
        self.assertEqual(us_aggregate.us_without_usable_usd_value, 1)
        self.assertEqual(us_aggregate.us_with_usable_usd_value, 1)


if __name__ == "__main__":
    unittest.main()
