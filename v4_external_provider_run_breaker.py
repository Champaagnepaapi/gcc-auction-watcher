"""Bound repeated public-provider failures inside one V4 scanner run.

This is scheduling/runtime protection only.  It does not change commercial
identity, matching, valuation, cacheability, or notification semantics.
Provider failures remain retryable and the breaker state is process-local, so a
new scanner run tries the public providers again normally.
"""
from __future__ import annotations

import os

import watcher


_INSTALLED = False
_ORIGINAL_SCRAPE_EBAY_SOLD = None
_ORIGINAL_SCRAPE_PSA_APR = None

_PSA_RUN_OPEN = False
_PSA_RUN_STATUS = watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
_PSA_RUN_REASON = ""
_EBAY_RUN_OPEN = False
_EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT = 0

_DEFAULT_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD = 2
_MIN_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD = 2
_MAX_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD = 8


def _ebay_hard_timeout_breaker_threshold() -> int:
    raw = os.getenv(
        "V4_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD",
        str(_DEFAULT_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD),
    ).strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = _DEFAULT_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD
    return max(
        _MIN_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD,
        min(_MAX_EBAY_HARD_TIMEOUT_BREAKER_THRESHOLD, value),
    )


def _psa_provider_wide_failure(data: watcher.PsaAprData) -> tuple[str, str] | None:
    note = str(getattr(data, "note", "") or "")
    lowered = note.lower()
    status = str(getattr(data, "provider_status", "") or "")

    # A public HTTP 403/429 is runner/provider-wide evidence, not card-specific
    # negative evidence. Repeating it for another identity in the same run only
    # wastes the scarce external-provider window. Never persist it as no-match.
    if "http 403" in lowered:
        return watcher.EXTERNAL_TRANSIENT_UNAVAILABLE, "HTTP 403"
    if "http 429" in lowered or status == watcher.EXTERNAL_RATE_LIMITED:
        return watcher.EXTERNAL_RATE_LIMITED, "HTTP 429/rate-limit"
    return None


def _guarded_scrape_psa_apr(page, *args, **kwargs):
    global _PSA_RUN_OPEN, _PSA_RUN_STATUS, _PSA_RUN_REASON

    if _PSA_RUN_OPEN:
        return watcher.PsaAprData(
            [],
            note=f"APR run circuit open after {_PSA_RUN_REASON}",
            provider_status=_PSA_RUN_STATUS,
        )

    data = _ORIGINAL_SCRAPE_PSA_APR(page, *args, **kwargs)
    failure = _psa_provider_wide_failure(data)
    if failure is not None:
        _PSA_RUN_STATUS, _PSA_RUN_REASON = failure
        _PSA_RUN_OPEN = True
        watcher.log(
            "PSA APR run circuit: provider-wide "
            f"{_PSA_RUN_REASON}; remaining APR network calls skipped this run"
        )
    return data


def _is_ebay_hard_timeout(result: watcher.ExternalScrapeResult) -> bool:
    return (
        result.status == watcher.EXTERNAL_PROVIDER_ERROR
        and "hard timeout" in str(result.note or "").lower()
    )


def _is_ebay_usable_result(result: watcher.ExternalScrapeResult) -> bool:
    return result.status in watcher.EXTERNAL_CACHEABLE_STATUSES


def _guarded_scrape_ebay_sold(
    page, lot: watcher.Lot, *, with_status: bool = False
):
    global _EBAY_RUN_OPEN, _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT

    if _EBAY_RUN_OPEN:
        result = watcher.ExternalScrapeResult(
            [],
            watcher.EXTERNAL_PROVIDER_ERROR,
            "eBay run circuit open after repeated hard timeouts",
        )
        return result if with_status else result.sales

    # The already-installed hard-timeout isolation exposes structured status.
    # Force status internally so the breaker can distinguish a true hard hang
    # from a clean no-match; preserve the caller's historical return shape.
    result = _ORIGINAL_SCRAPE_EBAY_SOLD(page, lot, with_status=True)

    if _is_ebay_hard_timeout(result):
        _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT += 1
        threshold = _ebay_hard_timeout_breaker_threshold()
        if _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT >= threshold:
            _EBAY_RUN_OPEN = True
            watcher.log(
                "eBay run circuit: "
                f"{_EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT} hard timeouts without "
                "a usable provider result; remaining eBay network calls skipped this run"
            )
    elif _is_ebay_usable_result(result):
        # A real provider response proves the route recovered; only then reset
        # accumulated hard hangs. Other provider errors do not fabricate health.
        _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT = 0

    return result if with_status else result.sales


def reset_v4_external_provider_run_breakers_for_tests() -> None:
    """Reset process-local state; production gets a fresh process every run."""
    global _PSA_RUN_OPEN, _PSA_RUN_STATUS, _PSA_RUN_REASON
    global _EBAY_RUN_OPEN, _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT
    _PSA_RUN_OPEN = False
    _PSA_RUN_STATUS = watcher.EXTERNAL_TRANSIENT_UNAVAILABLE
    _PSA_RUN_REASON = ""
    _EBAY_RUN_OPEN = False
    _EBAY_HARD_TIMEOUTS_WITHOUT_USABLE_RESULT = 0


def install_v4_external_provider_run_breakers() -> None:
    """Wrap final PSA/eBay scrapers with process-local failure breakers."""
    global _INSTALLED, _ORIGINAL_SCRAPE_EBAY_SOLD, _ORIGINAL_SCRAPE_PSA_APR
    if _INSTALLED:
        return

    _ORIGINAL_SCRAPE_EBAY_SOLD = watcher.scrape_ebay_sold
    _ORIGINAL_SCRAPE_PSA_APR = watcher.scrape_psa_apr
    watcher.scrape_ebay_sold = _guarded_scrape_ebay_sold
    watcher.scrape_psa_apr = _guarded_scrape_psa_apr
    _INSTALLED = True

    watcher.log(
        "External provider run breakers enabled: PSA HTTP 403/429 => stop APR network "
        "for this run; eBay hard-timeout threshold "
        f"{_ebay_hard_timeout_breaker_threshold()}; failures remain retryable next run"
    )
