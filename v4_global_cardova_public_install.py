"""Install sessionless public Cardova discovery into the Global marketplace lane."""
from __future__ import annotations

import os
from typing import Any

import v4_global_marketplace_notify as marketplace
from v4_cardova_public_inventory import capture_cardova_public_inventory
from v4_global_marketplace_discovery import cardova_inventory
from v4_global_marketplace_scan import ScanStatus


_INSTALLED = False
_ORIGINAL_SCAN: Any = None


def _env_pages() -> int:
    try:
        return max(1, min(30, int(os.getenv("GLOBAL_CARDOVA_PUBLIC_PAGES", "12"))))
    except ValueError:
        return 12


def _scan_with_public_cardova(args, *, observed_at):
    listings, statuses, gcc_fair, catalog_status = _ORIGINAL_SCAN(args, observed_at=observed_at)

    # Explicit sanitized files remain a supported deterministic override for
    # diagnostics/replay.  Public browsing is only used when no such files are
    # supplied and browser sources are enabled.
    if getattr(args, "cardova_fixed_json", "") or getattr(args, "cardova_auction_json", ""):
        return listings, statuses, gcc_fair, catalog_status
    if getattr(args, "no_browser_sources", False):
        return listings, statuses, gcc_fair, catalog_status

    capture = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                locale="en-US",
                user_agent="Mozilla/5.0",
                # No storage_state/user_data_dir: this is intentionally a fresh,
                # anonymous context with no imported Cardova session/cookies.
            )
            page = context.new_page()
            capture = capture_cardova_public_inventory(page, max_pages_each=_env_pages())
            context.close()
            browser.close()
    except Exception as error:
        status = ScanStatus(
            "cardova",
            "ERROR",
            detail=f"public anonymous browser capture failed: {type(error).__name__}",
            complete=False,
        )
        statuses = [row for row in statuses if row.market != "cardova"] + [status]
        return listings, statuses, gcc_fair, catalog_status

    cardova_rows = cardova_inventory(
        fixed_payload=capture.fixed_payload,
        auction_payload=capture.auction_payload,
        observed_at=observed_at,
        buyer_fee_rate=0.0,
        # Official buyer premium varies by membership rank.  Anonymous public
        # discovery cannot prove the user's rate, so auction all-in stays unknown.
        auction_buyer_premium_rate=None,
        logistics_jpy=0.0,
    )
    merged = {listing.stable_key: listing for listing in listings}
    for listing in cardova_rows:
        merged[listing.stable_key] = listing

    detail = (
        "public anonymous GET-only browser capture; no login/session/cookies; "
        f"json={capture.json_responses}; raw={capture.raw_listing_rows}; "
        f"scope={capture.accepted_rows}; rejects={dict(capture.rejected_rows)}; "
        "fixed buyer fee=0 per public fee schedule; auction buyer premium unproven"
    )
    status = ScanStatus(
        "cardova",
        capture.status,
        pages=capture.pages_visited,
        candidates=capture.raw_listing_rows,
        exact=len(cardova_rows),
        detail=detail,
        # Intentionally false until exhaustive public pagination is proven.
        complete=False,
    )
    statuses = [row for row in statuses if row.market != "cardova"] + [status]
    return list(merged.values()), statuses, gcc_fair, catalog_status


def install_global_cardova_public_inventory() -> None:
    global _INSTALLED, _ORIGINAL_SCAN
    if _INSTALLED:
        return
    _ORIGINAL_SCAN = marketplace._scan
    marketplace._scan = _scan_with_public_cardova
    _INSTALLED = True
