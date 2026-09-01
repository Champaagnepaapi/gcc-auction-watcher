"""Disposable child worker used by v4_ebay_hard_timeout_isolation."""
from __future__ import annotations

import contextlib
import json
import sys
from dataclasses import asdict

from playwright.sync_api import sync_playwright

import watcher
from v4_ebay_bulk_result_text import EbayBulkTextPageProxy
from v4_external_provider_navigation_resilience import (
    install_v4_external_provider_navigation_resilience,
)


def _sale_payload(sale: watcher.ComparableSale) -> dict:
    payload = asdict(sale)
    payload["sold_at"] = sale.sold_at.isoformat() if sale.sold_at is not None else None
    payload["proven_commercial_dimensions"] = list(sale.proven_commercial_dimensions)
    return payload


def _result_payload(result: watcher.ExternalScrapeResult) -> dict:
    return {
        "sales": [_sale_payload(sale) for sale in result.sales],
        "status": result.status,
        "note": result.note,
    }


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read())
        lot_payload = payload.get("lot") if isinstance(payload, dict) else None
        if not isinstance(lot_payload, dict):
            raise ValueError("missing lot")
        lot = watcher.Lot(**lot_payload)

        # Keep stdout machine-readable for the parent. Existing V4 diagnostic
        # logs remain available on child stderr but are never used as evidence.
        with contextlib.redirect_stdout(sys.stderr):
            install_v4_external_provider_navigation_resilience()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(locale="fr-FR")
                    page = EbayBulkTextPageProxy(context.new_page())
                    result = watcher.scrape_ebay_sold(page, lot, with_status=True)
                    context.close()
                finally:
                    browser.close()
        if not isinstance(result, watcher.ExternalScrapeResult):
            raise TypeError("unexpected eBay worker result")
        sys.stdout.write(json.dumps(_result_payload(result), ensure_ascii=False))
        return 0
    except Exception as exc:
        # Public technical class only; never echo payload/environment/secrets.
        sys.stderr.write(f"eBay isolated worker error: {type(exc).__name__}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
