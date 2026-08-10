from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from v5.market_values.poketrace import PokeTraceConfig
from v5.market_values.poketrace_free import (
    FreeTierPokeTraceProvider,
    free_tier_config_from_env,
    render_free_poketrace_counters,
)
from v5.models import CardIdentity


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(200, self.payload)


def identity():
    return CardIdentity(
        game="Pokemon TCG",
        card_name="Charizard",
        set="Base Set",
        card_number="4/102",
        language="English",
        variant="Holofoil",
    )


def free_payload():
    return {
        "data": [
            {
                "id": "free-card-id",
                "name": "Charizard",
                "cardNumber": "004/102",
                "set": {"name": "Base Set"},
                "variant": "Holofoil",
                "productType": "single",
                "currency": "USD",
                "prices": {
                    "ebay": {
                        "NEAR_MINT": {"median7d": 100},
                        # A Free response should not expose graded tiers, but
                        # include one here to prove the wrapper never accepts it.
                        "PSA_10": {"median7d": 999},
                    },
                    "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
                },
            }
        ]
    }


class PokeTraceFreeTierTests(unittest.TestCase):
    def test_free_mode_performs_one_us_request_and_never_eu(self):
        session = FakeSession(free_payload())
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="free-secret-key",
                minimum_request_interval_seconds=2.05,
            ),
            session=session,
        )

        snapshot = provider.snapshot_for(identity())

        self.assertEqual(len(session.calls), 1)
        params = session.calls[0][1]["params"]
        self.assertEqual(params["market"], "US")
        self.assertNotEqual(params["market"], "EU")
        self.assertIsNotNone(snapshot.us_values)
        self.assertIsNone(snapshot.cardmarket)
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        self.assertIsNone(snapshot.us_values.grade8_generic_value)
        self.assertIsNone(snapshot.us_values.grade9_generic_value)
        self.assertIsNone(snapshot.us_values.psa10_value)
        self.assertEqual(provider.counters.live_calls, 1)
        self.assertEqual(provider.counters.eu_matches, 0)

    def test_free_mode_caches_identity_without_spending_second_request(self):
        session = FakeSession(free_payload())
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="free-secret-key",
                minimum_request_interval_seconds=2.05,
            ),
            session=session,
        )
        provider.snapshot_for(identity())
        provider.snapshot_for(identity())
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(provider.counters.cache_hits, 1)

    def test_free_env_enforces_documented_burst_interval(self):
        with patch.dict(
            os.environ,
            {
                "POKETRACE_ENABLED": "true",
                "POKETRACE_API_KEY": "free-secret-key",
                "POKETRACE_MIN_REQUEST_INTERVAL_SECONDS": "0.1",
            },
            clear=False,
        ):
            config = free_tier_config_from_env()
        self.assertTrue(config.enabled)
        self.assertGreaterEqual(config.minimum_request_interval_seconds, 2.05)

    def test_free_summary_never_prints_api_key_or_cardmarket_claims(self):
        session = FakeSession(free_payload())
        provider = FreeTierPokeTraceProvider(
            config=PokeTraceConfig(
                enabled=True,
                api_key="free-secret-key",
                minimum_request_interval_seconds=2.05,
            ),
            session=session,
        )
        provider.snapshot_for(identity())
        rendered = render_free_poketrace_counters(provider)
        self.assertIn("plan mode: FREE_TEST", rendered)
        self.assertIn("EU/CardMarket requests: 0", rendered)
        self.assertIn("graded values accepted: 0", rendered)
        self.assertNotIn("free-secret-key", rendered)


if __name__ == "__main__":
    unittest.main()
