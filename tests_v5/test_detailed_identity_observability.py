from __future__ import annotations

import unittest

from v5.card_identity_uniqueness import (
    DeterministicUniquenessHybridPokemonCardResolver,
)
from v5.detailed_identity_observability import (
    MULTIPLE_CANONICAL_CANDIDATES,
    POKETRACE_SET_MISMATCH,
    VISUAL_DISABLED,
    DetailedDeterministicUniquenessHybridPokemonCardResolver,
    DetailedLocalVisualIdentityResolver,
    DetailedPokeTraceIdentityResolver,
    ProviderDiagnostic,
    VisualDiagnostic,
    detailed_record_payload,
)
from v5.identity_observability import (
    CoordinateState,
    UnresolvedIdentityDiagnostic,
    VariantDiagnostic,
)
from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import PokeTraceIdentityResolver


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        payload = self.payload(url, kwargs) if callable(self.payload) else self.payload
        return _Response(payload)


def _identity(**overrides):
    values = dict(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
    )
    values.update(overrides)
    return CardIdentity(**values)


def _candidate(card_id, *, set_name="Base Set"):
    return {
        "id": card_id,
        "name": "Charizard",
        "cardNumber": "4/102",
        "set": {
            "id": set_name.casefold().replace(" ", "-"),
            "name": set_name,
            "slug": set_name.casefold().replace(" ", "-"),
        },
        "language": "English",
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {},
    }


def _provider(payload, *, enabled=True):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=enabled,
            api_key="offline-test-key" if enabled else "",
            minimum_request_interval_seconds=0,
        ),
        session=_Session(payload),
        sleeper=lambda _seconds: None,
    )


class DetailedIdentityObservabilityTests(unittest.TestCase):
    def test_detailed_poketrace_preserves_ambiguous_decision(self):
        payload = {"data": [_candidate("pt-a"), _candidate("pt-b")]}
        base = PokeTraceIdentityResolver(_provider(payload))
        detailed = DetailedPokeTraceIdentityResolver(_provider(payload))

        base_result = base.resolve_identity(_identity())
        detailed_result = detailed.resolve_identity(_identity())

        self.assertEqual(base_result, detailed_result)
        self.assertTrue(detailed_result.ambiguous)
        diagnostic = detailed.diagnostics_for(_identity())[0]
        self.assertEqual(diagnostic.status, "AMBIGUOUS")
        self.assertIn(MULTIPLE_CANONICAL_CANDIDATES, diagnostic.reason_codes)
        self.assertGreaterEqual(diagnostic.candidate_count, 2)

    def test_detailed_poketrace_types_set_only_near_match(self):
        payload = {"data": [_candidate("pt-set", set_name="Base Set 2")]}
        resolver = DetailedPokeTraceIdentityResolver(_provider(payload))

        result = resolver.resolve_identity(_identity())
        diagnostic = resolver.diagnostics_for(_identity())[0]

        self.assertFalse(result.matched)
        self.assertIn(POKETRACE_SET_MISMATCH, diagnostic.reason_codes)
        samples = [
            sample
            for sample in diagnostic.samples
            if sample.reason_code == POKETRACE_SET_MISMATCH
        ]
        self.assertTrue(samples)
        self.assertEqual(samples[0].differing_fields, ("set",))
        self.assertIn(samples[0].strategy, diagnostic.routes)

    def test_catalog_overlay_preserves_current_tcgdex_decision(self):
        def payload(url, _kwargs):
            if url.endswith("/en/sets"):
                return [
                    {
                        "id": "base1",
                        "name": "Base Set",
                        "cardCount": {"official": 102},
                    }
                ]
            if url.endswith("/fr/sets"):
                return []
            if url.endswith("/en/sets/base1/4"):
                return {
                    "id": "base1-4",
                    "name": "Charizard",
                    "localId": "4",
                    "variants": {
                        "firstEdition": True,
                        "normal": False,
                        "holo": True,
                        "reverse": False,
                    },
                    "set": {
                        "id": "base1",
                        "name": "Base Set",
                        "cardCount": {"official": 102},
                    },
                }
            return {}

        base_pt = PokeTraceIdentityResolver(_provider({"data": []}, enabled=False))
        detailed_pt = DetailedPokeTraceIdentityResolver(
            _provider({"data": []}, enabled=False)
        )
        base = DeterministicUniquenessHybridPokemonCardResolver(
            poketrace_identity_resolver=base_pt,
            session=_Session(payload),
        )
        detailed = DetailedDeterministicUniquenessHybridPokemonCardResolver(
            poketrace_identity_resolver=detailed_pt,
            session=_Session(payload),
        )

        base_result = base.resolve_identity(_identity())
        detailed_result = detailed.resolve_identity(_identity())

        self.assertEqual(base_result, detailed_result)
        self.assertTrue(detailed_result.matched)
        diagnostic = detailed.catalog_diagnostic_for(detailed_result.identity)
        self.assertEqual(diagnostic.status, "MATCHED")
        self.assertGreaterEqual(diagnostic.details["tcgdex_requests"], 1)

    def test_visual_overlay_returns_exact_same_resolution_when_disabled(self):
        provider = _provider({"data": []}, enabled=False)
        base_pt = PokeTraceIdentityResolver(provider)
        detailed_provider = _provider({"data": []}, enabled=False)
        detailed_pt = DetailedPokeTraceIdentityResolver(detailed_provider)

        from v5.visual_identity import LocalVisualIdentityResolver

        base = LocalVisualIdentityResolver(
            base_pt,
            ebay_image_fetcher=lambda _url: None,
            enabled=True,
        )
        detailed = DetailedLocalVisualIdentityResolver(
            detailed_pt,
            ebay_image_fetcher=lambda _url: None,
            enabled=True,
        )

        base_result = base.resolve_identity(_identity(), ("https://invalid",))
        detailed_result = detailed.resolve_identity(_identity(), ("https://invalid",))

        self.assertEqual(base_result, detailed_result)
        diagnostic = detailed.diagnostic_for(_identity())
        self.assertEqual(diagnostic.reason_code, VISUAL_DISABLED)
        self.assertFalse(diagnostic.matched)

    def test_record_payload_serializes_current_variant_diagnostic_without_reanalysis(self):
        variant = VariantDiagnostic(
            record=9,
            item_id="ebay-9",
            macro_identity="Charizard | Base Set | 4/102 | English",
            blocking_dimension="finish",
            possible_variant_values=("finish_unproven",),
            commercially_distinct_candidates=1,
            collision_proven=False,
            target_evidence="edition=None, finish=None, promo=None",
            catalog_evidence="status=MICROVARIANT_APPLICABILITY_UNKNOWN",
            provider_evidence="None",
            current_block_reason="VARIANT_FINISH_UNKNOWN",
            variant_block_maybe_unnecessary=False,
            variant_block_basis="UNKNOWN_FIELD_ONLY",
        )
        simple = UnresolvedIdentityDiagnostic(
            record=9,
            item_id="ebay-9",
            title="Charizard Base Set 4/102",
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            final_status="BLOCKED_VARIANT",
            coordinates=CoordinateState("known", "known", "known", "known"),
            reason_code="VARIANT_FINISH_UNKNOWN",
            explanation="current V5 gate blocked",
            variant_diag=variant,
        )

        class _PT:
            @staticmethod
            def diagnostics_for(_identity):
                return (ProviderDiagnostic("POKETRACE", status="NO_MATCH"),)

        class _Resolver:
            poketrace_identity = _PT()

            @staticmethod
            def catalog_diagnostic_for(_identity):
                return ProviderDiagnostic("TCGDEX", status="MATCHED")

        class _Visual:
            @staticmethod
            def diagnostic_for(_identity):
                return VisualDiagnostic(attempted=True, reason_code="VISUAL_MATCHED")

        payload = detailed_record_payload(simple, _Resolver(), _Visual())

        self.assertEqual(payload["final_reason_code"], "VARIANT_FINISH_UNKNOWN")
        self.assertEqual(payload["variant"]["variant_block_basis"], "UNKNOWN_FIELD_ONLY")
        self.assertFalse(payload["variant"]["variant_block_maybe_unnecessary"])
        self.assertEqual(payload["catalog"]["status"], "MATCHED")
        self.assertEqual(payload["poketrace"][0]["status"], "NO_MATCH")


if __name__ == "__main__":
    unittest.main()
