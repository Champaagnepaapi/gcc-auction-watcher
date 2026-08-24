from __future__ import annotations

import os
from urllib.parse import urlparse

import watcher


_EBAY_ITEM_SELECTOR = "li.s-item"
_PSA_SEARCH_SELECTOR = (
    "input[placeholder*='Search PSA-Graded Items'], "
    "input[placeholder*='Search PSA Graded Items'], "
    "input[type='search']"
)
_CHALLENGE_MARKERS = (
    "pardon our interruption",
    "captcha",
    "verify you are human",
    "access denied",
    "forbidden",
    "perimeterx",
    "cloudflare",
    "datadome",
)

_INSTALLED = False
_ORIGINAL_SCRAPE_EBAY_SOLD = None
_ORIGINAL_SCRAPE_PSA_APR = None


def _hostname(value: str) -> str:
    try:
        return (urlparse(value).hostname or "").lower().strip(".")
    except Exception:
        return ""


def _same_target_host(current_url: str, target_url: str) -> bool:
    current = _hostname(current_url)
    target = _hostname(target_url)
    return bool(current and target and current == target)


def _safe_locator_count(page, selector: str) -> int:
    try:
        return int(page.locator(selector).count())
    except Exception:
        return 0


def _safe_body_text(page) -> str:
    try:
        return str(page.locator("body").inner_text(timeout=700) or "")
    except Exception:
        return ""


def _has_challenge_marker(page) -> bool:
    body = _safe_body_text(page).lower()
    return any(marker in body for marker in _CHALLENGE_MARKERS)


class NavigationTimeoutSalvageProxy:
    """Continue after a Playwright navigation timeout only when usable DOM is proven.

    This wrapper never retries the network request. It only lets the existing
    provider scraper inspect a page that demonstrably reached the expected host
    and already contains either structured provider content or an explicit
    challenge page that the existing scraper can classify fail-closed.
    """

    def __init__(self, page, provider: str):
        self._page = page
        self._provider = provider

    def __getattr__(self, name):
        return getattr(self._page, name)

    def _usable_after_timeout(self, target_url: str) -> bool:
        current_url = str(getattr(self._page, "url", "") or "")
        if not _same_target_host(current_url, target_url):
            return False

        if self._provider == "ebay":
            return _safe_locator_count(self._page, _EBAY_ITEM_SELECTOR) > 0 or _has_challenge_marker(
                self._page
            )
        if self._provider == "psa_apr":
            return _safe_locator_count(self._page, _PSA_SEARCH_SELECTOR) > 0 or _has_challenge_marker(
                self._page
            )
        return False

    def goto(self, url, *args, **kwargs):
        try:
            return self._page.goto(url, *args, **kwargs)
        except Exception as exc:
            if exc.__class__.__name__ != "TimeoutError":
                raise
            if not self._usable_after_timeout(str(url)):
                raise
            provider_label = "eBay" if self._provider == "ebay" else "PSA APR"
            watcher.log(
                f"{provider_label}: navigation timeout mais DOM provider exploitable; "
                "poursuite sans nouvelle requête"
            )
            return None


def resilient_scrape_ebay_sold(page, *args, **kwargs):
    if _ORIGINAL_SCRAPE_EBAY_SOLD is None:
        raise RuntimeError("V4 eBay navigation resilience is not installed")
    return _ORIGINAL_SCRAPE_EBAY_SOLD(
        NavigationTimeoutSalvageProxy(page, "ebay"), *args, **kwargs
    )


def resilient_scrape_psa_apr(page, *args, **kwargs):
    if _ORIGINAL_SCRAPE_PSA_APR is None:
        raise RuntimeError("V4 PSA APR navigation resilience is not installed")
    return _ORIGINAL_SCRAPE_PSA_APR(
        NavigationTimeoutSalvageProxy(page, "psa_apr"), *args, **kwargs
    )


def install_v4_external_provider_navigation_resilience() -> None:
    """Wrap current providers, then hard-isolate eBay in the production parent.

    The child eBay worker sets V4_EBAY_ISOLATED_WORKER=1 so it receives only
    this normal TimeoutError/usable-DOM salvage layer and cannot recursively
    spawn another worker.
    """
    global _INSTALLED, _ORIGINAL_SCRAPE_EBAY_SOLD, _ORIGINAL_SCRAPE_PSA_APR
    if _INSTALLED:
        return

    _ORIGINAL_SCRAPE_EBAY_SOLD = watcher.scrape_ebay_sold
    _ORIGINAL_SCRAPE_PSA_APR = watcher.scrape_psa_apr
    watcher.scrape_ebay_sold = resilient_scrape_ebay_sold
    watcher.scrape_psa_apr = resilient_scrape_psa_apr
    _INSTALLED = True

    if os.getenv("V4_EBAY_ISOLATED_WORKER", "0").strip() != "1":
        from v4_ebay_hard_timeout_isolation import (
            install_v4_ebay_hard_timeout_isolation,
        )

        install_v4_ebay_hard_timeout_isolation()
