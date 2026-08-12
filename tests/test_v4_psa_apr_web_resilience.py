import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import run_watcher_safe as safe
import watcher


NOW = datetime(2026, 8, 12, tzinfo=timezone.utc)


class _FakeLocator:
    def __init__(self, selector, calls, fail=False):
        self.selector = selector
        self.calls = calls
        self.fail = fail
        self.first = self

    def wait_for(self, *, state, timeout):
        self.calls.append((self.selector, state, timeout))
        if self.fail:
            raise TimeoutError("not hydrated")


class _FakePage:
    def __init__(self, *, fail_selector=""):
        self.url = "about:blank"
        self.goto_calls = []
        self.wait_calls = []
        self.fail_selector = fail_selector

    def goto(self, url, *args, **kwargs):
        self.url = url
        self.goto_calls.append((url, args, kwargs))
        return "goto-result"

    def locator(self, selector):
        return _FakeLocator(
            selector,
            self.wait_calls,
            fail=selector == self.fail_selector,
        )


class PsaAprWebHydrationResilienceTests(unittest.TestCase):
    def lot(self):
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/test",
            title="Dracaufeu",
            current_price=45,
            source_type="fixed",
            grader="PSA",
            grade="8",
            card_number="TG03/TG30",
            year=2022,
            language="French",
        )

    def test_apr_navigation_waits_for_search_and_submit_controls(self):
        page = _FakePage()
        proxy = safe.AprHydrationPageProxy(page)

        result = proxy.goto(
            watcher.PSA_APR_SEARCH_URL,
            wait_until="domcontentloaded",
            timeout=watcher.PSA_APR_NAV_TIMEOUT,
        )

        self.assertEqual(result, "goto-result")
        self.assertEqual(len(page.goto_calls), 1)
        self.assertEqual(
            page.wait_calls,
            [
                (
                    safe.PSA_APR_SEARCH_SELECTOR,
                    "visible",
                    min(
                        safe.PSA_APR_SEARCH_HYDRATION_WAIT_MS,
                        watcher.PSA_APR_NAV_TIMEOUT,
                    ),
                ),
                (
                    safe.PSA_APR_SUBMIT_SELECTOR,
                    "visible",
                    min(
                        safe.PSA_APR_SUBMIT_HYDRATION_WAIT_MS,
                        watcher.PSA_APR_NAV_TIMEOUT,
                    ),
                ),
            ],
        )

    def test_non_apr_navigation_does_not_add_hydration_wait(self):
        page = _FakePage()
        proxy = safe.AprHydrationPageProxy(page)

        proxy.goto("https://www.psacard.com/auctionprices/example/123")

        self.assertEqual(page.wait_calls, [])

    def test_hydration_timeout_is_fail_closed_by_original_scraper_not_proxy(self):
        page = _FakePage(fail_selector=safe.PSA_APR_SEARCH_SELECTOR)
        proxy = safe.AprHydrationPageProxy(page)

        result = proxy.goto(watcher.PSA_APR_SEARCH_URL)

        self.assertEqual(result, "goto-result")
        self.assertEqual(len(page.wait_calls), 2)

    def test_resilient_scraper_delegates_without_changing_result(self):
        page = _FakePage()
        expected = watcher.PsaAprData(
            [],
            note="aucun match",
            provider_status=watcher.EXTERNAL_CLEAN_NO_MATCH,
        )
        with patch.object(
            safe, "_ORIGINAL_SCRAPE_PSA_APR", return_value=expected
        ) as original, patch.object(watcher, "log") as log:
            result = safe.resilient_scrape_psa_apr(
                page,
                self.lot(),
                usd_per_eur=1.1,
                now=NOW,
            )

        self.assertIs(result, expected)
        delegated_page = original.call_args.args[0]
        self.assertIsInstance(delegated_page, safe.AprHydrationPageProxy)
        original.assert_called_once()
        log.assert_not_called()

    def test_transient_reason_is_logged_for_future_diagnosis(self):
        page = _FakePage()
        expected = watcher.PsaAprData(
            [],
            note="formulaire APR indisponible",
            provider_status=watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
        )
        with patch.object(
            safe, "_ORIGINAL_SCRAPE_PSA_APR", return_value=expected
        ), patch.object(watcher, "log") as log:
            result = safe.resilient_scrape_psa_apr(page, self.lot())

        self.assertIs(result, expected)
        log.assert_called_once_with(
            "APR disponibilité: formulaire APR indisponible"
        )

    def test_installer_wires_resilient_scraper_only_when_called(self):
        original = watcher.scrape_psa_apr
        try:
            safe.install_psa_apr_hydration_guard()
            self.assertIs(watcher.scrape_psa_apr, safe.resilient_scrape_psa_apr)
        finally:
            watcher.scrape_psa_apr = original


if __name__ == "__main__":
    unittest.main()
