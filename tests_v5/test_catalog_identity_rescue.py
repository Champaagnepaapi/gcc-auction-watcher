from __future__ import annotations

import unittest
from dataclasses import replace

from tests_v5.test_ebay_live_diagnostic import complete_item
from v5.card_identity_catalog import CatalogIdentityResult
from v5.ebay import CardNameLookupResult
from v5.ebay_live_diagnostic import _DiscoveryRecord
from v5.live_raw_pipeline import PipelineIdentityAggregate, PipelineImageAggregate
from v5.live_raw_pipeline_catalog import CatalogAwareLiveRawPipelineDiagnostic
from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
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

    def resolve_identity(self, identity, image_urls):
        self.calls += 1
        self.image_urls = tuple(image_urls)
        return VisualIdentityResolution(
            replace(identity, card_number="7/100", ambiguities=()),
            matched=True,
            card_id="visual-fixture",
            score=0.93,
            margin=0.31,
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


if __name__ == "__main__":
    unittest.main()
