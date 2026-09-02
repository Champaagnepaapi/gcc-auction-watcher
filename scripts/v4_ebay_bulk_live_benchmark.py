"""Read-only live benchmark for the V4 eBay result-text extraction bottleneck.

This diagnostic never performs purchases, bids, offers, checkout, payment, login,
notifications, state writes, or valuation. It opens one public eBay SOLD search
page and compares the two text-extraction mechanisms against the same DOM:

1. one Playwright ``all_inner_texts()`` call (PR #233 path),
2. the historical ``nth(i).inner_text()`` browser-RPC loop.

The benchmark deliberately does not parse prices or infer SOLD evidence. Its only
purpose is to measure the browser-IPC cost addressed by PR #233 and prove that
both extraction paths return the same visible text for the observed rows.
"""
from __future__ import annotations

import json
import time
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright


MAX_ROWS = 120
NAV_TIMEOUT_MS = 10_000
PAGE_WAIT_MS = 700
QUERY = "pokemon psa 10"


def main() -> int:
    params = {
        "_nkw": QUERY,
        "LH_Complete": "1",
        "LH_Sold": "1",
    }
    url = "https://www.ebay.fr/sch/i.html?" + urlencode(params)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(locale="fr-FR")
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
                page.wait_for_timeout(PAGE_WAIT_MS)
                cards = page.locator("li.s-item")
                observed = min(cards.count(), MAX_ROWS)
                if observed <= 0:
                    print(json.dumps({"status": "INCONCLUSIVE", "reason": "NO_VISIBLE_RESULT_ROWS"}))
                    return 2

                bulk_started = time.perf_counter()
                all_bulk = cards.all_inner_texts()
                bulk_seconds = time.perf_counter() - bulk_started
                bulk = ["" if value is None else str(value) for value in all_bulk[:observed]]

                per_item_started = time.perf_counter()
                per_item = [cards.nth(i).inner_text(timeout=600) for i in range(observed)]
                per_item_seconds = time.perf_counter() - per_item_started

                equivalent = bulk == per_item
                speedup = (per_item_seconds / bulk_seconds) if bulk_seconds > 0 else None
                payload = {
                    "status": "PASS" if equivalent else "FAIL",
                    "query": QUERY,
                    "observed_rows": observed,
                    "bulk_seconds": round(bulk_seconds, 4),
                    "per_item_seconds": round(per_item_seconds, 4),
                    "speedup_x": round(speedup, 2) if speedup is not None else None,
                    "per_item_exceeds_v4_hard_timeout_30s": per_item_seconds >= 30.0,
                    "text_equivalent": equivalent,
                }
                print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
                return 0 if equivalent else 1
            finally:
                context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
