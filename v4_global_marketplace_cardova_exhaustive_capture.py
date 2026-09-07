"""Bounded Cardova public pagination without accepted-only early truncation.

The legacy public collector stopped a lane after two pages produced no *new
accepted* Pokemon/PSA rows.  Pages containing only unsupported sports/graders or
other out-of-scope inventory could therefore stop retrieval before later Pokemon
cards were visited.  This transport wrapper scans the full configured page
window unless Cardova itself explicitly proves the last page.

Completeness remains fail-closed.  ``complete=True`` is emitted only when both
auction and fixed-price listing payloads carry explicit pagination metadata that
proves the last page (or GraphQL-style ``hasNextPage=false``).  Hitting the local
page cap, duplicate rows or two quiet pages never proves exhaustive coverage.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

import v4_cardova_public_inventory as base
import v4_global_cardova_public_install as public_install


_INSTALLED = False


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 1 else None


def _mapping_proves_last_page(value: object, *, depth: int = 0) -> bool:
    if depth > 7:
        return False
    if isinstance(value, Mapping):
        pairs = (
            ("current_page", "last_page"),
            ("currentPage", "lastPage"),
            ("page", "total_pages"),
            ("page", "totalPages"),
            ("page", "pageCount"),
            ("page_no", "total_page"),
        )
        for current_key, last_key in pairs:
            current = _positive_int(value.get(current_key))
            last = _positive_int(value.get(last_key))
            if current is not None and last is not None and current >= last:
                return True
        page_info = value.get("pageInfo")
        if isinstance(page_info, Mapping) and page_info.get("hasNextPage") is False:
            return True
        for nested in value.values():
            if _mapping_proves_last_page(nested, depth=depth + 1):
                return True
    elif isinstance(value, list):
        for nested in value[:20]:
            if _mapping_proves_last_page(nested, depth=depth + 1):
                return True
    return False


def _payload_has_listing_rows(payload: object) -> bool:
    for rows in base._row_lists(payload):
        if any(base._looks_like_listing_row(row) for row in rows):
            return True
    return False


def capture_cardova_public_inventory_exhaustive(
    page: Any,
    *,
    max_pages_each: int = 12,
    settle_ms: int = 900,
) -> base.CardovaPublicCapture:
    fixed: dict[str, dict[str, Any]] = {}
    auction: dict[str, dict[str, Any]] = {}
    rejects: Counter[str] = Counter()
    json_responses = 0
    raw_rows = 0
    pages_visited = 0
    current_lane = ""
    lane_complete = {"auction": False, "fixed": False}

    def on_response(response: Any) -> None:
        nonlocal json_responses, raw_rows
        if not base._safe_cardova_get(response):
            return
        try:
            headers = response.headers
            content_type = str(headers.get("content-type") or headers.get("Content-Type") or "").casefold()
        except Exception:
            content_type = ""
        if "json" not in content_type:
            return
        try:
            payload = response.json()
        except Exception:
            return
        json_responses += 1
        has_listing_rows = _payload_has_listing_rows(payload)
        for rows in base._row_lists(payload):
            for row in rows:
                if not base._looks_like_listing_row(row):
                    continue
                raw_rows += 1
                accepted, reason = base._supported_single_scope(row)
                if not accepted:
                    rejects[reason] += 1
                    continue
                clean = base._sanitize_row(row)
                ulid = str(clean.get("ulid") or "").strip()
                kind = base._listing_type(clean.get("listing_type"))
                target = auction if kind == 1 else fixed
                target[ulid] = clean
        # Pagination metadata can only prove completeness on a response that is
        # demonstrably carrying Cardova listing rows for the currently visited
        # lane. Unrelated Cardova JSON cannot close the lane.
        if current_lane and has_listing_rows and _mapping_proves_last_page(payload):
            lane_complete[current_lane] = True

    page.on("response", on_response)
    try:
        lanes = (
            ("auction", base.CARDOVA_AUCTION_URL),
            ("fixed", base.CARDOVA_FIXED_URL),
        )
        for lane, url in lanes:
            current_lane = lane
            for page_number in range(1, max(1, int(max_pages_each)) + 1):
                page.goto(base._page_url(url, page_number), wait_until="domcontentloaded", timeout=25000)
                pages_visited += 1
                page.wait_for_timeout(max(0, int(settle_ms)))
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(min(max(0, int(settle_ms)), 900))
                except Exception:
                    pass
                if lane_complete[lane]:
                    break
    except Exception as error:
        return base.CardovaPublicCapture(
            fixed_payload={"list": list(fixed.values())},
            auction_payload={"list": list(auction.values())},
            pages_visited=pages_visited,
            json_responses=json_responses,
            raw_listing_rows=raw_rows,
            accepted_rows=len(fixed) + len(auction),
            rejected_rows=dict(rejects),
            status=f"ERROR:{type(error).__name__}",
            complete=False,
        )
    finally:
        current_lane = ""
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    status = "OK" if json_responses > 0 else "NO_PUBLIC_JSON"
    return base.CardovaPublicCapture(
        fixed_payload={"list": list(fixed.values())},
        auction_payload={"list": list(auction.values())},
        pages_visited=pages_visited,
        json_responses=json_responses,
        raw_listing_rows=raw_rows,
        accepted_rows=len(fixed) + len(auction),
        rejected_rows=dict(rejects),
        status=status,
        complete=bool(lane_complete["auction"] and lane_complete["fixed"]),
    )


def install_global_marketplace_cardova_exhaustive_capture() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    public_install.capture_cardova_public_inventory = capture_cardova_public_inventory_exhaustive
    _INSTALLED = True
