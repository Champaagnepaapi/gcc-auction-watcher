from __future__ import annotations

import unittest

from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import CardIdentity
from v5.poketrace_identity import (
    PokeTraceIdentityResolver,
    REJECT_CARD_NUMBER,
    REJECT_SET,
    _candidate_score_and_rejection,
    _partial_card_number_equivalent,
)


class Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payload)


def identity(*, card_number="4", set_name="Pokemon TCG Base Set"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name="Charizard",
        set=set_name,
        card_number=card_number,
        language="English",
        variant="Holofoil",
    )


def candidate(*, card_number="004/102", set_name="Base Set"):
    return {
        "id": "pt-charizard-base-4",
        "name": "Charizard",
        "cardNumber": card_number,
        "set": {"name": set_name, "slug": set_name.casefold().replace(" ", "-")},
        "variant": "Holofoil",
        "rarity": "Rare Holo",
        "productType": "single",
        "market": "US",
        "currency": "USD",
        "prices": {
            "ebay": {"NEAR_MINT": {"median7d": 100}},
            "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
        },
    }


def provider(session):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        ),
        session=session,
        sleeper=lambda _seconds: None,
    )


class PartialCardNumberCompatibilityTests(unittest.TestCase):
    def test_numerator_only_matches_full_canonical_number_with_exact_name_and_strong_set(self):
        card = candidate(card_number="004/102")
        score, rejection = _candidate_score_and_rejection(identity(card_number="4"), card)

        self.assertIsNone(rejection)
        self.assertIsNotNone(score)
        self.assertTrue(
            _partial_card_number_equivalent(
                "4",
                "004/102",
                exact_name=True,
                set_similarity=0.86,
            )
        )

        session = Session({"data": [card]})
        resolver = PokeTraceIdentityResolver(provider(session))
        resolved = resolver.resolve_identity(identity(card_number="4"))

        self.assertTrue(resolved.matched)
        self.assertEqual(resolved.identity.card_number, "004/102")
        self.assertEqual(resolver.counters.partial_number_candidates, 1)
        self.assertEqual(resolver.counters.partial_number_matches, 1)
        self.assertEqual(resolver.counters.rejected_card_number, 0)

    def test_two_conflicting_full_numbers_remain_a_hard_reject(self):
        score, rejection = _candidate_score_and_rejection(
            identity(card_number="4/102", set_name="Base Set"),
            candidate(card_number="4/130", set_name="Base Set"),
        )
        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_CARD_NUMBER)
        self.assertFalse(
            _partial_card_number_equivalent(
                "4/102",
                "4/130",
                exact_name=True,
                set_similarity=1.0,
            )
        )

    def test_partial_number_never_overrides_wrong_set(self):
        score, rejection = _candidate_score_and_rejection(
            identity(card_number="4", set_name="Base Set"),
            candidate(card_number="004/102", set_name="Jungle"),
        )
        self.assertIsNone(score)
        self.assertEqual(rejection, REJECT_SET)

    def test_partial_number_never_overrides_wrong_name(self):
        card = candidate(card_number="004/102", set_name="Base Set")
        card["name"] = "Blastoise"
        score, rejection = _candidate_score_and_rejection(
            identity(card_number="4", set_name="Base Set"),
            card,
        )
        self.assertIsNone(score)
        self.assertNotEqual(rejection, None)


if __name__ == "__main__":
    unittest.main()
