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


class _MockResponse:
    def __init__(self, status=200):
        self.status = status


class _MockLocator:
    def __init__(self, count=0, text=""):
        self._count = count
        self._text = text
        self.first = self

    def count(self):
        return self._count

    def inner_text(self, timeout=None):
        return self._text

    def fill(self, query, timeout=None):
        pass

    def click(self, timeout=None):
        pass

    def wait_for(self, state=None, timeout=None):
        pass


class _MockPage:
    def __init__(
        self,
        status=200,
        title="",
        body="",
        input_count=0,
        submit_count=0,
    ):
        self.url = watcher.PSA_APR_SEARCH_URL
        self._status = status
        self._title = title
        self._body = body
        self._input_count = input_count
        self._submit_count = submit_count

    def goto(self, url, *args, **kwargs):
        self.url = url
        return _MockResponse(self._status)

    def title(self):
        return self._title

    def locator(self, selector):
        if selector == "body":
            return _MockLocator(count=1, text=self._body)
        if any(term in selector for term in ("input", "Search")):
            return _MockLocator(count=self._input_count)
        if any(term in selector for term in ("button", "submit", "role")):
            return _MockLocator(count=self._submit_count)
        return _MockLocator(count=0)

    def wait_for_timeout(self, ms):
        pass


class PsaAprDiagnosticClassificationTests(unittest.TestCase):
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
            body=(
                "Catégorie: Pokémon\nRéférence: #TG03/TG30\nAnnée: 2022\n"
                "Langue: Français\nSérie: Zenith Supreme\n"
                "Société de gradation: PSA\nNote: 8\n"
            ),
        )

    def test_http_403_classified_as_access_denied_transient(self):
        page = _MockPage(status=403, body="403 Forbidden")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "APR accès refusé (HTTP 403)")
        self.assertEqual(result.sales, [])

    def test_http_429_classified_as_rate_limited(self):
        page = _MockPage(status=429, body="Too Many Requests")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_RATE_LIMITED)
        self.assertEqual(result.note, "APR trop de requêtes (HTTP 429)")
        self.assertEqual(result.sales, [])

    def test_http_500_classified_as_provider_error(self):
        page = _MockPage(status=500, body="Internal Server Error")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.note, "APR erreur HTTP 500")
        self.assertEqual(result.sales, [])

    def test_cloudflare_challenge_body_detected_before_missing_form(self):
        page = _MockPage(
            status=200,
            title="Just a moment...",
            body="Checking your browser before accessing psacard.com. Cloudflare Turnstile",
            input_count=0,
        )
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "APR refusé ou anti-bot")
        self.assertEqual(result.sales, [])

    def test_perimeterx_challenge_title_detected_before_missing_form(self):
        page = _MockPage(
            status=200,
            title="Access Denied | PerimeterX",
            body="Please verify you are human to continue.",
            input_count=0,
        )
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "APR refusé ou anti-bot")
        self.assertEqual(result.sales, [])

    def test_challenge_with_too_many_requests_classified_as_rate_limited(self):
        page = _MockPage(
            status=200,
            title="Rate Limit Exceeded",
            body="Too many requests from your IP. Pardon our interruption.",
            input_count=0,
        )
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_RATE_LIMITED)
        self.assertEqual(result.note, "APR refusé ou anti-bot")
        self.assertEqual(result.sales, [])

    def test_genuine_missing_form_returns_formulaire_indisponible(self):
        page = _MockPage(
            status=200,
            title="PSA Auction Prices Realized",
            body="Welcome to PSA APR. Featured items...",
            input_count=0,
        )
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "formulaire APR indisponible")
        self.assertEqual(result.sales, [])

    def test_detail_page_http_403_classified_as_access_denied_transient(self):
        page = _MockDetailFlowPage(detail_status=403, detail_body="403 Forbidden")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "fiche APR accès refusé (HTTP 403)")
        self.assertEqual(result.sales, [])

    def test_detail_page_http_429_classified_as_rate_limited(self):
        page = _MockDetailFlowPage(detail_status=429, detail_body="Too Many Requests")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_RATE_LIMITED)
        self.assertEqual(result.note, "fiche APR trop de requêtes (HTTP 429)")
        self.assertEqual(result.sales, [])

    def test_detail_page_http_500_classified_as_provider_error(self):
        page = _MockDetailFlowPage(detail_status=500, detail_body="500 Internal Error")
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(result.note, "fiche APR erreur HTTP 500")
        self.assertEqual(result.sales, [])

    def test_detail_page_challenge_classified_as_transient(self):
        page = _MockDetailFlowPage(
            detail_status=200,
            detail_title="Just a moment...",
            detail_body="Cloudflare Turnstile Access Denied",
        )
        result = watcher.scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(
            result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        self.assertEqual(result.note, "fiche APR refusée ou anti-bot")
        self.assertEqual(result.sales, [])

    def test_resilient_scraper_logs_specific_diagnostic_notes(self):
        page = _MockPage(status=403, body="403 Forbidden")
        with patch.object(watcher, "log") as log:
            result = safe.resilient_scrape_psa_apr(page, self.lot(), usd_per_eur=1.1, now=NOW)
        self.assertEqual(result.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE)
        log.assert_any_call("APR disponibilité: APR accès refusé (HTTP 403)")


class _MockDetailLink:
    def __init__(self, href, text):
        self._href = href
        self._text = text

    def get_attribute(self, attr):
        if attr == "href":
            return self._href
        return None

    def inner_text(self, timeout=None):
        return self._text


class _MockDetailLinksLocator:
    def __init__(self, links):
        self._links = links

    def count(self):
        return len(self._links)

    def nth(self, index):
        return self._links[index]


class _MockDetailFlowPage:
    def __init__(
        self,
        detail_status=200,
        detail_title="",
        detail_body="",
    ):
        self.url = watcher.PSA_APR_SEARCH_URL
        self._detail_url = (
            "https://www.psacard.com/auctionprices/tcg-cards/2022-pokemon-zenith-supreme/dracaufeu/12345"
        )
        self._detail_status = detail_status
        self._detail_title = detail_title
        self._detail_body = detail_body
        self._matching_link = _MockDetailLink(
            "/auctionprices/tcg-cards/2022-pokemon-zenith-supreme/dracaufeu/12345",
            "2022 Pokemon Zenith Supreme #TG03/TG30 Dracaufeu French",
        )

    def goto(self, url, *args, **kwargs):
        self.url = url
        if url == self._detail_url:
            return _MockResponse(self._detail_status)
        return _MockResponse(200)

    def title(self):
        if self.url == self._detail_url:
            return self._detail_title
        return "PSA Auction Prices Realized"

    def locator(self, selector):
        if selector == "body":
            if self.url == self._detail_url:
                return _MockLocator(count=1, text=self._detail_body)
            return _MockLocator(count=1, text="Search results...")
        if any(term in selector for term in ("input", "Search")):
            return _MockLocator(count=1)
        if any(term in selector for term in ("button", "submit", "role")):
            return _MockLocator(count=1)
        if 'a[href*="/auctionprices/"]' in selector:
            return _MockDetailLinksLocator([self._matching_link])
        return _MockLocator(count=0)

    def wait_for_timeout(self, ms):
        pass


if __name__ == "__main__":
    unittest.main()
