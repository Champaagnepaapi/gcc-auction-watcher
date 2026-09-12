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


def _listing_envelopes(value: object, *, depth: int = 0):
    """Keep a listing array attached to its own immediate pagination envelope."""
    if depth > 6 or not isinstance(value, Mapping):
        return
    for key, rows in value.items():
        if key in {"items", "list", "data", "results"} and isinstance(rows, list):
            if rows and all(isinstance(row, Mapping) and base._looks_like_listing_row(row) for row in rows):
                yield value, rows
        elif isinstance(rows, Mapping):
            yield from _listing_envelopes(rows, depth=depth + 1)


def _envelope_proves_last_page(envelope: Mapping[str, Any], *, page_number: int) -> bool:
    # Contradictory or unrelated nested metadata cannot establish completeness.
    containers = [envelope]
    for key in ("meta", "pagination"):
        if isinstance(envelope.get(key), Mapping):
            containers.append(envelope[key])
    terminal = False
    for value in containers:
        page_info = value.get("pageInfo")
        if isinstance(page_info, Mapping) and page_info.get("hasNextPage") is True:
            return False
        for current_key, last_key in (
            ("current_page", "last_page"), ("currentPage", "lastPage"),
            ("page", "total_pages"), ("page", "totalPages"),
            ("page", "pageCount"), ("page_no", "total_page"),
        ):
            if current_key not in value and last_key not in value:
                continue
            current, last = _positive_int(value.get(current_key)), _positive_int(value.get(last_key))
            if current != page_number or last != current:
                return False
            terminal = True
    # A bare hasNextPage flag has no page coordinate. Preserve partial coverage
    # until the provider supplies a bound numeric page, even when it says false.
    return terminal


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
    current_page = 0
    requests_seen: set[int] = set()
    lane_complete = {"auction": False, "fixed": False}
    page_has_inventory = False
    page_evidence: list[dict[str, Any]] = []

    def on_request(request: Any) -> None:
        if current_lane and len(requests_seen) < 500:
            requests_seen.add(id(request))

    def on_response(response: Any) -> None:
        nonlocal json_responses, raw_rows, page_has_inventory
        if not base._safe_cardova_get(response) or getattr(response, "status", None) != 200:
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
        if current_lane and id(response.request) in requests_seen:
            kind = 1 if current_lane == "auction" else 4
            for envelope, rows in _listing_envelopes(payload):
                if all(base._listing_type(row.get("listing_type")) == kind for row in rows):
                    page_has_inventory = True
                    # Pagination diagnostics retain only allowlisted numeric
                    # coordinates, never arbitrary response/account fields.
                    if len(page_evidence) < 60:
                        coordinates = {}
                        for container in (envelope, envelope.get("meta"), envelope.get("pagination")):
                            if isinstance(container, Mapping):
                                for key in ("current_page", "last_page", "currentPage", "lastPage", "page", "total_pages", "totalPages", "pageCount", "page_no", "total_page", "total", "per_page", "limit", "offset"):
                                    if key in container and str(container[key]).isdigit():
                                        coordinates[key] = int(container[key])
                        page_evidence.append({"lane": current_lane, "requested_page": current_page, "rows": len(rows), "pagination": coordinates})
                    if _envelope_proves_last_page(envelope, page_number=current_page):
                        lane_complete[current_lane] = True

    page.on("request", on_request)
    page.on("response", on_response)
    try:
        lanes = (
            ("auction", base.CARDOVA_AUCTION_URL),
            ("fixed", base.CARDOVA_FIXED_URL),
        )
        for lane, url in lanes:
            current_lane = lane
            for page_number in range(1, max(1, int(max_pages_each)) + 1):
                current_page = page_number
                page_has_inventory = False
                requests_seen.clear()
                response = page.goto(base._page_url(url, page_number), wait_until="domcontentloaded", timeout=25000)
                pages_visited += 1
                http = getattr(response, "status", None)
                if isinstance(http, int) and http >= 400:
                    page_evidence.append({"lane": lane, "requested_page": page_number, "http": http, "stop": "HTTP_UNAVAILABLE"})
                    break
                # A settings/analytics response does not prove item readiness.
                # Await a request-bound listing envelope for this lane, bounded
                # to 3.6 seconds at the normal setting, without extra requests.
                for _ in range(4):
                    if page_has_inventory:
                        break
                    page.wait_for_timeout(min(900, max(0, int(settle_ms))))
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
            page_evidence=tuple(page_evidence),
        )
    finally:
        current_lane = ""
        requests_seen.clear()
        try:
            page.remove_listener("request", on_request)
        except Exception:
            pass
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    status = "OK" if raw_rows > 0 else ("PUBLIC_INVENTORY_UNPROVEN" if json_responses else "NO_PUBLIC_JSON")
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
        page_evidence=tuple(page_evidence),
    )


def install_global_marketplace_cardova_exhaustive_capture() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    public_install.capture_cardova_public_inventory = capture_cardova_public_inventory_exhaustive
    _INSTALLED = True
