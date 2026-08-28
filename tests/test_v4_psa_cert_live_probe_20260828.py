from __future__ import annotations

import os
import unittest


@unittest.skipUnless(
    os.getenv("GITHUB_ACTIONS", "").strip().lower() == "true",
    "one-shot GitHub Actions reachability probe",
)
class V4PsaCertLiveProbe20260828(unittest.TestCase):
    def test_public_psa_cert_page_is_reachable_from_runner(self):
        from playwright.sync_api import sync_playwright

        cert = "143398067"
        url = f"https://www.psacard.com/cert/{cert}/psa"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
                status = response.status if response is not None else 0
                body = page.locator("body").inner_text(timeout=5000)
            finally:
                browser.close()

        print(
            "PSA cert reachability: "
            f"status={status} cert_visible={cert in body} "
            f"item_grade_visible={'Item Grade' in body} "
            f"similar_sales_visible={'Sales of Similar Items' in body}"
        )
        self.assertEqual(status, 200)
        self.assertIn(cert, body)
        self.assertIn("Item Grade", body)


if __name__ == "__main__":
    unittest.main()
