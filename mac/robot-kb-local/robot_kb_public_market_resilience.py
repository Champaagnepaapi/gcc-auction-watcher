from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterable


FAIL_VISIBLE_STATUSES = frozenset(
    {
        "ERROR",
        "RETRYABLE_EMPTY",
        "NO_PUBLIC_JSON",
        "NO_PUBLIC_LISTING_ROWS",
    }
)

_INSTALLED = False
_RUNTIME_INSTALLED = False
_ORIGINAL_INSTALL_SCAN_STACK: Callable[..., Any] | None = None
_ORIGINAL_HARVEST_MARKETS: Callable[..., Any] | None = None
_ORIGINAL_FANATICS_SCAN: Callable[..., Any] | None = None
_ORIGINAL_COMC_SCAN: Callable[..., Any] | None = None
_ORIGINAL_CARDOVA_CAPTURE: Callable[..., Any] | None = None


def _bounded_detail(value: object, *, limit: int = 360) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(0, int(limit))]


def _pause(page: Any, milliseconds: int = 1600) -> None:
    try:
        page.wait_for_timeout(max(0, int(milliseconds)))
    except Exception:
        # A failed readiness wait must not manufacture coverage. The retry still
        # runs and remains fail-visible if the source is empty again.
        pass


def _retry_empty_scan(
    original: Callable[..., tuple[list[Any], Any]],
    page: Any,
    *args: Any,
    market: str,
    **kwargs: Any,
) -> tuple[list[Any], Any]:
    rows, status = original(page, *args, **kwargs)
    if str(getattr(status, "status", "")) != "OK" or int(getattr(status, "candidates", 0) or 0) > 0:
        return rows, status

    _pause(page)
    retry_rows, retry_status = original(page, *args, **kwargs)
    if str(getattr(retry_status, "status", "")) == "OK" and int(getattr(retry_status, "candidates", 0) or 0) > 0:
        detail = _bounded_detail(getattr(retry_status, "detail", ""))
        return retry_rows, replace(
            retry_status,
            detail=f"{detail}; Robot KB local hydration retry recovered source".strip("; "),
        )

    detail = _bounded_detail(getattr(retry_status, "detail", "") or getattr(status, "detail", ""))
    return retry_rows, replace(
        retry_status,
        status="RETRYABLE_EMPTY",
        complete=False,
        detail=(
            f"{detail}; Robot KB local observed zero {market} source candidates after 2 bounded attempts"
        ).strip("; "),
    )


def fanatics_scan_with_retry(
    original: Callable[..., tuple[list[Any], Any]],
    page: Any,
    *args: Any,
    **kwargs: Any,
) -> tuple[list[Any], Any]:
    return _retry_empty_scan(original, page, *args, market="Fanatics", **kwargs)


def comc_scan_with_retry(
    original: Callable[..., tuple[list[Any], Any]],
    page: Any,
    *args: Any,
    **kwargs: Any,
) -> tuple[list[Any], Any]:
    return _retry_empty_scan(original, page, *args, market="COMC", **kwargs)


def _capture_quality(capture: Any) -> tuple[int, int, int]:
    return (
        int(getattr(capture, "json_responses", 0) or 0),
        int(getattr(capture, "raw_listing_rows", 0) or 0),
        int(getattr(capture, "accepted_rows", 0) or 0),
    )


def cardova_capture_with_retry(
    original: Callable[..., Any],
    page: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    first = original(page, *args, **kwargs)
    first_json, first_raw, _first_accepted = _capture_quality(first)
    if first_json > 0 and first_raw > 0:
        return first

    _pause(page)
    retry_kwargs = dict(kwargs)
    retry_kwargs["settle_ms"] = max(1500, int(retry_kwargs.get("settle_ms", 900) or 900))
    second = original(page, *args, **retry_kwargs)
    chosen = max((first, second), key=_capture_quality)
    json_responses, raw_rows, _accepted = _capture_quality(chosen)
    if json_responses <= 0:
        return replace(chosen, status="NO_PUBLIC_JSON", complete=False)
    if raw_rows <= 0:
        return replace(chosen, status="NO_PUBLIC_LISTING_ROWS", complete=False)
    return chosen


def scan_status_detail_notes(statuses: Iterable[Any]) -> list[str]:
    notes: list[str] = []
    for row in statuses:
        detail = _bounded_detail(getattr(row, "detail", ""))
        if not detail:
            continue
        notes.append(
            "market-detail:"
            f"{str(getattr(row, 'market', '')).casefold()}:"
            f"{getattr(row, 'status', '')}:"
            f"exact={int(getattr(row, 'exact', 0) or 0)}:"
            f"candidates={int(getattr(row, 'candidates', 0) or 0)}:"
            f"complete={bool(getattr(row, 'complete', False))}:"
            f"{detail}"
        )
    return notes


def count_fail_visible_statuses(statuses: Iterable[Any]) -> int:
    return sum(
        1
        for row in statuses
        if str(getattr(row, "status", "")).upper() in FAIL_VISIBLE_STATUSES
    )


def _install_runtime() -> None:
    global _RUNTIME_INSTALLED
    global _ORIGINAL_FANATICS_SCAN, _ORIGINAL_COMC_SCAN, _ORIGINAL_CARDOVA_CAPTURE
    if _RUNTIME_INSTALLED:
        return

    import v4_global_cardova_public_install as cardova_install
    import v4_global_marketplace_notify as marketplace

    _ORIGINAL_FANATICS_SCAN = marketplace.scan_fanatics_inventory
    _ORIGINAL_COMC_SCAN = marketplace.scan_comc_inventory
    _ORIGINAL_CARDOVA_CAPTURE = cardova_install.capture_cardova_public_inventory

    def fanatics(page: Any, *args: Any, **kwargs: Any):
        assert _ORIGINAL_FANATICS_SCAN is not None
        return fanatics_scan_with_retry(_ORIGINAL_FANATICS_SCAN, page, *args, **kwargs)

    def comc(page: Any, *args: Any, **kwargs: Any):
        assert _ORIGINAL_COMC_SCAN is not None
        return comc_scan_with_retry(_ORIGINAL_COMC_SCAN, page, *args, **kwargs)

    def cardova(page: Any, *args: Any, **kwargs: Any):
        assert _ORIGINAL_CARDOVA_CAPTURE is not None
        return cardova_capture_with_retry(_ORIGINAL_CARDOVA_CAPTURE, page, *args, **kwargs)

    marketplace.scan_fanatics_inventory = fanatics
    marketplace.scan_comc_inventory = comc
    cardova_install.capture_cardova_public_inventory = cardova
    _RUNTIME_INSTALLED = True


def install(harvest: Any) -> None:
    """Install Robot-KB-only public retrieval resilience.

    The shared V4 scanner/identity code is not modified on ``main``. This local
    adapter is activated only by the Robot KB entrypoint, after the normal V4
    marketplace stack has installed its wrappers.
    """

    global _INSTALLED, _ORIGINAL_INSTALL_SCAN_STACK, _ORIGINAL_HARVEST_MARKETS
    if _INSTALLED:
        return

    _ORIGINAL_INSTALL_SCAN_STACK = harvest.install_scan_stack
    _ORIGINAL_HARVEST_MARKETS = harvest.harvest_markets

    def install_scan_stack_resilient() -> None:
        assert _ORIGINAL_INSTALL_SCAN_STACK is not None
        _ORIGINAL_INSTALL_SCAN_STACK()
        _install_runtime()

    def harvest_markets_resilient(kb: Any, state: dict[str, Any], diag: Any) -> None:
        import v4_global_marketplace_notify as marketplace

        assert _ORIGINAL_HARVEST_MARKETS is not None
        # Install every shared V4 wrapper before observing the final _scan
        # callable. The original harvester calls this again idempotently.
        install_scan_stack_resilient()
        original_scan = marketplace._scan
        captured: dict[str, Any] = {}

        def observed_scan(*args: Any, **kwargs: Any):
            result = original_scan(*args, **kwargs)
            captured["statuses"] = result[1]
            return result

        marketplace._scan = observed_scan
        try:
            _ORIGINAL_HARVEST_MARKETS(kb, state, diag)
        finally:
            marketplace._scan = original_scan

        statuses = captured.get("statuses") or ()
        diag.notes.extend(scan_status_detail_notes(statuses))
        diag.source_failures += count_fail_visible_statuses(statuses)

    harvest.install_scan_stack = install_scan_stack_resilient
    harvest.harvest_markets = harvest_markets_resilient
    _INSTALLED = True
