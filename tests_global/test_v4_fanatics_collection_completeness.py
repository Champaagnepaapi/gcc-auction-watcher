"""Browser-boundary regression of the production Fanatics scanner."""
from datetime import datetime, timezone
import contextlib
import functools
import io
import os
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import v4_global_marketplace_fanatics_native_v2 as v2
import v4_global_marketplace_fanatics_provider_language as provider


URL = 'https://www.fanaticscollect.com/buy-now/7922000d-352c-4290-b0eb-29578d712424'


class Page:
    def __init__(self, snapshots, *, status=200, redirect=None):
        self.snapshots = snapshots
        self.status = status
        self.url = redirect or v2.FANATICS_POKEMON_BROWSE
        self.observations = 0
        self.waits = []

    def goto(self, *_args, **_kwargs):
        return SimpleNamespace(status=self.status)

    def wait_for_timeout(self, ms):
        self.waits.append(ms)

    def evaluate(self, script):
        if 'scrollTo' in script:
            return None
        state = self.snapshots[min(self.observations, len(self.snapshots)-1)]
        self.observations += 1
        # Support the old collector as well, so pre-fix failures are behavioral.
        if 'container_present' not in script:
            return state.get('hrefs', [])
        return state

    def content(self):
        return '<html></html>'


def runtime_case(method):
    @functools.wraps(method)
    def run(self):
        if os.environ.get("FANATICS_COLLECTION_CHILD") == "1":
            return method(self)
        child = subprocess.run([sys.executable, "-m", "unittest", "tests_global." + self.id().removeprefix("tests_global.")],
            env=dict(os.environ, FANATICS_COLLECTION_CHILD="1"), capture_output=True, text=True)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
    return run


class FanaticsCollectionTests(unittest.TestCase):
    @runtime_case
    def test_next_page_outside_main_is_followed_only_when_unique(self):
        other = URL.replace('7922000d', '8922000d')
        class NavigationPage(Page):
            def __init__(self, count=1, disabled=False):
                super().__init__([{'container_present': True, 'hrefs': [URL]}])
                self.matches, self.disabled, self.clicks = count, disabled, 0
            def locator(self, selector):
                # The inventory is inside main; its pagination is a sibling.
                return SimpleNamespace(get_by_role=lambda *a, **k: SimpleNamespace(count=lambda: 0))
            def get_by_role(self, role, *, name, exact):
                assert (role, name, exact) == ('button', 'Go to next page', True)
                return self
            def count(self): return self.matches
            def is_visible(self): return True
            def is_enabled(self): return not self.disabled and not self.clicks
            def get_attribute(self, name): return 'true' if self.disabled else None
            def click(self, **kwargs):
                self.clicks += 1
                self.snapshots = [{'container_present': True, 'hrefs': [other]}]
        page = NavigationPage()
        result = v2._fanatics_pokemon_urls(page, scroll_rounds=10)
        self.assertEqual(result.urls, [URL, other])
        self.assertEqual(page.clicks, 1)
        self.assertFalse(result.complete)
        for page in (NavigationPage(count=2), NavigationPage(disabled=True)):
            result = v2._fanatics_pokemon_urls(page, scroll_rounds=10)
            self.assertEqual(result.urls, [URL])
            self.assertEqual(page.clicks, 0)
            self.assertIn('pagination=', result.detail)

    @runtime_case
    def test_real_next_page_control_collects_second_page(self):
        other = URL.replace('7922000d', '8922000d')
        class PagedPage(Page):
            def __init__(self):
                super().__init__([{'container_present': True, 'hrefs': [URL]}])
                self.clicks = 0
            def locator(self, selector):
                assert selector == 'main, [role="main"]'
                return self
            def get_by_role(self, role, *, name, exact):
                assert (role, name, exact) == ('button', 'Go to next page', True)
                return self
            def count(self):
                return 1
            def is_visible(self):
                return True
            def is_enabled(self):
                return self.clicks == 0
            def get_attribute(self, name):
                return None
            def click(self, **kwargs):
                self.clicks += 1
                self.snapshots = [{'container_present': True, 'hrefs': [other]}]
        page = PagedPage()
        result = v2._fanatics_pokemon_urls(page, scroll_rounds=10)
        self.assertEqual(result.urls, [URL, other])
        self.assertEqual(page.clicks, 1)
        self.assertFalse(result.complete)

    @runtime_case
    def test_stable_results_without_total_are_not_exhaustive(self):
        result = v2._fanatics_pokemon_urls(Page([{'container_present': True, 'hrefs': [URL]}]), scroll_rounds=8)
        self.assertEqual(result.urls, [URL])
        self.assertFalse(result.complete)

    @classmethod
    def setUpClass(cls):
        if os.environ.get("FANATICS_COLLECTION_CHILD") != "1":
            return
        import requests
        cls.http_guard = patch.object(requests.sessions.Session, "request",
                                      side_effect=AssertionError("unexpected HTTP"))
        cls.http_guard.start()
        cls.addClassCleanup(cls.http_guard.stop)
        import v4_global_marketplace_notify_resilient as runner
        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys, "argv", ["runner", "--help"]):
            try:
                runner.main()
            except SystemExit as status:
                assert status.code == 0
            runner.confirmed.install_global_external_market_stack()

    def scan_empty(self, page):
        return provider.v3.scan_fanatics_native_inventory_v3(
            page, (), observed_at=datetime.now(timezone.utc), scroll_rounds=8)

    @runtime_case
    def test_unproven_zero_is_incomplete(self):
        _, status = self.scan_empty(Page([{'container_present': False, 'hrefs': []}]))
        self.assertFalse(status.complete)
        self.assertEqual(status.status, 'UNAVAILABLE')
        self.assertIn('CONTENT_UNPROVEN', status.detail)

    @runtime_case
    def test_explicit_empty_is_complete(self):
        _, status = self.scan_empty(Page([{'container_present': True, 'empty_proven': True, 'hrefs': []}]))
        self.assertTrue(status.complete)
        self.assertIn('EMPTY_PROVEN', status.detail)

    @runtime_case
    def test_late_results_are_collected_after_two_empty_observations(self):
        page = Page([{'container_present': False, 'hrefs': []}]*3 +
                    [{'container_present': True, 'hrefs': [URL]}])
        result = v2._fanatics_pokemon_urls(page, scroll_rounds=8)
        urls, observations = result
        self.assertEqual(urls, [URL])
        self.assertGreaterEqual(observations, 4)
        self.assertLessEqual(sum(page.waits), 12000)

    @runtime_case
    def test_http_redirect_or_unexpected_dom_never_prove_empty(self):
        for kwargs in ({'status': 403}, {'status': 503}, {'redirect': 'https://www.fanaticscollect.com/login'},
                       {'redirect': 'https://www.fanaticscollect.com/marketplace?type=FIXED&similarQuery=Football'}):
            with self.subTest(kwargs=kwargs):
                _, status = self.scan_empty(Page([{'container_present': True, 'empty_proven': True, 'hrefs': []}], **kwargs))
                self.assertFalse(status.complete)
                self.assertEqual(status.status, 'UNAVAILABLE')

    @runtime_case
    def test_results_at_cap_are_not_complete(self):
        result = v2._fanatics_pokemon_urls(Page([{'container_present': True, 'hrefs': [URL]}]), scroll_rounds=1)
        self.assertFalse(getattr(result, 'complete', True))


if __name__ == '__main__':
    unittest.main()
