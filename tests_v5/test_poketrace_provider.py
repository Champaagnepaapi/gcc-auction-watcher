import unittest
from decimal import Decimal

from v5.market_values.poketrace import (
    CARDMARKET_DISCOUNT,
    CARDMARKET_FALLING_MARKET,
    POKETRACE_DISABLED,
    POKETRACE_MATCHED,
    PokeTraceConfig,
    PokeTraceProvider,
)
from v5.models import CardIdentity


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, us_payload=None, eu_payload=None, status_code=200):
        self.us_payload = us_payload or {"data": []}
        self.eu_payload = eu_payload or {"data": []}
        self.status_code = status_code
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        market = kwargs.get("params", {}).get("market")
        payload = self.us_payload if market == "US" else self.eu_payload
        return FakeResponse(self.status_code, payload)


def identity():
    return CardIdentity(
        game="Pokémon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
        variant="Holofoil",
    )


def card(market, prices):
    return {
        "id": "us-charizard" if market == "US" else "eu_273927",
        "name": "Charizard",
        "cardNumber": "004/102",
        "set": {"name": "Base Set", "slug": "base-set"},
        "variant": "Holofoil",
        "productType": "single",
        "market": market,
        "currency": "USD" if market == "US" else "EUR",
        "refs": {
            "tcgplayerId": "123" if market == "US" else None,
            "cardmarketId": "273927" if market == "EU" else None,
        },
        "prices": prices,
        "lastUpdated": "2026-08-10T20:00:00Z",
    }


class PokeTraceProviderTests(unittest.TestCase):
    def provider(self, session):
        return PokeTraceProvider(
            PokeTraceConfig(
                enabled=True,
                api_key="secret-never-render",
                minimum_request_interval_seconds=0,
            ),
            session=session,
        )

    def test_us_values_and_cardmarket_discount_are_resolved_together(self):
        us = card(
            "US",
            {
                "ebay": {
                    "NEAR_MINT": {"median7d": 100},
                    "PSA_9": {"median7d": 200},
                    "PSA_10": {"median7d": 500},
                },
                "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
            },
        )
        eu = card(
            "EU",
            {
                "cardmarket": {
                    "AGGREGATED": {
                        "avg": 100,
                        "avg1d": 100,
                        "avg7d": 105,
                        "avg30d": 110,
                    }
                },
                "cardmarket_unsold": {
                    "NEAR_MINT": {
                        "low": 70,
                        "median7d": 102,
                        "median30d": 108,
                    }
                },
            },
        )
        session = FakeSession({"data": [us]}, {"data": [eu]})
        provider = self.provider(session)

        snapshot = provider.snapshot_for(identity())

        self.assertEqual(snapshot.status, POKETRACE_MATCHED)
        self.assertIsNotNone(snapshot.us_values)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        self.assertEqual(snapshot.us_values.grade9_generic_value, Decimal("200"))
        self.assertEqual(snapshot.us_values.psa10_value, Decimal("500"))
        self.assertEqual(snapshot.cardmarket.status, CARDMARKET_DISCOUNT)
        self.assertEqual(snapshot.cardmarket.lowest_active_ask, Decimal("70"))
        self.assertEqual(snapshot.cardmarket.cardmarket_id, "273927")
        self.assertEqual(provider.counters.cardmarket_discount_signals, 1)
        self.assertEqual(len(session.calls), 2)
        for _, kwargs in session.calls:
            self.assertEqual(kwargs["headers"]["X-API-Key"], "secret-never-render")
            self.assertEqual(kwargs["params"]["product_type"], "single")

    def test_falling_market_guard_blocks_naive_discount_signal(self):
        us = card(
            "US",
            {
                "ebay": {"NEAR_MINT": {"median7d": 90}},
                "tcgplayer": {"NEAR_MINT": {"median7d": 90}},
            },
        )
        eu = card(
            "EU",
            {
                "cardmarket": {
                    "AGGREGATED": {
                        "avg": 80,
                        "avg1d": 70,
                        "avg7d": 90,
                        "avg30d": 110,
                    }
                },
                "cardmarket_unsold": {
                    "NEAR_MINT": {
                        "low": 60,
                        "median7d": 90,
                        "median30d": 100,
                    }
                },
            },
        )
        provider = self.provider(FakeSession({"data": [us]}, {"data": [eu]}))

        snapshot = provider.snapshot_for(identity())

        self.assertEqual(snapshot.cardmarket.status, CARDMARKET_FALLING_MARKET)
        self.assertTrue(snapshot.cardmarket.falling_market)
        self.assertEqual(provider.counters.cardmarket_falling_market_guards, 1)
        self.assertEqual(provider.counters.cardmarket_discount_signals, 0)

    def test_exact_card_identity_is_required(self):
        wrong = card(
            "US",
            {
                "ebay": {"NEAR_MINT": {"median7d": 100}},
                "tcgplayer": {},
            },
        )
        wrong["cardNumber"] = "5/102"
        provider = self.provider(FakeSession({"data": [wrong]}, {"data": []}))

        snapshot = provider.snapshot_for(identity())

        self.assertIsNone(snapshot.us_values)
        self.assertIsNone(snapshot.cardmarket)
        self.assertEqual(provider.counters.no_match, 1)

    def test_cache_avoids_duplicate_market_calls(self):
        us = card(
            "US",
            {
                "ebay": {"NEAR_MINT": {"median7d": 100}},
                "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
            },
        )
        session = FakeSession({"data": [us]}, {"data": []})
        provider = self.provider(session)

        first = provider.snapshot_for(identity())
        second = provider.snapshot_for(identity())

        self.assertEqual(first, second)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(provider.counters.cache_hits, 1)

    def test_disabled_provider_never_calls_network_or_leaks_key_in_repr(self):
        session = FakeSession()
        config = PokeTraceConfig(
            enabled=False,
            api_key="secret-never-render",
            minimum_request_interval_seconds=0,
        )
        provider = PokeTraceProvider(config, session=session)

        snapshot = provider.snapshot_for(identity())

        self.assertEqual(snapshot.status, POKETRACE_DISABLED)
        self.assertEqual(session.calls, [])
        self.assertNotIn("secret-never-render", repr(config))

    def test_rate_limit_is_counted_without_retrying(self):
        session = FakeSession(status_code=429)
        provider = self.provider(session)

        snapshot = provider.snapshot_for(identity())

        self.assertIsNone(snapshot.us_values)
        self.assertEqual(provider.counters.rate_limited, 2)
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
