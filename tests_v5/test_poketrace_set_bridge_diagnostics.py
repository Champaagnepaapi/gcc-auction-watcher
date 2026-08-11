from __future__ import annotations

import unittest

from tests_v5.test_poketrace_identity_regressions import (
    _Session,
    _candidate,
    _identity,
    _provider,
)
from v5.models import POKETRACE_PROVIDER, ProviderSearchAlias
from v5.poketrace_identity import PokeTraceIdentityResolver, render_poketrace_identity_counters
from v5.poketrace_matching import REJECT_SET, _candidate_evidence


class PokeTraceSetBridgeDiagnosticTests(unittest.TestCase):
    def resolver(self):
        return PokeTraceIdentityResolver(_provider(_Session([])))

    def test_slug_and_unresolved_name_number_are_counted_without_acceptance(self):
        resolver = self.resolver()
        listing = _identity(set_name="Base Set")
        card = _candidate(set_name="Jungle")
        evidence = _candidate_evidence(listing, card)
        resolver._count_match_evidence(
            evidence,
            search_identity=listing,
            listing_identity=listing,
            candidate=card,
        )
        self.assertEqual(evidence.rejection, REJECT_SET)
        self.assertEqual(resolver.counters.near_set_slug_available, 1)
        self.assertEqual(
            resolver.counters.near_set_name_number_exact_set_unresolved, 1
        )

    def test_missing_slug_is_distinct(self):
        resolver = self.resolver()
        listing = _identity(set_name="Base Set")
        card = _candidate(set_name="Jungle")
        card["set"].pop("slug")
        resolver._count_match_evidence(
            _candidate_evidence(listing, card),
            search_identity=listing,
            listing_identity=listing,
            candidate=card,
        )
        self.assertEqual(resolver.counters.near_set_slug_missing, 1)

    def test_exact_tcgdex_twin_provenance_counts_as_bridge_only(self):
        resolver = self.resolver()
        listing = _identity(set_name="Set de Base", language="French")
        search = _identity(set_name="Base Set")
        card = _candidate(set_name="Jungle")
        alias = ProviderSearchAlias(
            provider=POKETRACE_PROVIDER,
            search_card_name="Charizard",
            search_set_name="Base Set",
            provenance="TCGDEX_EXACT_ENGLISH_TWIN",
            catalog_card_id="base1-4",
            catalog_set_id="base1",
            catalog_local_id="4",
        )
        evidence = _candidate_evidence(search, card)
        resolver._count_match_evidence(
            evidence,
            search_identity=search,
            listing_identity=listing,
            candidate=card,
            provider_alias=alias,
        )
        self.assertEqual(evidence.rejection, REJECT_SET)
        self.assertEqual(
            resolver.counters.near_set_tcgdex_exact_bridge_available, 1
        )
        self.assertEqual(resolver.counters.matches, 0)

    def test_same_slug_with_distinct_set_names_is_aggregate_collision(self):
        left = _candidate(set_name="Jungle")
        right = _candidate(set_name="Jungle Expansion")
        left["set"]["slug"] = "shared-slug"
        right["set"]["slug"] = "shared-slug"
        payload = {"data": [left, right]}
        session = _Session([payload] * 6)
        resolver = PokeTraceIdentityResolver(_provider(session))
        resolver.resolve_identity(_identity(set_name="Base Set"))
        self.assertEqual(resolver.counters.candidate_set_id_slug_collisions, 1)

    def test_renderer_exposes_only_aggregate_bridge_labels(self):
        resolver = self.resolver()
        rendered = render_poketrace_identity_counters(resolver)
        self.assertIn("exact TCGdex bridge available: 0", rendered)
        self.assertIn("acceptance unchanged", rendered)
        self.assertNotIn("Set de Base", rendered)


if __name__ == "__main__":
    unittest.main()
