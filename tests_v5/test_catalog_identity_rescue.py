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


class CatalogIdentityRescueTests(unittest.TestCase):
    def test_raw_missing_number_is_rescued_before_final_identity_gate(self):
        item = complete_item()
        # Remove the structured card number and any title fallback number while
        # preserving a strong card_name + set identity for the catalogue.
        item["localizedAspects"] = [
            aspect
            for aspect in item["localizedAspects"]
            if aspect["name"] != "Card Number"
        ]
        item["title"] = "Fixturemon Fixture Set Pokemon raw card"
        product = item.get("product")
        if isinstance(product, dict):
            product["title"] = item["title"]

        resolver = RescueResolver()
        poketrace = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(enabled=False, api_key=None),
            session=DisabledPokeTraceSession(),
        )
        diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
            "client",
            "secret",
            card_catalog_resolver=resolver,
            poketrace_provider=poketrace,
        )
        # Avoid all image network work; the listing already has a front URL and
        # the back state may safely remain unknown for this identity test.
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


if __name__ == "__main__":
    unittest.main()
