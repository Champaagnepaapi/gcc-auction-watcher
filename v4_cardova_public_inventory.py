"""Sessionless read-only Cardova inventory capture for the Global V4 lane.

Cardova explicitly allows non-members to view auction listings.  The collector
therefore uses a fresh browser context with no imported cookies/session and only
observes public GET JSON responses while visiting Cardova's public live pages.

Only a strict whitelist of listing fields is retained.  Account, seller,
payment, cookie, token and header data are never persisted or returned.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re
import unicodedata


CARDOVA_AUCTION_URL = "https://www.cardova.co.jp/en/auction/weekly?kind=1"
CARDOVA_FIXED_URL = "https://www.cardova.co.jp/en/trade/live/fixed-price"
SUPPORTED_GRADES = frozenset({"8", "8.5", "9", "10"})
SUPPORTED_LANGUAGES = frozenset({"japanese", "english"})

# Deliberately excludes cert number, member/seller identifiers, account state,
# payment fields, cookies, tokens and arbitrary provider metadata.
PUBLIC_LISTING_FIELDS = frozenset(
    {
        "ulid",
        "listing_type",
        "asking_price",
        "set_asking_price",
        "set_quantity",
        "authentication_company_code",
        "grade",
        "language",
        "player",
        "variety",
        "variety_short",
        "card_number",
        "attribute",
        "attribute2",
        "attribute3",
        "remark",
        "finished",
        "bid_price",
        "start_price",
        "end_date",
        "scheduled_end_date",
        "category",
        "category_name",
        "series",
        "title",
        "item_name",
        "trade_ulid",
        "card_ulid",
    }
)


@dataclass(frozen=True)
class CardovaPublicCapture:
    fixed_payload: Mapping[str, Any]
    auction_payload: Mapping[str, Any]
    pages_visited: int
    json_responses: int
    raw_listing_rows: int
    accepted_rows: int
    rejected_rows: Mapping[str, int]
    status: str
    complete: bool = False


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.casefold()).split())


def _grade(value: object) -> str:
    try:
        number = float(str(value or "").strip())
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _listing_type(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_cardova_get(response: Any) -> bool:
    try:
        request = response.request
        method = str(request.method or "").upper()
        parsed = urlsplit(str(response.url or ""))
    except Exception:
        return False
    host = (parsed.hostname or "").casefold()
    return (
        method == "GET"
        and parsed.scheme.casefold() == "https"
        and (host == "cardova.co.jp" or host.endswith(".cardova.co.jp"))
    )


def _looks_like_listing_row(row: Mapping[str, Any]) -> bool:
    return bool(str(row.get("ulid") or "").strip()) and _listing_type(row.get("listing_type")) in {1, 4}


def _row_lists(value: object, *, depth: int = 0):
    """Yield nested lists that contain Cardova listing-shaped rows.

    The public site may wrap its list under ``data`` or another response object;
    no endpoint-specific assumption is needed and unrelated JSON is ignored.
    """
    if depth > 6:
        return
    if isinstance(value, list):
        mappings = [row for row in value if isinstance(row, Mapping)]
        if any(_looks_like_listing_row(row) for row in mappings):
            yield mappings
            return
        for item in value:
            yield from _row_lists(item, depth=depth + 1)
        return
    if isinstance(value, Mapping):
        for item in value.values():
            yield from _row_lists(item, depth=depth + 1)


def _pokemon_scope(row: Mapping[str, Any]) -> bool:
    category = _norm(row.get("category") or row.get("category_name"))
    if category:
        return category == "pokemon"
    # Older/public projections may omit an explicit category while retaining a
    # Pokemon-prefixed series/variety.  This is retrieval-only evidence; exact
    # TCGdex resolution is still mandatory downstream.
    surface = " ".join(
        str(row.get(key) or "")
        for key in ("series", "variety", "variety_short", "title", "item_name")
    )
    return "pokemon" in _norm(surface).split()


def _supported_single_scope(row: Mapping[str, Any]) -> tuple[bool, str]:
    if not _pokemon_scope(row):
        return False, "non_pokemon_or_unproven_category"
    quantity = row.get("set_quantity")
    if quantity not in {None, "", 1, "1"}:
        return False, "multi_item_set"
    language = _norm(row.get("language"))
    if language not in SUPPORTED_LANGUAGES:
        return False, "unsupported_language"
    grader = str(row.get("authentication_company_code") or "").strip().upper()
    if grader not in {"P", "PSA"}:
        return False, "unsupported_grader"
    if _grade(row.get("grade")) not in SUPPORTED_GRADES:
        return False, "unsupported_grade"
    if not str(row.get("player") or "").strip():
        return False, "missing_player"
    if not str(row.get("card_number") or "").strip():
        return False, "missing_card_number"
    if not str(row.get("variety") or row.get("variety_short") or "").strip():
        return False, "missing_series"
    return True, "accepted"


def _sanitize_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in PUBLIC_LISTING_FIELDS if key in row}


def _page_url(base: str, page_number: int) -> str:
    parsed = urlsplit(base)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["page"] = str(max(1, int(page_number)))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def capture_cardova_public_inventory(
    page: Any,
    *,
    max_pages_each: int = 12,
    settle_ms: int = 900,
) -> CardovaPublicCapture:
    """Capture public Cardova listings with no login/session import.

    Network safety is structural: the collector never calls request/POST APIs;
    it only navigates public pages and inspects GET JSON responses generated by
    those pages.  Two consecutive pages with no newly accepted ids stop a lane.
    """
    fixed: dict[str, dict[str, Any]] = {}
    auction: dict[str, dict[str, Any]] = {}
    rejects: Counter[str] = Counter()
    json_responses = 0
    raw_rows = 0
    pages_visited = 0

    def on_response(response: Any) -> None:
        nonlocal json_responses, raw_rows
        if not _safe_cardova_get(response):
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
        for rows in _row_lists(payload):
            for row in rows:
                if not _looks_like_listing_row(row):
                    continue
                raw_rows += 1
                accepted, reason = _supported_single_scope(row)
                if not accepted:
                    rejects[reason] += 1
                    continue
                clean = _sanitize_row(row)
                ulid = str(clean.get("ulid") or "").strip()
                kind = _listing_type(clean.get("listing_type"))
                target = auction if kind == 1 else fixed
                target[ulid] = clean

    page.on("response", on_response)
    try:
        for base, target in ((CARDOVA_AUCTION_URL, auction), (CARDOVA_FIXED_URL, fixed)):
            stale_pages = 0
            for page_number in range(1, max(1, int(max_pages_each)) + 1):
                before = len(target)
                page.goto(_page_url(base, page_number), wait_until="domcontentloaded", timeout=25000)
                pages_visited += 1
                page.wait_for_timeout(max(0, int(settle_ms)))
                try:
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(min(max(0, int(settle_ms)), 900))
                except Exception:
                    pass
                if len(target) == before:
                    stale_pages += 1
                else:
                    stale_pages = 0
                if stale_pages >= 2 and page_number >= 2:
                    break
    except Exception as error:
        return CardovaPublicCapture(
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
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    status = "OK" if json_responses > 0 else "NO_PUBLIC_JSON"
    return CardovaPublicCapture(
        fixed_payload={"list": list(fixed.values())},
        auction_payload={"list": list(auction.values())},
        pages_visited=pages_visited,
        json_responses=json_responses,
        raw_listing_rows=raw_rows,
        accepted_rows=len(fixed) + len(auction),
        rejected_rows=dict(rejects),
        status=status,
        # Keep false until Cardova exposes/proves an exhaustive public page count.
        # This prevents a missing listing from ever being interpreted as a sale.
        complete=False,
    )
