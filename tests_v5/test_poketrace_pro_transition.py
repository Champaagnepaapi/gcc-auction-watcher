from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from v5.live_raw_pipeline_catalog import _build_poketrace_provider
from v5.market_values.poketrace import (
    PRO_MIN_REQUEST_INTERVAL_SECONDS,
    POKETRACE_MATCHED,
    POKETRACE_RATE_LIMITED,
    PokeTraceConfig,
    PokeTraceProvider,
    pro_tier_config_from_env,
)
from v5.market_values.poketrace_free import FreeTierPokeTraceProvider
from v5.models import (
    POKETRACE_PROVIDER,
    TCGDEX_EXACT_ENGLISH_TWIN,
    CardIdentity,
    ProviderSearchAlias,
)
from v5.poketrace_identity import PokeTraceIdentityResolver
from v5.poketrace_preflight import (
    PREFLIGHT_AUTH_REJECTED,
    PREFLIGHT_INVALID_SCHEMA,
    PREFLIGHT_MISSING_API_KEY,
    PREFLIGHT_PLAN_BELOW_PRO,
    PokeTracePlanPreflightConfig,
    render_poketrace_plan_preflight,
    run_poketrace_plan_preflight,
)


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Session:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responder(url, kwargs)


def _identity(*, localized=False, variant="Holofoil"):
    return CardIdentity(
        game="Pokémon TCG",
        card_name="Dracaufeu" if localized else "Charizard",
        set="Set de Base" if localized else "Base Set",
        card_number="4/102",
        language="French" if localized else "English",
        variant=variant,
    )


def _card(market, *, localized=False, variant="Holofoil", record_id=None):
    return {
        "id": record_id or f"{market.casefold()}-charizard",
        "name": "Dracaufeu" if localized else "Charizard",
        "cardNumber": "004/102",
        "set": {
            "name": "Set de Base" if localized else "Base Set",
            "slug": "base-set",
        },
        "variant": variant,
        "productType": "single",
        "market": market,
        "currency": "USD" if market == "US" else "EUR",
        "refs": {"cardmarketId": "273927" if market == "EU" else None},
        "prices": (
            {
                "ebay": {
                    "NEAR_MINT": {"median7d": 100},
                    "PSA_8": {"median7d": 140},
                    "PSA_9": {"median7d": 210},
                    "PSA_10": {"median7d": 500},
                },
                "tcgplayer": {"NEAR_MINT": {"median7d": 110}},
            }
            if market == "US"
            else {
                "cardmarket": {
                    "AGGREGATED": {
                        "avg": 100,
                        "avg1d": 100,
                        "avg7d": 102,
                        "avg30d": 104,
                    }
                },
                "cardmarket_unsold": {
                    "NEAR_MINT": {"low": 80, "median7d": 99}
                },
            }
        ),
    }


def _provider(session):
    return PokeTraceProvider(
        PokeTraceConfig(
            enabled=True,
            api_key="offline-placeholder",
            minimum_request_interval_seconds=0,
            max_retry_after_seconds=30,
        ),
        session=session,
        sleeper=lambda _seconds: None,
    )


class PokeTraceProPreflightTests(unittest.TestCase):
    def test_documented_rate_limit_headers_fill_missing_body_quota_safely(self):
        secret = "secret-header-fallback"
        session = _Session(
            lambda _url, _kwargs: _Response(
                payload={"data": {"active": True, "user": {}}},
                headers={
                    "x-plan": "Pro",
                    "X-RateLimit-Limit": "10000",
                    "x-ratelimit-remaining": "9750",
                    "X-RateLimit-Reset": "1786492800",
                    "X-Private-Diagnostic": "must-never-render",
                },
            )
        )

        result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key=secret),
            session=session,
        )
        rendered = render_poketrace_plan_preflight(result)

        self.assertTrue(result.accepted)
        self.assertEqual(result.plan, "PRO")
        self.assertEqual(result.daily_limit, 10000)
        self.assertEqual(result.daily_remaining, 9750)
        self.assertEqual(result.daily_used, 250)
        self.assertEqual(result.resets_at, "2026-08-12T00:00:00Z")
        self.assertNotIn(secret, rendered)
        self.assertNotIn("must-never-render", rendered)
        self.assertNotIn("X-RateLimit", rendered)

    def test_body_quota_has_precedence_over_conflicting_headers(self):
        session = _Session(
            lambda _url, _kwargs: _Response(
                payload={
                    "data": {
                        "active": True,
                        "user": {
                            "plan": "Growth",
                            "limit": 50000,
                            "remaining": 49900,
                            "resetsAt": "2026-08-13T00:00:00Z",
                        },
                    }
                },
                headers={
                    "X-Plan": "Free",
                    "X-RateLimit-Limit": "1",
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": "1786492800",
                },
            )
        )

        result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key="offline"),
            session=session,
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.plan, "GROWTH")
        self.assertEqual(result.daily_limit, 50000)
        self.assertEqual(result.daily_remaining, 49900)
        self.assertEqual(result.resets_at, "2026-08-13T00:00:00Z")

    def test_valid_pro_does_not_fail_when_usage_is_unavailable(self):
        session = _Session(
            lambda _url, _kwargs: _Response(
                payload={
                    "data": {"active": True, "user": {"plan": "Pro"}}
                }
            )
        )

        result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key="offline"),
            session=session,
        )

        self.assertTrue(result.accepted)
        self.assertIsNone(result.daily_limit)
        self.assertIsNone(result.daily_remaining)
        self.assertIsNone(result.daily_used)

    def test_official_pro_schema_is_accepted_and_render_is_safe(self):
        secret = "secret-never-render"
        session = _Session(
            lambda _url, _kwargs: _Response(
                payload={
                    "data": {
                        "key": secret,
                        "name": "private key name",
                        "active": True,
                        "user": {
                            "email": "private@example.test",
                            "plan": "Pro",
                            "remaining": 9876,
                            "limit": 10000,
                            "resetsAt": "2026-08-12T00:00:00Z",
                        },
                    }
                }
            )
        )

        result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key=secret),
            session=session,
        )
        rendered = render_poketrace_plan_preflight(result)

        self.assertTrue(result.accepted)
        self.assertEqual(result.plan, "PRO")
        self.assertEqual(result.daily_used, 124)
        self.assertEqual(result.resets_at, "2026-08-12T00:00:00Z")
        self.assertEqual(session.calls[0][0], "https://api.poketrace.com/v1/auth/info")
        self.assertEqual(session.calls[0][1]["headers"]["X-API-Key"], secret)
        for private in (secret, "private key name", "private@example.test", "user"):
            self.assertNotIn(private, rendered)

    def test_documented_higher_plans_are_accepted(self):
        for plan in ("Growth", "Scale"):
            with self.subTest(plan=plan):
                session = _Session(
                    lambda _url, _kwargs, plan=plan: _Response(
                        payload={
                            "data": {
                                "active": True,
                                "user": {"plan": plan},
                            }
                        }
                    )
                )
                result = run_poketrace_plan_preflight(
                    PokeTracePlanPreflightConfig(api_key="offline"),
                    session=session,
                )
                self.assertTrue(result.accepted)
                self.assertEqual(result.plan, plan.upper())

    def test_free_auth_and_bad_schema_fail_closed(self):
        free = _Session(
            lambda _url, _kwargs: _Response(
                payload={
                    "data": {"active": True, "user": {"plan": "Free"}}
                }
            )
        )
        malformed = _Session(lambda _url, _kwargs: _Response(payload={"data": {}}))

        free_result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key="offline"), session=free
        )
        malformed_result = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key="offline"), session=malformed
        )

        self.assertFalse(free_result.accepted)
        self.assertEqual(free_result.reason, PREFLIGHT_PLAN_BELOW_PRO)
        self.assertEqual(malformed_result.reason, PREFLIGHT_INVALID_SCHEMA)

    def test_missing_or_rejected_auth_never_reaches_pipeline(self):
        unused = _Session(lambda _url, _kwargs: self.fail("request not expected"))
        missing = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(), session=unused
        )
        rejected = run_poketrace_plan_preflight(
            PokeTracePlanPreflightConfig(api_key="offline"),
            session=_Session(lambda _url, _kwargs: _Response(status_code=401)),
        )

        self.assertEqual(missing.reason, PREFLIGHT_MISSING_API_KEY)
        self.assertEqual(unused.calls, [])
        self.assertEqual(rejected.reason, PREFLIGHT_AUTH_REJECTED)

    def test_pro_interval_and_free_provider_remain_separate(self):
        with patch.dict(
            "os.environ",
            {
                "GITHUB_ACTIONS": "true",
                "POKETRACE_ENABLED": "true",
                "POKETRACE_API_KEY": "offline",
                "POKETRACE_MIN_REQUEST_INTERVAL_SECONDS": "0.01",
            },
            clear=False,
        ):
            self.assertEqual(
                pro_tier_config_from_env().minimum_request_interval_seconds,
                PRO_MIN_REQUEST_INTERVAL_SECONDS,
            )
            with patch.dict("os.environ", {"POKETRACE_PLAN": "free"}):
                self.assertIsInstance(
                    _build_poketrace_provider(), FreeTierPokeTraceProvider
                )
            with patch.dict("os.environ", {"POKETRACE_PLAN": "pro"}):
                pro = _build_poketrace_provider()
                self.assertIs(type(pro), PokeTraceProvider)
                self.assertEqual(
                    pro.config.minimum_request_interval_seconds,
                    PRO_MIN_REQUEST_INTERVAL_SECONDS,
                )


class PokeTraceProMarketSeparationTests(unittest.TestCase):
    def test_us_and_eu_records_values_currencies_and_caches_stay_separate(self):
        us = _card("US", record_id="us-record")
        eu = _card("EU", record_id="eu-record")
        session = _Session(
            lambda _url, kwargs: _Response(
                payload={"data": [us if kwargs["params"]["market"] == "US" else eu]}
            )
        )
        provider = _provider(session)

        snapshot = provider.snapshot_for(_identity())

        self.assertEqual(snapshot.status, POKETRACE_MATCHED)
        self.assertEqual(snapshot.us_record_id, "us-record")
        self.assertEqual(snapshot.eu_record_id, "eu-record")
        self.assertEqual(snapshot.us_values.currency, "USD")
        self.assertEqual(snapshot.us_values.ungraded_value, Decimal("105"))
        self.assertEqual(snapshot.us_values.grade8_generic_value, Decimal("140"))
        self.assertEqual(snapshot.us_values.grade9_generic_value, Decimal("210"))
        self.assertEqual(snapshot.us_values.psa10_value, Decimal("500"))
        self.assertEqual(snapshot.cardmarket.currency, "EUR")
        self.assertEqual(snapshot.cardmarket.lowest_active_ask, Decimal("80"))
        self.assertEqual([call[1]["params"]["market"] for call in session.calls], ["US", "EU"])
        self.assertEqual(provider.counters.us_raw_available, 1)
        self.assertEqual(provider.counters.us_psa8_available, 1)
        self.assertEqual(provider.counters.us_psa9_available, 1)
        self.assertEqual(provider.counters.us_psa10_available, 1)
        self.assertEqual(provider.counters.eu_cardmarket_aggregated_available, 1)
        self.assertEqual(provider.counters.eu_active_ask_available, 1)

    def test_us_no_match_does_not_poison_eu_and_wrong_market_is_rejected(self):
        eu = _card("EU", record_id="eu-only")
        session = _Session(
            lambda _url, kwargs: _Response(
                payload={"data": [eu]}
                if kwargs["params"]["market"] == "US"
                else {"data": [eu]}
            )
        )
        provider = _provider(session)

        snapshot = provider.snapshot_for(_identity())

        self.assertIsNone(snapshot.us_values)
        self.assertEqual(snapshot.eu_record_id, "eu-only")
        self.assertEqual(provider.counters.market_mismatch_rejections, 1)
        self.assertEqual(provider.counters.us_clean_no_matches, 1)
        self.assertEqual(provider.counters.eu_matches, 1)

    def test_market_alias_searches_and_matches_are_split_by_market(self):
        localized = _identity(localized=True)
        alias = ProviderSearchAlias(
            provider=POKETRACE_PROVIDER,
            search_card_name="Charizard",
            search_set_name="Base Set",
            provenance=TCGDEX_EXACT_ENGLISH_TWIN,
            catalog_card_id="base1-4",
            catalog_set_id="base1",
            catalog_local_id="4",
        )
        us = _card("US")
        eu = _card("EU")
        session = _Session(
            lambda _url, kwargs: _Response(
                payload={
                    "data": [us if kwargs["params"]["market"] == "US" else eu]
                }
            )
        )
        provider = _provider(session)
        self.assertTrue(provider.register_search_alias(localized, alias))

        snapshot = provider.snapshot_for(localized)

        self.assertEqual(snapshot.us_values.matched_identity, localized)
        self.assertEqual(provider.counters.provider_alias_market_searches_us, 1)
        self.assertEqual(provider.counters.provider_alias_market_searches_eu, 1)
        self.assertEqual(provider.counters.alias_market_matches_us, 1)
        self.assertEqual(provider.counters.alias_market_matches_eu, 1)


class PokeTraceProIdentityFallbackTests(unittest.TestCase):
    def test_us_exact_stops_before_eu_and_primes_only_us_record(self):
        us = _card("US")
        session = _Session(lambda _url, _kwargs: _Response(payload={"data": [us]}))
        provider = _provider(session)
        resolver = PokeTraceIdentityResolver(provider)

        result = resolver.resolve_identity(_identity())

        self.assertTrue(result.matched)
        self.assertEqual(result.provider_market, "US")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.identity_us_exact_matches, 1)
        self.assertEqual(resolver.counters.eu_fallback_avoided_us_match, 1)
        self.assertEqual(resolver.counters.identity_eu_fallback_queries, 0)

    def test_only_clean_us_no_match_can_fall_back_to_eu(self):
        eu = _card("EU")
        session = _Session(
            lambda _url, kwargs: _Response(
                payload={"data": []}
                if kwargs["params"]["market"] == "US"
                else {"data": [eu]}
            )
        )
        provider = _provider(session)
        resolver = PokeTraceIdentityResolver(provider)

        result = resolver.resolve_identity(_identity())
        snapshot = provider.snapshot_for(result.identity)

        self.assertTrue(result.matched)
        self.assertEqual(result.provider_market, "EU")
        self.assertEqual(resolver.counters.identity_us_clean_no_matches, 1)
        self.assertEqual(resolver.counters.identity_eu_fallback_queries, 1)
        self.assertEqual(resolver.counters.identity_eu_exact_matches, 1)
        self.assertEqual(snapshot.eu_record_id, "eu-charizard")
        self.assertIsNone(snapshot.us_record_id)
        self.assertTrue(all(call[1]["params"]["market"] == "US" for call in session.calls[:-1]))
        self.assertEqual(session.calls[-1][1]["params"]["market"], "EU")

    def test_us_ambiguity_error_variant_conflict_and_rate_limit_suppress_eu(self):
        exact = _card("US")
        second = dict(exact, id="us-second")
        cases = {
            "ambiguous": _Response(payload={"data": [exact, second]}),
            "error": _Response(status_code=500),
            "variant": _Response(
                payload={"data": [_card("US", variant="Reverse Holofoil")]}
            ),
            "rate": _Response(status_code=429, headers={"Retry-After": "600"}),
        }
        for label, response in cases.items():
            with self.subTest(label=label):
                session = _Session(lambda _url, _kwargs, response=response: response)
                provider = _provider(session)
                resolver = PokeTraceIdentityResolver(provider)

                result = resolver.resolve_identity(_identity())

                self.assertFalse(result.matched)
                self.assertTrue(all(call[1]["params"]["market"] == "US" for call in session.calls))
                self.assertEqual(resolver.counters.identity_eu_fallback_queries, 0)
                if label == "rate":
                    self.assertEqual(result.provider_status, POKETRACE_RATE_LIMITED)

    def test_alias_can_match_in_eu_without_replacing_localized_identity(self):
        localized = _identity(localized=True)
        alias = ProviderSearchAlias(
            provider=POKETRACE_PROVIDER,
            search_card_name="Charizard",
            search_set_name="Base Set",
            provenance=TCGDEX_EXACT_ENGLISH_TWIN,
            catalog_card_id="base1-4",
            catalog_set_id="base1",
            catalog_local_id="4",
        )
        eu = _card("EU")
        session = _Session(
            lambda _url, kwargs: _Response(
                payload={"data": []}
                if kwargs["params"]["market"] == "US"
                else {"data": [eu]}
            )
        )
        provider = _provider(session)
        self.assertTrue(provider.register_search_alias(localized, alias))
        resolver = PokeTraceIdentityResolver(provider)

        result = resolver.resolve_identity(localized)

        self.assertTrue(result.matched)
        self.assertEqual(result.identity, localized)
        self.assertEqual(result.provider_market, "EU")
        self.assertEqual(resolver.counters.alias_identity_matches_eu, 1)
        self.assertGreater(resolver.counters.alias_identity_searches_us, 0)
        self.assertEqual(resolver.counters.alias_identity_searches_eu, 1)


if __name__ == "__main__":
    unittest.main()
