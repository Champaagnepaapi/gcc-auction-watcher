import unittest
from unittest.mock import Mock, patch

import v4_external_provider_run_breaker as breaker
import watcher


class ExternalProviderRunBreakerTests(unittest.TestCase):
    def setUp(self):
        self.original_ebay = watcher.scrape_ebay_sold
        self.original_psa = watcher.scrape_psa_apr
        self.installed = breaker._INSTALLED
        self.delegate_ebay = breaker._ORIGINAL_SCRAPE_EBAY_SOLD
        self.delegate_psa = breaker._ORIGINAL_SCRAPE_PSA_APR
        breaker.reset_v4_external_provider_run_breakers_for_tests()

    def tearDown(self):
        watcher.scrape_ebay_sold = self.original_ebay
        watcher.scrape_psa_apr = self.original_psa
        breaker._INSTALLED = self.installed
        breaker._ORIGINAL_SCRAPE_EBAY_SOLD = self.delegate_ebay
        breaker._ORIGINAL_SCRAPE_PSA_APR = self.delegate_psa
        breaker.reset_v4_external_provider_run_breakers_for_tests()

    def _lot(self):
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/public",
            title="PSA 10 Pikachu",
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="151",
            card_number="#025/165",
            language="English",
        )

    def test_psa_http_403_opens_run_circuit_and_second_call_skips_network(self):
        delegate = Mock(
            return_value=watcher.PsaAprData(
                [],
                note="APR accès refusé (HTTP 403)",
                provider_status=watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            )
        )
        breaker._ORIGINAL_SCRAPE_PSA_APR = delegate

        first = breaker._guarded_scrape_psa_apr(Mock(), self._lot())
        second = breaker._guarded_scrape_psa_apr(Mock(), self._lot())

        self.assertEqual(delegate.call_count, 1)
        self.assertEqual(first.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE)
        self.assertEqual(second.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE)
        self.assertIn("circuit open", second.note.lower())
        self.assertTrue(breaker._PSA_RUN_OPEN)

    def test_psa_rate_limit_opens_run_circuit_without_becoming_no_match(self):
        delegate = Mock(
            return_value=watcher.PsaAprData(
                [],
                note="APR trop de requêtes (HTTP 429)",
                provider_status=watcher.EXTERNAL_RATE_LIMITED,
            )
        )
        breaker._ORIGINAL_SCRAPE_PSA_APR = delegate

        breaker._guarded_scrape_psa_apr(Mock(), self._lot())
        skipped = breaker._guarded_scrape_psa_apr(Mock(), self._lot())

        self.assertEqual(delegate.call_count, 1)
        self.assertEqual(skipped.provider_status, watcher.EXTERNAL_RATE_LIMITED)
        self.assertNotEqual(skipped.provider_status, watcher.EXTERNAL_CLEAN_NO_MATCH)

    def test_psa_clean_result_does_not_open_circuit(self):
        delegate = Mock(
            return_value=watcher.PsaAprData(
                [],
                note="aucun candidat exact",
                provider_status=watcher.EXTERNAL_CLEAN_NO_MATCH,
            )
        )
        breaker._ORIGINAL_SCRAPE_PSA_APR = delegate

        breaker._guarded_scrape_psa_apr(Mock(), self._lot())
        breaker._guarded_scrape_psa_apr(Mock(), self._lot())

        self.assertEqual(delegate.call_count, 2)
        self.assertFalse(breaker._PSA_RUN_OPEN)

    def test_two_ebay_hard_timeouts_open_circuit_and_third_call_skips_worker(self):
        hard = watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay hard timeout after 30s"
        )
        delegate = Mock(side_effect=[hard, hard])
        breaker._ORIGINAL_SCRAPE_EBAY_SOLD = delegate

        with patch.dict(
            breaker.os.environ,
            {"V4_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD": "2"},
            clear=False,
        ):
            first = breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)
            second = breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)
            third = breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)

        self.assertEqual(delegate.call_count, 2)
        self.assertEqual(first.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(second.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(third.status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertIn("circuit open", third.note.lower())
        self.assertTrue(breaker._EBAY_RUN_OPEN)

    def test_usable_ebay_response_resets_accumulated_hard_timeout(self):
        hard = watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay hard timeout after 30s"
        )
        clean = watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_CLEAN_NO_MATCH, "clean"
        )
        delegate = Mock(side_effect=[hard, clean, hard])
        breaker._ORIGINAL_SCRAPE_EBAY_SOLD = delegate

        with patch.dict(
            breaker.os.environ,
            {"V4_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD": "2"},
            clear=False,
        ):
            breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)
            breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)
            breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)

        self.assertEqual(delegate.call_count, 3)
        self.assertFalse(breaker._EBAY_RUN_OPEN)
        self.assertEqual(breaker._EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT, 1)

    def test_non_hard_ebay_provider_error_does_not_trip_breaker(self):
        error = watcher.ExternalScrapeResult(
            [], watcher.EXTERNAL_PROVIDER_ERROR, "eBay navigation timeout"
        )
        delegate = Mock(return_value=error)
        breaker._ORIGINAL_SCRAPE_EBAY_SOLD = delegate

        for _ in range(4):
            breaker._guarded_scrape_ebay_sold(Mock(), self._lot(), with_status=True)

        self.assertEqual(delegate.call_count, 4)
        self.assertFalse(breaker._EBAY_RUN_OPEN)

    def test_installer_wraps_final_provider_functions_only(self):
        ebay = Mock()
        psa = Mock()
        watcher.scrape_ebay_sold = ebay
        watcher.scrape_psa_apr = psa
        breaker._INSTALLED = False
        breaker._ORIGINAL_SCRAPE_EBAY_SOLD = None
        breaker._ORIGINAL_SCRAPE_PSA_APR = None

        with patch.object(watcher, "log"):
            breaker.install_v4_external_provider_run_breakers()

        self.assertIs(breaker._ORIGINAL_SCRAPE_EBAY_SOLD, ebay)
        self.assertIs(breaker._ORIGINAL_SCRAPE_PSA_APR, psa)
        self.assertIs(watcher.scrape_ebay_sold, breaker._guarded_scrape_ebay_sold)
        self.assertIs(watcher.scrape_psa_apr, breaker._guarded_scrape_psa_apr)


if __name__ == "__main__":
    unittest.main()
