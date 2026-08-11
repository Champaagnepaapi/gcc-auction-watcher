from __future__ import annotations

import unittest
from decimal import Decimal

from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.microvariants import (
    MICROVARIANT_APPLICABLE,
    LocalMicrovariantValidator,
    MicrovariantApplicability,
)
from v5.models import (
    POKETRACE_PROVIDER,
    TCGDEX_EXACT_ENGLISH_TWIN,
    CardIdentity,
    ProviderSearchAlias,
)
from v5.poketrace_identity import PokeTraceIdentityResolver
from v5.poketrace_matching import (
    REJECT_CARD_NAME,
    REJECT_CARD_NUMBER,
    _candidate_evidence,
)
from v5.poketrace_set_bridge import (
    BRIDGE_ENGLISH_TWIN,
    BRIDGE_OBSERVED_EXACT,
    BRIDGE_TCGDEX_ALIAS,
    BRIDGE_VERSIONED_MAPPING,
    SET_BRIDGE_AMBIGUOUS,
    SET_BRIDGE_COLLISION,
    SET_BRIDGE_EXACT,
    SET_BRIDGE_NO_MAPPING,
    DeterministicSetBridgeRegistry,
    OfficialSetName,
    SetBridgeDecision,
    TCGdexSetProvenance,
    VersionedPokeTraceSetMapping,
    collision_index,
)


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected offline PokeTrace request")
        return _Response(self.payloads.pop(0))


def _identity(
    *,
    card_name="Léviator",
    set_name="Set de Base",
    card_number="6/102",
    language="French",
    variant=None,
):
    return CardIdentity(
        game="Pokémon TCG",
        card_name=card_name,
        set=set_name,
        card_number=card_number,
        language=language,
        variant=variant,
    )


def _alias(
    *,
    card_id="base1-6",
    set_id="base1",
    local_id="6",
):
    return ProviderSearchAlias(
        provider=POKETRACE_PROVIDER,
        search_card_name="Gyarados",
        search_set_name="Base Set",
        provenance=TCGDEX_EXACT_ENGLISH_TWIN,
        catalog_card_id=card_id,
        catalog_set_id=set_id,
        catalog_local_id=local_id,
    )


def _provenance(
    *,
    language="fr",
    listing_set="Set de Base",
    localized_set="Set de Base",
    set_id="base1",
    names=None,
):
    official_names = names or (
        OfficialSetName(language, localized_set),
        OfficialSetName("en", "Base Set"),
    )
    return TCGdexSetProvenance(
        listing_set=listing_set,
        listing_language=language,
        language=language,
        set_id=set_id,
        set_name=localized_set,
        official_names=tuple(official_names),
        catalog_card_id=f"{set_id}-6",
        catalog_card_name="Léviator",
        local_id="6",
    )


def _candidate(
    *,
    name="Gyarados",
    number="6/102",
    set_name="Base Set",
    set_slug="base-set",
    set_id="pt-base-set",
    language="English",
    variant=None,
):
    return {
        "id": "pt-base1-6",
        "name": name,
        "cardNumber": number,
        "set": {"name": set_name, "slug": set_slug, "id": set_id},
        "language": language,
        "variant": variant,
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 30}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 34}},
        },
    }


def _provider(session, mappings=()):
    provider = FreeTierPokeTraceProvider(
        PokeTraceConfig(
            enabled=True,
            api_key="offline-placeholder",
            minimum_request_interval_seconds=0,
        ),
        session=session,
    )
    provider.set_bridge_registry = DeterministicSetBridgeRegistry(mappings)
    return provider


def _mapping():
    return VersionedPokeTraceSetMapping(
        mapping_id="base1-poketrace-name",
        version="2026-08-11",
        source="offline-test-fixture",
        tcgdex_set_id="base1",
        provider_names=("PokeTrace Base 1999",),
        provider_slugs=("poketrace-base-1999",),
        provider_set_ids=("pt-base-1999",),
    )


class DeterministicSetBridgeRegistryTests(unittest.TestCase):
    def _decision(self, candidate, *, provenance=None, alias=None, registry=None):
        registry = registry or DeterministicSetBridgeRegistry()
        provenance = provenance or _provenance()
        key = ("listing", provenance.language, provenance.set_id)
        self.assertTrue(registry.register(key, provenance))
        return registry, registry.evaluate(
            key,
            candidate,
            provider_alias=alias,
            core_identity_exact=True,
            collisions=collision_index((candidate,)),
        )

    def test_same_exact_official_set_name_is_accepted(self):
        registry, decision = self._decision(
            _candidate(set_name="Set de Base", language="French")
        )
        self.assertEqual(decision.status, SET_BRIDGE_EXACT)
        self.assertEqual(decision.reason, BRIDGE_TCGDEX_ALIAS)
        self.assertEqual(registry.counters.set_bridge_via_tcgdex_alias, 1)

    def test_known_provider_slug_requires_a_prior_exact_observation(self):
        registry = DeterministicSetBridgeRegistry()
        provenance = _provenance()
        first = _candidate(
            set_name="Set de Base",
            set_slug="base-set-1999",
            set_id="pt-base-1999",
            language="French",
        )
        registry, observed = self._decision(
            first, provenance=provenance, registry=registry
        )
        german = _provenance(
            language="de",
            listing_set="Grundset",
            localized_set="Grundset",
            names=(OfficialSetName("de", "Grundset"),),
        )
        german_key = ("listing", german.language, german.set_id)
        self.assertTrue(registry.register(german_key, german))
        second = _candidate(
            set_name="Set de Base",
            set_slug="base-set-1999",
            set_id="pt-base-1999",
            language="German",
        )
        decision = registry.evaluate(
            german_key,
            second,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collision_index((second,)),
        )
        self.assertEqual(observed.status, SET_BRIDGE_EXACT)
        self.assertEqual(decision.status, SET_BRIDGE_EXACT)
        self.assertEqual(decision.reason, BRIDGE_OBSERVED_EXACT)

    def test_unknown_slug_is_not_assumed_to_be_tcgdex_set_id(self):
        _registry, decision = self._decision(
            _candidate(
                set_name="Provider Catalogue Label",
                set_slug="base1",
                set_id="base1",
                language="French",
            )
        )
        self.assertEqual(decision.status, SET_BRIDGE_NO_MAPPING)

    def test_missing_provider_set_metadata_cannot_prove_a_bridge(self):
        candidate = _candidate(language="French")
        candidate.pop("set")
        _registry, decision = self._decision(candidate)
        self.assertEqual(decision.status, SET_BRIDGE_NO_MAPPING)

    def test_reviewed_versioned_mapping_can_match_name_slug_or_id(self):
        for field, value in (
            ("set_name", "PokeTrace Base 1999"),
            ("set_slug", "poketrace-base-1999"),
            ("set_id", "pt-base-1999"),
        ):
            with self.subTest(field=field):
                values = {
                    "set_name": "Unrelated provider label",
                    "set_slug": "unrelated-provider-slug",
                    "set_id": "unrelated-provider-id",
                    field: value,
                }
                registry = DeterministicSetBridgeRegistry((_mapping(),))
                registry, decision = self._decision(
                    _candidate(language="French", **values),
                    registry=registry,
                )
                self.assertEqual(decision.status, SET_BRIDGE_EXACT)
                self.assertEqual(decision.reason, BRIDGE_VERSIONED_MAPPING)

    def test_substring_and_extra_tokens_are_rejected(self):
        for set_name in ("Base", "Base Set Legacy", "The Base Set Collection"):
            with self.subTest(set_name=set_name):
                _registry, decision = self._decision(
                    _candidate(set_name=set_name, language="French")
                )
                self.assertEqual(decision.status, SET_BRIDGE_NO_MAPPING)

    def test_parent_subset_and_promo_subset_are_rejected(self):
        for set_name in (
            "Scarlet & Violet",
            "Scarlet & Violet 151",
            "Black Star Promos",
            "Base Set Promos",
        ):
            with self.subTest(set_name=set_name):
                _registry, decision = self._decision(
                    _candidate(set_name=set_name, language="French")
                )
                self.assertEqual(decision.status, SET_BRIDGE_NO_MAPPING)

    def test_same_number_in_an_unrelated_set_does_not_bridge(self):
        _registry, decision = self._decision(
            _candidate(set_name="Jungle", number="6/102", language="French")
        )
        self.assertEqual(decision.status, SET_BRIDGE_NO_MAPPING)

    def test_one_official_alias_for_two_tcgdex_sets_is_ambiguous(self):
        registry = DeterministicSetBridgeRegistry()
        shared = (OfficialSetName("en", "Shared Official Name"),)
        left = _provenance(set_id="left", names=shared)
        right = _provenance(set_id="right", names=shared)
        self.assertTrue(registry.register(("left",), left))
        self.assertTrue(registry.register(("right",), right))
        candidate = _candidate(
            set_name="Shared Official Name", language="French"
        )
        decision = registry.evaluate(
            ("left",),
            candidate,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collision_index((candidate,)),
        )
        self.assertEqual(decision.status, SET_BRIDGE_AMBIGUOUS)

    def test_same_provider_name_with_conflicting_ids_is_collision(self):
        left = _candidate(
            set_name="Set de Base", set_id="pt-left", language="French"
        )
        right = _candidate(
            set_name="Set de Base", set_id="pt-right", language="French"
        )
        collisions = collision_index((left, right))
        registry = DeterministicSetBridgeRegistry()
        self.assertTrue(registry.register(("left",), _provenance()))
        decision = registry.evaluate(
            ("left",),
            left,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collisions,
        )
        self.assertEqual(decision.status, SET_BRIDGE_COLLISION)

    def test_same_provider_slug_for_distinct_sets_is_collision(self):
        left = _candidate(
            set_name="Set de Base",
            set_slug="shared",
            set_id="pt-left",
            language="French",
        )
        right = _candidate(
            set_name="Jungle",
            set_slug="shared",
            set_id="pt-right",
            language="French",
        )
        registry = DeterministicSetBridgeRegistry()
        self.assertTrue(registry.register(("left",), _provenance()))
        decision = registry.evaluate(
            ("left",),
            left,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collision_index((left, right)),
        )
        self.assertEqual(decision.status, SET_BRIDGE_COLLISION)

    def test_conflicting_provider_ids_across_pages_are_not_reconciled(self):
        registry = DeterministicSetBridgeRegistry()
        provenance = _provenance()
        registry, first = self._decision(
            _candidate(
                set_name="Set de Base",
                set_id="pt-left",
                language="French",
            ),
            provenance=provenance,
            registry=registry,
        )
        second = _candidate(
            set_name="Set de Base",
            set_id="pt-right",
            language="French",
        )
        decision = registry.evaluate(
            ("listing", provenance.language, provenance.set_id),
            second,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collision_index((second,)),
        )
        self.assertEqual(first.status, SET_BRIDGE_EXACT)
        self.assertEqual(decision.status, SET_BRIDGE_COLLISION)

    def test_different_tcgdex_coordinates_invalidate_english_twin(self):
        _registry, decision = self._decision(
            _candidate(set_name="Provider-only label", language="English"),
            alias=_alias(card_id="another-card"),
        )
        self.assertEqual(decision.status, SET_BRIDGE_AMBIGUOUS)

    def test_conflicting_tcgdex_provenance_for_one_identity_is_collision(self):
        registry = DeterministicSetBridgeRegistry()
        key = ("same-listing",)
        self.assertTrue(registry.register(key, _provenance(set_id="base1")))
        self.assertFalse(registry.register(key, _provenance(set_id="base2")))
        candidate = _candidate(set_name="Set de Base", language="French")
        decision = registry.evaluate(
            key,
            candidate,
            provider_alias=None,
            core_identity_exact=True,
            collisions=collision_index((candidate,)),
        )
        self.assertEqual(decision.status, SET_BRIDGE_COLLISION)

    def test_explicit_incompatible_provider_language_is_ambiguous(self):
        _registry, decision = self._decision(
            _candidate(set_name="Set de Base", language="Japanese")
        )
        self.assertEqual(decision.status, SET_BRIDGE_AMBIGUOUS)

    def _assert_localized_english_twin(self, language, listing_set):
        provenance = _provenance(
            language=language,
            listing_set=listing_set,
            localized_set=listing_set,
            names=(
                OfficialSetName(language, listing_set),
                OfficialSetName("en", "Base Set"),
            ),
        )
        _registry, decision = self._decision(
            _candidate(set_name="Base Set", language="English"),
            provenance=provenance,
            alias=_alias(),
        )
        self.assertEqual(decision.status, SET_BRIDGE_EXACT)
        self.assertEqual(decision.reason, BRIDGE_ENGLISH_TWIN)

    def test_french_exact_identity_can_use_exact_english_twin(self):
        self._assert_localized_english_twin("fr", "Set de Base")

    def test_german_exact_identity_can_use_exact_english_twin(self):
        self._assert_localized_english_twin("de", "Grundset")

    def test_italian_exact_identity_can_use_exact_english_twin(self):
        self._assert_localized_english_twin("it", "Set Base")

    def test_spanish_exact_identity_can_use_exact_english_twin(self):
        self._assert_localized_english_twin("es", "Set Base Español")


class SetBridgeMatcherAndIntegrationTests(unittest.TestCase):
    def test_bridge_decision_cannot_rescue_wrong_card_name(self):
        evidence = _candidate_evidence(
            _identity(card_name="Gyarados", set_name="Base Set"),
            _candidate(name="Vaporeon", set_name="Provider-only label"),
            set_bridge=SetBridgeDecision(SET_BRIDGE_EXACT, BRIDGE_VERSIONED_MAPPING),
        )
        self.assertFalse(evidence.set_bridged)
        self.assertEqual(evidence.rejection, REJECT_CARD_NAME)

    def test_bridge_decision_cannot_rescue_wrong_or_partial_card_number(self):
        for number in ("7/102", "6"):
            with self.subTest(number=number):
                evidence = _candidate_evidence(
                    _identity(card_name="Gyarados", set_name="Base Set"),
                    _candidate(
                        number=number,
                        set_name="Provider-only label",
                        set_slug="provider-only-label",
                    ),
                    set_bridge=SetBridgeDecision(
                        SET_BRIDGE_EXACT, BRIDGE_VERSIONED_MAPPING
                    ),
                )
                self.assertFalse(evidence.set_bridged)
                self.assertFalse(evidence.card_number_matched)
                self.assertIn(evidence.rejection, {"set", REJECT_CARD_NUMBER})

    def test_identity_bridge_preserves_localized_listing_identity(self):
        session = _Session(
            [
                {
                    "data": [
                        _candidate(
                            set_name="PokeTrace Base 1999",
                            set_slug="poketrace-base-1999",
                        )
                    ]
                }
            ]
        )
        provider = _provider(session, (_mapping(),))
        identity = _identity()
        self.assertTrue(provider.register_search_alias(identity, _alias()))
        self.assertTrue(provider.register_set_provenance(identity, _provenance()))
        resolver = PokeTraceIdentityResolver(provider)

        result = resolver.resolve_identity(identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.identity, identity)
        self.assertEqual(result.identity.set, "Set de Base")
        self.assertEqual(resolver.counters.candidates_all_three_before_bridge, 0)
        self.assertEqual(resolver.counters.candidates_all_three_after_bridge, 1)
        self.assertEqual(resolver.counters.candidates_name_number_bridged_set, 1)
        self.assertEqual(
            resolver.counters.candidates_all_three_variant_compatible_after_bridge,
            1,
        )

    def test_market_bridge_uses_exact_mapping_without_overwriting_identity(self):
        session = _Session(
            [
                {
                    "data": [
                        _candidate(
                            set_name="PokeTrace Base 1999",
                            set_slug="poketrace-base-1999",
                        )
                    ]
                }
            ]
        )
        provider = _provider(session, (_mapping(),))
        identity = _identity()
        provider.register_search_alias(identity, _alias())
        provider.register_set_provenance(identity, _provenance())

        snapshot = provider.snapshot_for(identity)

        self.assertIsNotNone(snapshot.us_values)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("32"))
        self.assertEqual(snapshot.us_values.matched_identity, identity)
        self.assertEqual(provider.set_bridge_registry.counters.set_bridge_exact, 1)
        self.assertEqual(provider.counters.candidates_all_three_before_bridge, 0)
        self.assertEqual(provider.counters.candidates_all_three_after_bridge, 1)
        self.assertEqual(provider.counters.candidates_name_number_bridged_set, 1)

    def test_provider_collision_blocks_otherwise_exact_market_candidate(self):
        left = _candidate(set_name="Base Set", set_id="pt-left")
        right = _candidate(set_name="Base Set", set_id="pt-right")
        session = _Session([{"data": [left, right]}])
        provider = _provider(session)
        identity = _identity()
        provider.register_search_alias(identity, _alias())
        provider.register_set_provenance(identity, _provenance())

        snapshot = provider.snapshot_for(identity)

        self.assertIsNone(snapshot.us_values)
        self.assertEqual(provider.counters.ambiguous, 1)
        self.assertGreaterEqual(
            provider.set_bridge_registry.counters.set_bridge_collision, 1
        )

    def test_bridge_does_not_bypass_premium_microvariant_gate(self):
        identity = _identity(card_name="Gyarados", set_name="Base Set")
        card = _candidate(set_name="Provider-only label")
        evidence = _candidate_evidence(
            identity,
            card,
            set_bridge=SetBridgeDecision(SET_BRIDGE_EXACT, BRIDGE_VERSIONED_MAPPING),
        )
        result = LocalMicrovariantValidator().resolve(
            identity,
            MicrovariantApplicability(MICROVARIANT_APPLICABLE, "TCGDEX_EXACT"),
            candidate=card,
        )
        self.assertIsNone(evidence.rejection)
        self.assertTrue(evidence.set_bridged)
        self.assertTrue(result.blocks_economics)


if __name__ == "__main__":
    unittest.main()
