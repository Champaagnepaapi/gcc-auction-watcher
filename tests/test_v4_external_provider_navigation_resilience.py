import unittest
from unittest.mock import Mock, patch

import v4_external_provider_navigation_resilience as resilience
import watcher


class _Locator:
    def __init__(self, *, count=0, text=""):
        self._count = count
        self._text = text
        self.first = self

    def count(self):
        return self._count

    def inner_text(self, timeout=None):
        return self._text


class _Page:
    def __init__(
        self,
        *,
        target_url="https://www.ebay.fr/sch/i.html",
        fail=None,
        item_count=0,
        search_count=0,
        body="",
    ):
        self.url = "about:blank"
        self.target_url = target_url
        self.fail = fail
        self.item_count = item_count
        self.search_count = search_count
        self.body = body
        self.goto_calls = []

    def goto(self, url, *args, **kwargs):
        self.goto_calls.append((url, args, kwargs))
        self.url = self.target_url
        if self.fail is not None:
            raise self.fail
        return "ok"

    def locator(self, selector):
        if selector == resilience._EBAY_ITEM_SELECTOR:
            return _Locator(count=self.item_count)
        if selector == resilience._PSA_SEARCH_SELECTOR:
            return _Locator(count=self.search_count)
        if selector == "body":
            return _Locator(count=1, text=self.body)
        return _Locator()


class ExternalProviderNavigationResilienceTests(unittest.TestCase):
    def setUp(self):
        self.watcher_ebay = watcher.scrape_ebay_sold
        self.watcher_apr = watcher.scrape_psa_apr
        self.installed = resilience._INSTALLED
        self.original_ebay = resilience._ORIGINAL_SCRAPE_EBAY_SOLD
        self.original_apr = resilience._ORIGINAL_SCRAPE_PSA_APR

    def tearDown(self):
        watcher.scrape_ebay_sold = self.watcher_ebay
        watcher.scrape_psa_apr = self.watcher_apr
        resilience._INSTALLED = self.installed
        resilience._ORIGINAL_SCRAPE_EBAY_SOLD = self.original_ebay
        resilience._ORIGINAL_SCRAPE_PSA_APR = self.original_apr

    def test_ebay_timeout_with_structured_items_is_salvaged_without_retry(self):
        page = _Page(fail=TimeoutError("nav"), item_count=1)
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        with patch.object(watcher, "log") as log:
            result = proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon")

        self.assertIsNone(result)
        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(proxy.timeout_reason, "items")
        log.assert_called_once()

    def test_ebay_timeout_without_usable_dom_remains_fail_closed(self):
        page = _Page(fail=TimeoutError("nav"))
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        with self.assertRaises(TimeoutError):
            proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon")

        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(proxy.timeout_reason, "empty_dom")

    def test_ebay_timeout_challenge_page_is_salvaged_for_existing_classifier(self):
        page = _Page(fail=TimeoutError("nav"), body="Pardon our interruption")
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        result = proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon")

        self.assertIsNone(result)
        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(proxy.timeout_reason, "challenge")

    def test_psa_timeout_with_search_control_is_salvaged(self):
        page = _Page(
            target_url="https://www.psacard.com/auctionprices",
            fail=TimeoutError("nav"),
            search_count=1,
        )
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "psa_apr")

        result = proxy.goto("https://www.psacard.com/auctionprices")

        self.assertIsNone(result)
        self.assertEqual(len(page.goto_calls), 1)

    def test_psa_timeout_challenge_page_is_salvaged_for_existing_classifier(self):
        page = _Page(
            target_url="https://www.psacard.com/auctionprices",
            fail=TimeoutError("nav"),
            body="Access Denied - Cloudflare",
        )
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "psa_apr")

        self.assertIsNone(proxy.goto("https://www.psacard.com/auctionprices"))

    def test_psa_timeout_without_usable_dom_remains_fail_closed(self):
        page = _Page(
            target_url="https://www.psacard.com/auctionprices",
            fail=TimeoutError("nav"),
        )
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "psa_apr")

        with self.assertRaises(TimeoutError):
            proxy.goto("https://www.psacard.com/auctionprices")

    def test_redirect_to_other_host_is_never_salvaged(self):
        page = _Page(
            target_url="https://example.com/challenge",
            fail=TimeoutError("nav"),
            item_count=1,
            body="captcha",
        )
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        with self.assertRaises(TimeoutError):
            proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon")

        self.assertEqual(proxy.timeout_reason, "wrong_host")

    def test_non_timeout_exception_is_never_swallowed(self):
        page = _Page(fail=RuntimeError("boom"), item_count=1)
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        with self.assertRaises(RuntimeError):
            proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon")

        self.assertEqual(proxy.timeout_reason, "")

    def test_successful_navigation_result_is_unchanged(self):
        page = _Page(item_count=1)
        proxy = resilience.NavigationTimeoutSalvageProxy(page, "ebay")

        self.assertEqual(proxy.goto("https://www.ebay.fr/sch/i.html?q=pokemon"), "ok")
        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(proxy.timeout_reason, "")

    def test_ebay_wrapper_adds_only_safe_reason_to_provider_error_note(self):
        def delegate(page, *args, **kwargs):
            try:
                page.goto("https://www.ebay.fr/sch/i.html?q=pokemon")
            except TimeoutError:
                return watcher.ExternalScrapeResult(
                    [],
                    watcher.EXTERNAL_PROVIDER_ERROR,
                    "eBay navigation TimeoutError",
                )
            raise AssertionError("timeout should remain fail-closed")

        resilience._ORIGINAL_SCRAPE_EBAY_SOLD = delegate
        page = _Page(fail=TimeoutError("private payload must not surface"))

        result = resilience.resilient_scrape_ebay_sold(
            page, "lot", with_status=True
        )

        self.assertEqual(result.sales, [])
        self.assertEqual(result.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(
            result.note,
            "eBay navigation TimeoutError [nav_timeout=empty_dom]",
        )
        self.assertNotIn("private payload", result.note)
        self.assertEqual(len(page.goto_calls), 1)

    def test_safe_reason_never_changes_non_provider_error_result(self):
        result = watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_CLEAN_NO_MATCH, "clean"
        )

        annotated = resilience._annotate_ebay_timeout_result(result, "empty_dom")

        self.assertIs(annotated, result)
        self.assertEqual(annotated.note, "clean")

    def test_installer_wraps_current_scrapers_then_enables_hard_ebay_isolation(self):
        ebay_delegate = Mock(return_value="ebay-result")
        apr_delegate = Mock(return_value="apr-result")
        watcher.scrape_ebay_sold = ebay_delegate
        watcher.scrape_psa_apr = apr_delegate
        resilience._INSTALLED = False
        resilience._ORIGINAL_SCRAPE_EBAY_SOLD = None
        resilience._ORIGINAL_SCRAPE_PSA_APR = None

        with patch(
            "v4_ebay_hard_timeout_isolation.install_v4_ebay_hard_timeout_isolation"
        ) as hard_install:
            resilience.install_v4_external_provider_navigation_resilience()

        hard_install.assert_called_once_with()
        page = _Page()
        self.assertEqual(watcher.scrape_ebay_sold(page, "lot"), "ebay-result")
        self.assertEqual(watcher.scrape_psa_apr(page, "lot"), "apr-result")
        self.assertIsInstance(
            ebay_delegate.call_args.args[0],
            resilience.NavigationTimeoutSalvageProxy,
        )
        self.assertIsInstance(
            apr_delegate.call_args.args[0],
            resilience.NavigationTimeoutSalvageProxy,
        )
        self.assertEqual(ebay_delegate.call_args.args[0]._provider, "ebay")
        self.assertEqual(apr_delegate.call_args.args[0]._provider, "psa_apr")

    def test_child_worker_marker_skips_recursive_hard_isolation(self):
        ebay_delegate = Mock(return_value="ebay-result")
        watcher.scrape_ebay_sold = ebay_delegate
        resilience._INSTALLED = False
        resilience._ORIGINAL_SCRAPE_EBAY_SOLD = None
        resilience._ORIGINAL_SCRAPE_PSA_APR = None

        with (
            patch.dict(resilience.os.environ, {"V4_EBAY_ISOLATED_WORKER": "1"}),
            patch(
                "v4_ebay_hard_timeout_isolation.install_v4_ebay_hard_timeout_isolation"
            ) as hard_install,
        ):
            resilience.install_v4_external_provider_navigation_resilience()

        hard_install.assert_not_called()
        self.assertIs(watcher.scrape_ebay_sold, resilience.resilient_scrape_ebay_sold)


if __name__ == "__main__":
    unittest.main()
