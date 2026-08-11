from __future__ import annotations

import unittest

from v5.justtcg_identity import (
    JUSTTCG_FREE_MIN_REQUEST_INTERVAL_SECONDS,
    JustTCGIdentityResolver,
)
from v5.models import CardIdentity


class Response:
    def __init__(self, status_code, payload, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers or {}, params or {}))
        return Response(200, self.payload)


class SequenceSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.calls.append((url, headers or {}, params or {}))
        return self.responses.pop(0)


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def identity(**kwargs):
    data = dict(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
        finish="Holo",
    )
    data.update(kwargs)
    return CardIdentity(**data)


def card(*, name="Charizard", set_name="Base Set", number="004", printing="Holofoil", language="English"):
    return {
        "id": "pokemon-base-set-charizard-holo-rare",
        "uuid": "card-uuid",
        "name": name,
        "game": "Pokemon",
        "set": "base-set-pokemon",
        "set_name": set_name,
        "number": number,
        "rarity": "Rare Holo",
        "variants": [
            {
                "printing": printing,
                "language": language,
                "condition": "Near Mint",
                "price": 100,
            }
        ],
    }


def resolver_without_set_catalog(session, **kwargs):
    return JustTCGIdentityResolver(
        api_key="secret",
        session=session,
        use_set_catalog=False,
        **kwargs,
    )


class JustTCGIdentityTests(unittest.TestCase):
    def test_uses_q_and_number_but_accepts_only_local_exact_identity(self):
        session = Session({"data": [card()]})
        resolver = resolver_without_set_catalog(session)
        result = resolver.resolve_identity(identity())
        self.assertTrue(result.matched)
        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][2]
        self.assertEqual(params["game"], "pokemon")
        self.assertEqual(params["q"], "Charizard")
        self.assertEqual(params["number"], "4")
        self.assertEqual(params["limit"], "20")
        self.assertEqual(params["include_null_prices"], "true")
        self.assertEqual(params["include_price_history"], "false")
        self.assertNotIn("include_statistics", params)
        self.assertNotIn("set", params)
        self.assertEqual(resolver.counters.matches, 1)

    def test_set_catalog_resolves_stable_id_once_and_filters_card_query(self):
        fake = FakeTime()
        session = SequenceSession(
            [
                Response(
                    200,
                    {
                        "data": [
                            {"id": "jungle-pokemon", "name": "Jungle", "game": "pokemon"},
                            {"id": "base-set-pokemon", "name": "Base Set", "game": "pokemon"},
                        ]
                    },
                ),
                Response(200, {"data": [card()]}),
            ]
        )
        resolver = JustTCGIdentityResolver(
            api_key="secret",
            session=session,
            clock=fake.clock,
            sleeper=fake.sleep,
        )
        result = resolver.resolve_identity(identity())
        self.assertTrue(result.matched)
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[0][0].endswith("/v1/sets"))
        self.assertEqual(session.calls[0][2], {"game": "pokemon"})
        self.assertTrue(session.calls[1][0].endswith("/v1/cards"))
        self.assertEqual(session.calls[1][2]["set"], "base-set-pokemon")
        self.assertEqual(resolver.counters.set_catalog_queries, 1)
        self.assertEqual(resolver.counters.set_catalog_resolved, 1)
        self.assertGreaterEqual(fake.sleeps[0], JUSTTCG_FREE_MIN_REQUEST_INTERVAL_SECONDS)

    def test_set_catalog_is_cached_for_multiple_identities(self):
        fake = FakeTime()
        session = SequenceSession(
            [
                Response(200, {"data": [{"id": "base-set-pokemon", "name": "Base Set"}]}),
                Response(200, {"data": [card()]}),
                Response(200, {"data": [card(name="Blastoise", number="2")]}),
            ]
        )
        resolver = JustTCGIdentityResolver(
            api_key="secret",
            session=session,
            clock=fake.clock,
            sleeper=fake.sleep,
        )
        first = resolver.resolve_identity(identity())
        second = resolver.resolve_identity(
            identity(card_name="Blastoise", card_number="2/102")
        )
        self.assertTrue(first.matched)
        self.assertTrue(second.matched)
        self.assertEqual(resolver.counters.set_catalog_queries, 1)
        self.assertEqual(resolver.counters.set_catalog_resolved, 1)
        self.assertEqual(len(session.calls), 3)

    def test_ambiguous_set_catalog_mapping_blocks_card_query(self):
        fake = FakeTime()
        session = SequenceSession(
            [
                Response(
                    200,
                    {
                        "data": [
                            {"id": "base-set-a-pokemon", "name": "Base Set"},
                            {"id": "base-set-b-pokemon", "name": "Base Set"},
                        ]
                    },
                )
            ]
        )
        resolver = JustTCGIdentityResolver(
            api_key="secret", session=session, clock=fake.clock, sleeper=fake.sleep
        )
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.set_catalog_ambiguous, 1)

    def test_contained_but_distinct_set_name_is_not_a_catalog_alias(self):
        session = SequenceSession(
            [
                Response(
                    200,
                    {
                        "data": [
                            {
                                "id": "team-rocket-returns-pokemon",
                                "name": "Team Rocket Returns",
                            }
                        ]
                    },
                ),
                Response(
                    200,
                    {"data": [card(set_name="Team Rocket Returns")]},
                ),
            ]
        )
        resolver = JustTCGIdentityResolver(
            api_key="secret",
            session=session,
            sleeper=lambda _seconds: None,
        )

        result = resolver.resolve_identity(identity(set="Team Rocket"))

        self.assertFalse(result.matched)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.set_catalog_no_match, 1)

    def test_wrong_set_is_rejected(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card(set_name="Jungle")]})
        )
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_set, 1)

    def test_wrong_number_is_rejected(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card(number="5")]})
        )
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_number, 1)

    def test_wrong_language_variant_is_rejected(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card(language="Japanese")]})
        )
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_language, 1)

    def test_missing_variant_language_evidence_is_rejected(self):
        candidate = card()
        candidate.pop("variants")
        resolver = resolver_without_set_catalog(Session({"data": [candidate]}))

        result = resolver.resolve_identity(identity(finish=None))

        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_language, 1)

    def test_missing_listing_finish_does_not_accept_holo_printing(self):
        resolver = resolver_without_set_catalog(Session({"data": [card()]}))

        result = resolver.resolve_identity(identity(finish=None))

        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_variant, 1)

    def test_identity_cache_never_reuses_different_rarity_semantics(self):
        session = Session({"data": [card()]})
        resolver = resolver_without_set_catalog(session)

        self.assertTrue(resolver.resolve_identity(identity(rarity=None)).matched)
        special = resolver.resolve_identity(identity(rarity="Promo"))

        self.assertFalse(special.matched)
        self.assertEqual(resolver.counters.rejected_variant, 1)
        self.assertEqual(len(session.calls), 2)

    def test_first_edition_listing_requires_compatible_printing(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card(printing="Unlimited Holofoil")]})
        )
        result = resolver.resolve_identity(
            identity(edition="1st Edition", finish="Holo")
        )
        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.rejected_variant, 1)

    def test_first_edition_printing_can_support_listing(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card(printing="1st Edition Holofoil")]})
        )
        result = resolver.resolve_identity(
            identity(edition="1st Edition", finish="Holo")
        )
        self.assertTrue(result.matched)
        self.assertEqual(resolver.counters.variant_supported, 1)

    def test_multiple_equally_exact_cards_are_ambiguous(self):
        a = card()
        b = dict(card())
        b["uuid"] = "other-card"
        resolver = resolver_without_set_catalog(Session({"data": [a, b]}))
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertTrue(result.ambiguous)

    def test_minimum_interval_is_clamped_to_free_safe_value(self):
        resolver = resolver_without_set_catalog(
            Session({"data": [card()]}), min_request_interval_seconds=1.0
        )
        self.assertEqual(
            resolver.min_request_interval_seconds,
            JUSTTCG_FREE_MIN_REQUEST_INTERVAL_SECONDS,
        )

    def test_transient_429_honors_retry_after_and_retries_once(self):
        fake = FakeTime()
        session = SequenceSession(
            [
                Response(
                    429,
                    {"error": "slow down", "code": "RATE_LIMIT_EXCEEDED"},
                    {"Retry-After": "1"},
                ),
                Response(200, {"data": [card()]}),
            ]
        )
        resolver = resolver_without_set_catalog(
            session,
            clock=fake.clock,
            sleeper=fake.sleep,
        )
        result = resolver.resolve_identity(identity())
        self.assertTrue(result.matched)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(resolver.counters.rate_limited, 1)
        self.assertEqual(resolver.counters.retry_attempts, 1)
        self.assertGreaterEqual(fake.sleeps[0], JUSTTCG_FREE_MIN_REQUEST_INTERVAL_SECONDS)

    def test_daily_quota_429_is_not_retried(self):
        fake = FakeTime()
        session = SequenceSession(
            [Response(429, {"error": "quota", "code": "DAILY_LIMIT_EXCEEDED"})]
        )
        resolver = resolver_without_set_catalog(
            session,
            clock=fake.clock,
            sleeper=fake.sleep,
        )
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.daily_limit_exceeded, 1)
        self.assertEqual(resolver.counters.retry_attempts, 0)

    def test_bad_request_is_separately_counted(self):
        session = SequenceSession(
            [Response(400, {"error": "bad parameter", "code": "INVALID_REQUEST"})]
        )
        resolver = resolver_without_set_catalog(session)
        result = resolver.resolve_identity(identity())
        self.assertFalse(result.matched)
        self.assertEqual(resolver.counters.request_failures, 1)
        self.assertEqual(resolver.counters.bad_request, 1)


if __name__ == "__main__":
    unittest.main()
