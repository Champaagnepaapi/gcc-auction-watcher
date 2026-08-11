from __future__ import annotations

import unittest

from v5.market_values.poketrace import (
    PokeTraceConfig,
    _candidate_matches,
)
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import (
    PokeTraceIdentityResolver,
    REJECT_CARD_NAME,
    REJECT_SET,
    _candidate_score_and_rejection,
)


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.payloads:
            raise AssertionError("unexpected PokeTrace request")
        return _Response(self.payloads.pop(0))


def _identity(
    *,
    card_name="Charizard",
    set_name="Pokemon TCG Base Set",
    card_number="4/102",
):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=card_name,
        set=set_name,
        card_number=card_number,
        language="English",
        variant="Holofoil",
    )


def _candidate(
    *,
    card_name="Charizard",
    set_name="Base Set",
    card_number="004/102",
):
    return {
        "id": "pt-card",
        "name": card_name,
        "cardNumber": card_number,
        "set": {"name": set_name, "slug": set_name.casefold().replace(" ", "-")},
        "variant": "Holofoil",
        "productType": "single",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 100}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
        },
    }


def _provider(session):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
        sleeper=lambda _seconds: None,
    )


class PokeTraceIdentityRegressionTests(unittest.TestCase):
    def test_identity_and_market_accept_same_conservative_set_alias_and_partial_number(self):
        identity = _identity(card_number="4")
        candidate = _candidate(card_number="004/102")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNotNone(score)
        self.assertIsNone(rejection)
        self.assertTrue(_candidate_matches(identity, candidate))

    def test_distinct_numbered_set_is_rejected_even_when_base_tokens_overlap(self):
        identity = _identity(set_name="Base Set")
        candidate = _candidate(set_name="Base Set 2")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_SET)
        self.assertFalse(_candidate_matches(identity, candidate))

    def test_meaningful_name_suffix_case_is_not_erased(self):
        identity = _identity(card_name="Charizard EX")
        candidate = _candidate(card_name="Charizard ex")

        score, rejection = _candidate_score_and_rejection(identity, candidate)

        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_CARD_NAME)
        self.assertFalse(_candidate_matches(identity, candidate))

    def test_structured_retrieval_replaces_concatenated_primary_search(self):
        session = _Session([{"data": [_candidate()]}])
        resolver = PokeTraceIdentityResolver(_provider(session))

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["search"], "Charizard")
        self.assertEqual(params["card_number"], "4/102")
        self.assertEqual(params["set"], "Pokemon TCG Base Set")
        self.assertEqual(resolver.counters.structured_searches, 1)

    def test_candidate_field_counters_are_independent_of_rejection_order(self):
        wrong_name = _candidate(card_name="Blastoise")
        session = _Session([{"data": [wrong_name]}, {"data": []}])
        resolver = PokeTraceIdentityResolver(_provider(session))

        result = resolver.resolve_identity(_identity())

        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.candidates_name_matched, 0)
        self.assertEqual(resolver.counters.candidates_set_matched, 1)
        self.assertEqual(resolver.counters.candidates_card_number_matched, 1)
        self.assertEqual(resolver.counters.candidates_set_number_matched, 1)
        self.assertEqual(resolver.counters.candidates_failing_only_name, 1)
        self.assertGreaterEqual(
            resolver.counters.candidate_queries_without_exact_match, 1
        )
        self.assertEqual(resolver.counters.zero_candidate_queries, 1)

    def test_primed_identity_snapshot_counts_avoided_market_request(self):
        session = _Session([{"data": [_candidate()]}])
        market = _provider(session)
        resolver = PokeTraceIdentityResolver(market)

        resolved = resolver.resolve_identity(_identity())
        snapshot = market.snapshot_for(resolved.identity)

        self.assertIsNotNone(snapshot.us_values)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(market.counters.primed_market_calls_avoided, 1)


if __name__ == "__main__":
    unittest.main()
