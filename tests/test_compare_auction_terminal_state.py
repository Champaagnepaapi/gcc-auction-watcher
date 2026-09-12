"""Real comparison + watcher inspection; only the browser boundary is replaced."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

import watcher
from compare_auction_discovery import resolve_legacy_ids


ITEM = '7a84f68f-80e6-42e2-8e46-52acf1de2d74'
URL = f'https://gradedcardcenter.com/item/{ITEM}'
NOW = datetime(2026, 9, 10, tzinfo=timezone.utc)


class Response:
    status = 200
    url = f'https://api.gradedcardcenter.com/on-sale-items/{ITEM}'
    headers = {'content-type': 'application/json'}

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Page:
    def __init__(self, *, body='Pikachu PSA 10\n50 €', payload=None, fail=False, redirect=None):
        self.body, self.payload, self.fail, self.redirect = body, payload, fail, redirect
        self.url, self.listeners, self.navigations = '', [], 0

    def on(self, event, callback):
        assert event == 'response'
        self.listeners.append(callback)

    def remove_listener(self, event, callback):
        self.listeners.remove(callback)

    def goto(self, url, **kwargs):
        self.navigations += 1
        if self.fail:
            raise RuntimeError('browser unavailable')
        self.url = self.redirect or url
        if self.payload is not None:
            for callback in self.listeners:
                callback(Response(self.payload))
        return SimpleNamespace(status=200)

    def wait_for_timeout(self, *_args):
        pass

    def locator(self, selector):
        text = 'Pikachu PSA 10' if selector == 'h1' else self.body
        locator = SimpleNamespace(inner_text=lambda **kwargs: text)
        locator.first = locator
        return locator


def terminal(**overrides):
    return dict({'id': ITEM, 'sellingType': 'AUCTION', 'status': 'ENDED',
                 'endTime': (NOW - timedelta(minutes=2)).isoformat()}, **overrides)


class AuctionTerminalTests(unittest.TestCase):
    def test_ended_regression_through_existing_comparison_api(self):
        page = Page(payload=terminal(endTime='2020-01-01T00:00:00Z'))
        lot = watcher.Lot(URL, 'Pikachu PSA 10', 50.0, source_type='auction')
        # Also runs against the original API: the pre-fix defect is an actual
        # ENDED item classified as unresolved, not just a missing diagnostic API.
        self.assertEqual(resolve_legacy_ids(page, [lot], 717), (set(), set()))

    def resolve(self, page, *, minutes=None):
        lot = watcher.Lot(URL, 'Pikachu PSA 10', 50.0, source_type='auction', minutes_to_end=minutes)
        diagnostics = {}
        result = resolve_legacy_ids(page, [lot], 717, diagnostics=diagnostics, observed_at=NOW)
        self.assertEqual(page.listeners, [])
        return result, diagnostics[URL], lot

    def test_valid_timer_uses_real_parser(self):
        result, diagnostic, _ = self.resolve(Page(body='Pikachu PSA 10\n50 €\n0 jours 0 heures 12 minutes 0 secondes'))
        self.assertEqual(result, ({URL}, set()))
        self.assertEqual(diagnostic['state'], 'RESOLVED')
        self.assertEqual(diagnostic['minutes'], 12)
        self.assertEqual(diagnostic['provenance'], 'item_countdown')

    def test_item_explicitly_ended_is_not_unknown_or_sold(self):
        page = Page(payload=terminal())
        result, diagnostic, lot = self.resolve(page)
        self.assertEqual(result, (set(), set()))
        self.assertEqual(diagnostic['state'], 'ENDED')
        self.assertEqual(diagnostic['item_id'], ITEM)
        self.assertFalse(diagnostic['sold_proven'])
        self.assertEqual(lot.source_type, 'auction')
        self.assertIsNone(lot.minutes_to_end)
        self.assertEqual(page.navigations, 1)

    def test_missing_timer_without_terminal_proof_still_fails(self):
        page = Page(body='Pikachu PSA 10\n50 €\nRelated items\nAuction ended')
        result, diagnostic, _ = self.resolve(page)
        self.assertEqual(result, (set(), {URL}))
        self.assertEqual(diagnostic['state'], 'UNKNOWN')
        self.assertEqual(page.navigations, 2)

    def test_inspection_error_is_distinct_and_retried(self):
        page = Page(fail=True)
        result, diagnostic, _ = self.resolve(page)
        self.assertEqual(result, (set(), {URL}))
        self.assertEqual(diagnostic['state'], 'INSPECTION_ERROR')
        self.assertEqual(page.navigations, 2)

    def test_wrong_item_active_future_or_payment_status_is_not_sold(self):
        for payload in (terminal(id='other'), terminal(status='ON_SALE'), terminal(sellingType='FIXED'),
                        terminal(endTime=(NOW + timedelta(minutes=2)).isoformat()),
                        terminal(endTime='unreadable')):
            with self.subTest(payload=payload):
                result, diagnostic, _ = self.resolve(Page(payload=payload))
                self.assertEqual(result, (set(), {URL}))
                self.assertEqual(diagnostic['state'], 'UNKNOWN')
        result, diagnostic, _ = self.resolve(Page(payload=terminal(status='WAITING_FOR_PAYMENT')))
        self.assertEqual(result, (set(), set()))
        self.assertEqual(diagnostic['state'], 'ENDED')
        self.assertFalse(diagnostic['sold_proven'])

    def test_redirect_or_contradictory_timer_blocks_terminal_proof(self):
        for page in (Page(payload=terminal(), redirect='https://gradedcardcenter.com/login'),
                     Page(payload=terminal(), body='Pikachu PSA 10\n50 €\n0 jours 0 heures 12 minutes 0 secondes')):
            with self.subTest(page=page):
                result, diagnostic, _ = self.resolve(page)
                self.assertEqual(result, (set(), {URL}))
                self.assertEqual(diagnostic['state'], 'UNKNOWN')

    def test_existing_timer_needs_no_navigation(self):
        page = Page(fail=True)
        result, diagnostic, _ = self.resolve(page, minutes=90)
        self.assertEqual(result, ({URL}, set()))
        self.assertEqual(diagnostic['provenance'], 'listing_timer')
        self.assertEqual(page.navigations, 0)
