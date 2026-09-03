"""Disposable child worker used by v4_ebay_hard_timeout_isolation."""
from __future__ import annotations

import contextlib
import json
import os
import sys
from dataclasses import asdict

from playwright.sync_api import sync_playwright

import watcher
from v4_ebay_bulk_result_text import EbayBulkTextPageProxy
from v4_ebay_stage_timing import EbayStageTelemetry, EbayStageTimingPageProxy
from v4_external_provider_navigation_resilience import (
    install_v4_external_provider_navigation_resilience,
)

_RESULT_FD_ENV = "V4_EBAY_RESULT_FD"


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


def _emit_early_result(encoded_result: str) -> bool:
    """Send a complete result to the parent before browser teardown when requested."""
    raw_fd = os.getenv(_RESULT_FD_ENV, "").strip()
    if not raw_fd:
        return False
    try:
        fd = int(raw_fd)
    except ValueError as exc:
        raise RuntimeError("invalid eBay result pipe") from exc
    if fd < 0:
        raise RuntimeError("invalid eBay result pipe")

    payload = (encoded_result + "\n").encode("utf-8")
    view = memoryview(payload)
    try:
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise RuntimeError("eBay result pipe write failed")
            view = view[written:]
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return True


def main() -> int:
    telemetry = EbayStageTelemetry()
    telemetry.mark("worker_start")
    result_json = None
    try:
        payload = json.loads(sys.stdin.read())
        lot_payload = payload.get("lot") if isinstance(payload, dict) else None
        if not isinstance(lot_payload, dict):
            raise ValueError("missing lot")
        lot = watcher.Lot(**lot_payload)

        # Keep stdout machine-readable for the parent. Existing V4 diagnostic
        # logs remain available on child stderr but are never used as evidence.
        # The parent parses only strict EBAY_STAGE markers and discards all
        # other stderr, so card/query/provider payloads never become telemetry.
        with contextlib.redirect_stdout(sys.stderr):
            with telemetry.span("resilience_install"):
                install_v4_external_provider_navigation_resilience()
            with telemetry.span("playwright"):
                with sync_playwright() as playwright:
                    with telemetry.span("browser_launch"):
                        browser = playwright.chromium.launch(headless=True)
                    try:
                        with telemetry.span("context_create"):
                            context = browser.new_context(locale="fr-FR")
                        with telemetry.span("page_create"):
                            raw_page = context.new_page()
                            timed_page = EbayStageTimingPageProxy(raw_page, telemetry)
                            # Layer bulk extraction above timing so the existing
                            # bulk proxy's all_inner_texts/fallback RPCs are timed
                            # without changing canonical scraper behavior.
                            page = EbayBulkTextPageProxy(timed_page)
                        with telemetry.span("scrape"):
                            result = watcher.scrape_ebay_sold(
                                page, lot, with_status=True
                            )
                        with telemetry.span("context_close"):
                            context.close()
                        if not isinstance(result, watcher.ExternalScrapeResult):
                            raise TypeError("unexpected eBay worker result")
                        result_json = json.dumps(
                            _result_payload(result), ensure_ascii=False
                        )
                        if _emit_early_result(result_json):
                            telemetry.mark("result_ready")
                    finally:
                        # The parent now treats this as bounded cleanup only.
                        # A valid result has already crossed the dedicated pipe;
                        # if Chromium teardown wedges, the parent kills this
                        # disposable process group after a short grace period.
                        with telemetry.span("browser_close"):
                            browser.close()
        if result_json is None:
            raise TypeError("unexpected eBay worker result")
        telemetry.mark("worker_done")
        # Preserve the historical stdout protocol for direct/manual callers.
        # Production isolation consumes the dedicated result pipe instead.
        sys.stdout.write(result_json)
        return 0
    except Exception as exc:
        telemetry.mark("worker_error")
        # Public technical class only; never echo payload/environment/secrets.
        sys.stderr.write(f"eBay isolated worker error: {type(exc).__name__}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
