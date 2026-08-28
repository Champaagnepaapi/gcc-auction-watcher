from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_psa_cert_sales_bridge as bridge


class _Response:
    def __init__(self, status):
        self.status = status


class _Locator:
    def __init__(self, body):
        self.body = body

    def inner_text(self, **_kwargs):
        return self.body


class _Page:
    def __init__(self, body="", status=200):
        self.body = body
        self.status = status
        self.urls = []

    def goto(self, url, **_kwargs):
        self.urls.append(url)
        return _Response(self.status)

    def wait_for_timeout(self, _ms):
        return None

    def locator(self, selector):
        self.last_selector = selector
        return _Locator(self.body)


def _lot(**overrides):
    values = dict(
        url="https://gradedcardcenter.com/item/test",
        title="Bulbasaur",
        current_price=50.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_set="Stellar Crown",
        card_number="143/142",
        language="English",
        year=2024,
        body="",
        listing_text="",
    )
    values.update(overrides)
    return watcher.Lot(**values)


class V4PsaCertSalesBridgeTests(unittest.TestCase):
    def tearDown(self):
        bridge.reset_v4_psa_cert_sales_bridge_for_tests()

    def test_fixed_gcc_serial_number_is_attached_only_for_psa(self):
        psa = _lot()
        non_psa = _lot(grader="CGC")
        original = bridge._ORIGINAL_FIXED_RESULT_TO_LOT
        try:
            bridge._ORIGINAL_FIXED_RESULT_TO_LOT = lambda *_a, **_k: psa
            result = {"item": {"serialNumber": "143398067"}}
            out = bridge._attach_fixed_gcc_psa_cert(result, psa.url, object())
            self.assertIs(out, psa)
            self.assertEqual(out._v4_psa_cert_number, "143398067")

            bridge._ORIGINAL_FIXED_RESULT_TO_LOT = lambda *_a, **_k: non_psa
            out = bridge._attach_fixed_gcc_psa_cert(result, non_psa.url, object())
            self.assertFalse(hasattr(out, "_v4_psa_cert_number"))
        finally:
            bridge._ORIGINAL_FIXED_RESULT_TO_LOT = original

    def test_cert_extraction_requires_structured_or_labeled_value(self):
        lot = _lot(body="Reference: 143/142\nCertification Number: 143398067")
        self.assertEqual(bridge._cert_number_from_lot(lot), "143398067")
        self.assertEqual(
            bridge._cert_number_from_lot(
                _lot(body="Reference: 143/142\nPopulation 143398067")
            ),
            "",
        )

    def test_cert_page_exact_sales_are_same_grade_and_provenance(self):
        lot = _lot()
        body = (
            "Certification Number 143398067\n"
            "2024 POKEMON STELLAR CROWN BULBASAUR 143\n"
            "Item Grade 10\n"
            "PSA Population 1,234\n"
            "PSA Pop Higher 0\n"
            "Sales of Similar Items\n"
            "PSA 10\n08/25/26\neBay\nAuction\n987654321\n$345.00\n"
        )
        sale10 = watcher.ComparableSale(
            345.0,
            source="psa",
            grader="PSA",
            grade=10.0,
            sold_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        )
        sale9 = watcher.ComparableSale(
            200.0,
            source="psa",
            grader="PSA",
            grade=9.0,
            sold_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        )
        with (
            patch.object(watcher, "_target_grade", return_value=10.0),
            patch.object(watcher, "psa_apr_match_score", return_value=(100, "exact")),
            patch.object(watcher, "parse_psa_apr_sales", return_value=[sale10, sale9]),
            patch.object(
                watcher,
                "attach_psa_spec_provenance",
                side_effect=lambda data, _body, _lot: data,
            ),
        ):
            data = bridge._cert_page_result(
                lot, "143398067", body, usd_per_eur=1.0
            )
        self.assertEqual(data.provider_status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(len(data.sales), 1)
        self.assertEqual(data.sales[0].grade, 10.0)
        self.assertIn("PSA cert 143398067", data.sales[0].context)
        self.assertEqual(data.population, 1234)
        self.assertEqual(data.pop_higher, 0)
        self.assertEqual(data.most_recent_price, 345.0)

    def test_psa_estimate_never_becomes_a_sale(self):
        body = (
            "Certification Number 143398067\n"
            "Item Grade 10\n"
            "PSA Estimate $999.00\n"
        )
        self.assertEqual(bridge._cert_sale_rows(body), [])
        with (
            patch.object(watcher, "_target_grade", return_value=10.0),
            patch.object(watcher, "psa_apr_match_score", return_value=(100, "exact")),
            patch.object(watcher, "parse_psa_apr_sales", return_value=[]),
            patch.object(
                watcher,
                "attach_psa_spec_provenance",
                side_effect=lambda data, _body, _lot: data,
            ),
        ):
            data = bridge._cert_page_result(
                _lot(), "143398067", body, usd_per_eur=1.0
            )
        self.assertEqual(data.provider_status, watcher.EXTERNAL_CLEAN_NO_MATCH)
        self.assertEqual(data.sales, [])
        self.assertIsNone(data.most_recent_price)

    def test_cert_identity_or_grade_conflict_fails_closed(self):
        with patch.object(watcher, "_target_grade", return_value=10.0):
            missing_cert = bridge._cert_page_result(
                _lot(), "143398067", "Item Grade 10", usd_per_eur=1.0
            )
            wrong_grade = bridge._cert_page_result(
                _lot(),
                "143398067",
                "Certification Number 143398067\nItem Grade 9",
                usd_per_eur=1.0,
            )
        self.assertEqual(missing_cert.provider_status, watcher.EXTERNAL_PROVIDER_ERROR)
        self.assertEqual(wrong_grade.provider_status, watcher.EXTERNAL_PROVIDER_ERROR)

    def test_http_403_and_429_remain_retryable_provider_failures(self):
        lot = _lot()
        setattr(lot, "_v4_psa_cert_number", "143398067")
        with (
            patch.object(watcher, "_target_grade", return_value=10.0),
            patch.object(watcher, "psa_apr_identity_is_sufficient", return_value=True),
        ):
            denied = bridge._cert_first_scrape_psa_apr(
                _Page(status=403), lot, usd_per_eur=1.0
            )
        with (
            patch.object(watcher, "_target_grade", return_value=10.0),
            patch.object(watcher, "psa_apr_identity_is_sufficient", return_value=True),
        ):
            limited = bridge._cert_first_scrape_psa_apr(
                _Page(status=429), lot, usd_per_eur=1.0
            )
        self.assertEqual(denied.provider_status, watcher.EXTERNAL_TRANSIENT_UNAVAILABLE)
        self.assertIn("HTTP 403", denied.note)
        self.assertEqual(limited.provider_status, watcher.EXTERNAL_RATE_LIMITED)
        self.assertIn("HTTP 429", limited.note)

    def test_no_cert_delegates_to_existing_apr(self):
        sentinel = watcher.PsaAprData(
            [], note="legacy APR", provider_status=watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
        )
        original = bridge._ORIGINAL_SCRAPE_PSA_APR
        try:
            bridge._ORIGINAL_SCRAPE_PSA_APR = lambda *_a, **_k: sentinel
            self.assertIs(
                bridge._cert_first_scrape_psa_apr(_Page(), _lot()),
                sentinel,
            )
        finally:
            bridge._ORIGINAL_SCRAPE_PSA_APR = original

    def test_installer_wraps_fixed_converter_and_psa_scraper(self):
        original_fixed = watcher._gcc_fixed_result_to_lot
        original_psa = watcher.scrape_psa_apr
        bridge.install_v4_psa_cert_sales_bridge()
        self.assertIs(watcher._gcc_fixed_result_to_lot, bridge._attach_fixed_gcc_psa_cert)
        self.assertIs(watcher.scrape_psa_apr, bridge._cert_first_scrape_psa_apr)
        bridge.install_v4_psa_cert_sales_bridge()
        bridge.reset_v4_psa_cert_sales_bridge_for_tests()
        self.assertIs(watcher._gcc_fixed_result_to_lot, original_fixed)
        self.assertIs(watcher.scrape_psa_apr, original_psa)


if __name__ == "__main__":
    unittest.main()
