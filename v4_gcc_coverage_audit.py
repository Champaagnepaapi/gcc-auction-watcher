"""Audit manuel V4 de discovery GCC, sans valuation ni notification économique."""

from pathlib import Path

from playwright.sync_api import sync_playwright

import watcher


def main() -> int:
    diagnostics = watcher.RunDiagnostics()
    watcher.log("=== V4 GCC Coverage Audit (diagnostic manuel) ===")
    watcher.log(
        f"Production fixed endpoint: {watcher.FIXED_PRICE_URL}"
    )
    watcher.log(
        f"Production fixed filters: [{'; '.join(watcher.FIXED_DISCOVERY_FILTERS)}]"
    )
    watcher.log(
        f"Production auction filters: [{'; '.join(watcher.AUCTION_DISCOVERY_FILTERS)}]"
    )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=watcher.HEADLESS)
        session_file = Path("gcc_session.json")
        context_options = {
            "locale": "fr-FR",
            "timezone_id": "Europe/Zurich",
        }
        if session_file.exists():
            context_options["storage_state"] = str(session_file)
        context = browser.new_context(**context_options)
        page = context.new_page()
        page.set_default_timeout(watcher.TEXT_TIMEOUT)
        page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)

        try:
            fixed_lots = watcher.collect_lots_from_listing(
                page,
                watcher.FIXED_PRICE_URL,
                "fixed",
                diagnostics,
            )
            for lot in fixed_lots:
                diagnostics.fixed_coverage.record_terminal(
                    lot.url, watcher.ACCOUNT_DIAGNOSTIC_ONLY
                )

            sales = watcher.collect_live_auction_urls(page, diagnostics)
            diagnostics.record_live_sales(sales)
            for sale_url in sales:
                lots = watcher.collect_lots_from_listing(
                    page,
                    sale_url,
                    "auction",
                    diagnostics,
                )
                for lot in lots:
                    diagnostics.auction_coverage.record_terminal(
                        lot.url, watcher.ACCOUNT_DIAGNOSTIC_ONLY
                    )
        finally:
            diagnostics.finalize_coverage()
            watcher.log_scan_coverage(diagnostics)
            browser.close()

    production_ids = (
        diagnostics.fixed_coverage.listing_ids
        | diagnostics.auction_coverage.listing_ids
    )
    comparison = watcher.compare_marketplace_inventory(production_ids, None)
    print("\n=== MARKETPLACE GCC REFERENCE ===", flush=True)
    print(comparison.reason, flush=True)
    print(f"production unique listings: {comparison.production_unique}", flush=True)
    print("reference unique listings: UNKNOWN", flush=True)
    print("outside production universe: UNKNOWN", flush=True)
    print(
        "reason: GCC expose des vues client filtrées avec défilement infini, "
        "mais aucun endpoint documenté et stable d'inventaire complet n'est "
        "utilisé par V4; aucune référence all-GCC n'est inventée.",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
