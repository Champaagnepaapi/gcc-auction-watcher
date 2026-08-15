from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from v5.market_values.poketrace import (
    POKETRACE_RATE_LIMITED,
    RATE_LIMIT_LONG_NON_RETRYABLE,
    RATE_LIMIT_SHORT_RETRYABLE,
    RATE_LIMIT_UNCLASSIFIED,
    PokeTraceConfig,
    classify_poketrace_429,
)
from v5.market_values.poketrace_free import (
    FreeTierPokeTraceProvider,
    render_free_poketrace_counters,
)
from v5.models import CardIdentity
from v5.poketrace_identity import (
    PokeTraceIdentityResolver,
    render_poketrace_identity_counters,
)
from v5.visual_identity import (
    LocalVisualIdentityResolver,
    render_visual_identity_counters,
)


class Response:
    def __init__(self, status_code=429, *, headers=None, payload=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.payload = payload

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("circuit breaker allowed an unexpected request")
        return self.responses.pop(0)


def identity(*, card_name="Charizard", set_name="Base Set"):
    return CardIdentity(
        game="Pokemon TCG",
        card_name=card_name,
        set=set_name,
        card_number="4/102",
        language="English",
        variant="Holofoil",
    )


def provider(session, *, sleeper=lambda _seconds: None):
    return FreeTierPokeTraceProvider(
        config=PokeTraceConfig(
            enabled=True,
            api_key="provider-secret-never-render",
            minimum_request_interval_seconds=0,
            max_retry_after_seconds=30,
        ),
        session=session,
        sleeper=sleeper,
    )


class PokeTraceCircuitBreakerTests(unittest.TestCase):
    def test_retry_after_classification_uses_header_only(self):
        short = classify_poketrace_429(
            Response(headers={"Retry-After": "2"}),
            max_retry_after_seconds=30,
        )
        long = classify_poketrace_429(
            Response(headers={"retry-after": "3600"}),
            max_retry_after_seconds=30,
        )
        unknown = classify_poketrace_429(
            Response(payload=AssertionError("provider body must not be read")),
            max_retry_after_seconds=30,
        )
        now = datetime(2026, 8, 11, 12, 0, tzinfo=timezone.utc)
        http_date = (now + timedelta(seconds=5)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        )
        dated = classify_poketrace_429(
            Response(headers={"Retry-After": http_date}),
            max_retry_after_seconds=30,
            now=now,
        )

        self.assertEqual(short.classification, RATE_LIMIT_SHORT_RETRYABLE)
        self.assertEqual(long.classification, RATE_LIMIT_LONG_NON_RETRYABLE)
        self.assertEqual(unknown.classification, RATE_LIMIT_UNCLASSIFIED)
        self.assertEqual(dated.classification, RATE_LIMIT_SHORT_RETRYABLE)
        self.assertEqual(dated.retry_after_seconds, 5)

    def test_long_429_opens_shared_breaker_and_skips_later_identity(self):
        session = Session(
            [
                Response(
                    headers={"Retry-After": "3600"},
                    payload=AssertionError("provider body must not be read"),
                )
            ]
        )
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)

        first = resolver.resolve_identity(identity())
        second = resolver.resolve_identity(
            identity(card_name="Blastoise", set_name="Base Set 2")
        )

        self.assertEqual(first.provider_status, POKETRACE_RATE_LIMITED)
        self.assertEqual(second.provider_status, POKETRACE_RATE_LIMITED)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.no_match, 0)
        self.assertEqual(resolver.counters.identities_skipped_after_breaker, 1)
        self.assertEqual(market.counters.terminal_429_detected, 1)
        self.assertEqual(market.counters.circuit_breaker_opened, 1)
        self.assertEqual(market.counters.calls_avoided_after_breaker, 1)

    def test_unclassified_429_is_terminal_without_reading_body(self):
        session = Session(
            [Response(payload=AssertionError("provider body must not be read"))]
        )
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)

        result = resolver.resolve_identity(identity())

        self.assertEqual(result.provider_status, POKETRACE_RATE_LIMITED)
        self.assertTrue(market.circuit_open)
        self.assertEqual(market.counters.unclassified_429, 1)
        self.assertEqual(resolver.counters.unclassified_429, 1)

    def test_second_short_429_exhausts_retry_and_opens_breaker(self):
        waits = []
        session = Session(
            [
                Response(headers={"Retry-After": "1"}),
                Response(headers={"Retry-After": "1"}),
            ]
        )
        market = provider(session, sleeper=waits.append)
        resolver = PokeTraceIdentityResolver(market)

        result = resolver.resolve_identity(identity())

        self.assertEqual(result.provider_status, POKETRACE_RATE_LIMITED)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(resolver.counters.retry_attempts, 1)
        self.assertEqual(market.counters.retryable_429, 2)
        self.assertEqual(market.counters.terminal_429_detected, 1)
        self.assertEqual(market.counters.circuit_breaker_opened, 1)
        self.assertTrue(waits)

    def test_market_lookup_after_breaker_is_rate_limited_not_no_match(self):
        session = Session([Response(headers={"Retry-After": "600"})])
        market = provider(session)

        first = market.snapshot_for(identity())
        second = market.snapshot_for(
            identity(card_name="Blastoise", set_name="Base Set 2")
        )

        self.assertEqual(first.status, POKETRACE_RATE_LIMITED)
        self.assertEqual(second.status, POKETRACE_RATE_LIMITED)
        self.assertEqual(market.counters.no_match, 0)
        self.assertEqual(market.counters.calls_avoided_after_breaker, 1)
        self.assertEqual(len(session.calls), 1)

    def test_visual_and_ocr_candidate_search_is_skipped_after_breaker(self):
        session = Session([])
        market = provider(session)
        market._record_rate_limit(Response(headers={"Retry-After": "600"}))
        resolver = PokeTraceIdentityResolver(market)
        ebay_fetches = []
        visual = LocalVisualIdentityResolver(
            resolver,
            ebay_image_fetcher=lambda url: ebay_fetches.append(url),
            candidate_image_fetcher=lambda _url: None,
            enabled=True,
        )

        result = visual.resolve_identity(
            identity(),
            ["https://i.ebayimg.com/example.png"],
        )

        self.assertFalse(result.matched)
        self.assertEqual(session.calls, [])
        self.assertEqual(ebay_fetches, [])
        self.assertEqual(visual.counters.attempted, 0)
        self.assertEqual(
            visual.counters.visual_searches_skipped_after_breaker,
            1,
        )
        self.assertEqual(market.counters.calls_avoided_after_breaker, 1)

    def test_baseline_shape_avoids_fourteen_calls_after_first_terminal_429(self):
        session = Session([Response(headers={"Retry-After": "600"})])
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)
        resolver.resolve_identity(identity())

        for index in range(8):
            resolver.resolve_identity(
                identity(
                    card_name=f"Card {index}",
                    set_name=f"Set {index}",
                )
            )

        visual = LocalVisualIdentityResolver(
            resolver,
            ebay_image_fetcher=lambda _url: None,
            enabled=True,
        )
        for index in range(6):
            visual.resolve_identity(
                identity(card_name=f"Visual Card {index}"),
                [f"https://i.ebayimg.com/{index}.png"],
            )

        self.assertEqual(len(session.calls), 1)
        self.assertEqual(resolver.counters.identities_skipped_after_breaker, 8)
        self.assertEqual(
            visual.counters.visual_searches_skipped_after_breaker,
            6,
        )
        self.assertEqual(market.counters.calls_avoided_after_breaker, 14)

    def test_aggregate_renderers_never_expose_provider_or_listing_data(self):
        session = Session(
            [
                Response(
                    headers={"Retry-After": "600"},
                    payload={
                        "secret": "provider-secret-never-render",
                        "title": "listing-title-never-render",
                    },
                )
            ]
        )
        market = provider(session)
        resolver = PokeTraceIdentityResolver(market)
        resolver.resolve_identity(identity())
        visual = LocalVisualIdentityResolver(
            resolver,
            ebay_image_fetcher=lambda _url: None,
            enabled=True,
        )
        visual.resolve_identity(identity(), ["https://i.ebayimg.com/private.png"])

        rendered = "\n".join(
            (
                render_poketrace_identity_counters(resolver),
                render_free_poketrace_counters(market),
                render_visual_identity_counters(visual),
            )
        )
        self.assertIn("terminal 429 detected: 1", rendered)
        self.assertIn("circuit breaker opened: 1", rendered)
        self.assertIn("calls avoided after breaker: 1", rendered)
        self.assertIn("visual searches skipped after breaker: 1", rendered)
        self.assertNotIn("provider-secret-never-render", rendered)
        self.assertNotIn("listing-title-never-render", rendered)
        self.assertNotIn("ebayimg", rendered)


if __name__ == "__main__":
    unittest.main()
