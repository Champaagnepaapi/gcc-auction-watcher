"""Fanatics-native exact identity discovery for the V4 Global marketplace lane.

The public Fanatics browse remains inventory-first.  This module removes the
historical GCC-SOLD seed prerequisite from Fanatics identity discovery: the
listing H1 supplies a strict provider coordinate, then the already-proven V4
TCGdex stack must resolve that coordinate exactly.

No fuzzy matching, translation, transaction capability, or SOLD inference is
introduced here.  A Fanatics Buy Now listing remains a FIXED_ASK.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

import watcher
import v4_canonical_multimarket as multimarket
import v4_global_economic_confirmation as confirmed
import v4_global_marketplace_notify as marketplace
import v4_global_marketplace_scan as scan
import v4_global_retrieval_hardening as retrieval_v1
import v4_global_retrieval_hardening_v2 as retrieval_v2
from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_discovery import MarketplaceListing, listing_from_observation
from v4_global_marketplace_scan import ScanStatus
from v4_market_fanatics_bridge import fanatics_fixed_offer


_SUPPORTED_GRADES = frozenset({"8", "8.5", "9", "10"})
_LANGUAGE_CODES = {"japanese": ("ja", "Japanese"), "english": ("en", "English")}

# Fanatics H1 schema observed by the existing hardened collectors.  Language,
# local collector number and PSA grade are explicit; none is inferred.
_TITLE_RE = re.compile(
    r"^\s*(?P<year>\d{4})\s+Pok[eé]mon\s+"
    r"(?P<language>Japanese|English)\s+"
    r"(?P<middle>.+?)\s+#0*(?P<local>[A-Za-z0-9-]+)\s+"
    r"PSA\s*(?:GEM\s*MT\s*)?"
    r"(?P<grade>10(?:\.0)?|9(?:\.0)?|8\.5|8(?:\.0)?)\b",
    re.IGNORECASE,
)

# A rarity token is a deterministic field boundary in Fanatics' H1: set before,
# card name after.  Longer phrases must be matched before their suffixes.
_RARITY_RE = re.compile(
    r"\b(?:SPECIAL\s+ILLUSTRATION\s+RARE|ILLUSTRATION\s+RARE|"
    r"HYPER\s+RARE|ULTRA\s+RARE|DOUBLE\s+RARE|ACE\s+SPEC\s+RARE|"
    r"HOLO\s+RARE|REVERSE\s+HOLO|"
    r"SAR|CSR|CHR|SSR|RRR|AR|SR|UR|HR|RR|PROMO|HOLO|REVERSE)\b",
    re.IGNORECASE,
)
_FULL_NUMBER_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<left>[A-Za-z0-9-]+)\s*/\s*(?P<right>[A-Za-z0-9-]+)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FanaticsNativeCoordinate:
    year: int
    language_code: str
    language_label: str
    set_name: str
    name: str
    local_id: str
    grade: str
    edition: str = ""
    finish: str = ""
    variant: str = ""


@dataclass(frozen=True)
class FanaticsNativeResolution:
    status: str
    reason: str
    coordinate: Optional[FanaticsNativeCoordinate] = None
    identity: Optional[CommercialIdentity] = None


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _norm_local(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip().upper().lstrip("#")
    return str(int(raw)) if raw.isdigit() else raw


def _norm_full_number(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).replace(" ", "").upper().lstrip("#")
    if "/" not in raw:
        return _norm_local(raw)
    left, right = raw.split("/", 1)
    return f"{_norm_local(left)}/{_norm_local(right)}"


def _grade(value: object) -> str:
    try:
        parsed = float(str(value or "").strip())
    except (TypeError, ValueError):
        return ""
    return str(int(parsed)) if parsed.is_integer() else f"{parsed:g}"


def _explicit_dimensions(title: str) -> tuple[str, str, str]:
    normalized = unicodedata.normalize("NFKC", title or "")
    upper = normalized.upper()

    edition = ""
    if re.search(r"\b1ST\s+EDITION\b|\bFIRST\s+EDITION\b", upper):
        edition = "First Edition"
    elif re.search(r"\bUNLIMITED\b", upper):
        edition = "Unlimited"

    variant = "Shadowless" if re.search(r"\bSHADOWLESS\b", upper) else ""

    finish = ""
    if re.search(r"\bREVERSE\s+HOLO(?:FOIL)?\b", upper):
        finish = "Reverse Holo"
    elif re.search(r"\bNON[-\s]?HOLO\b", upper):
        finish = "Non-Holo"
    elif re.search(r"\bHOLO(?:FOIL)?\b", upper):
        finish = "Holo"
    return edition, finish, variant


def parse_fanatics_native_coordinate(title: str) -> FanaticsNativeResolution:
    """Parse only the bounded public Fanatics H1 schema, fail-closed otherwise."""
    normalized = " ".join(unicodedata.normalize("NFKC", str(title or "")).split())
    match = _TITLE_RE.search(normalized)
    if not match:
        return FanaticsNativeResolution("NO_MATCH", "fanatics_title_schema_unproven")

    language_key = match.group("language").casefold()
    language = _LANGUAGE_CODES.get(language_key)
    if language is None:
        return FanaticsNativeResolution("NO_MATCH", "language_unproven")

    grade = _grade(match.group("grade"))
    if grade not in _SUPPORTED_GRADES:
        return FanaticsNativeResolution("NO_MATCH", "unsupported_psa_grade")

    middle = " ".join(match.group("middle").split())
    rarity_matches = list(_RARITY_RE.finditer(middle))
    if len(rarity_matches) != 1:
        reason = "rarity_boundary_missing" if not rarity_matches else "rarity_boundary_ambiguous"
        return FanaticsNativeResolution("NO_MATCH", reason)

    rarity = rarity_matches[0]
    raw_set = middle[: rarity.start()].strip(" -|:")
    name = middle[rarity.end() :].strip(" -|:")
    raw_set = retrieval_v1.FANATICS_SET_CODE_RE.sub("", raw_set).strip()
    raw_set = retrieval_v2.FANATICS_ERA_PREFIX_RE.sub("", raw_set).strip()
    raw_set = re.sub(r"^Pok[eé]mon\s+", "", raw_set, flags=re.IGNORECASE).strip()
    if not raw_set or not name:
        return FanaticsNativeResolution("NO_MATCH", "set_or_name_unproven")

    edition, finish, variant = _explicit_dimensions(normalized)
    coordinate = FanaticsNativeCoordinate(
        year=int(match.group("year")),
        language_code=language[0],
        language_label=language[1],
        set_name=raw_set,
        name=name,
        local_id=_norm_local(match.group("local")),
        grade=grade,
        edition=edition,
        finish=finish,
        variant=variant,
    )
    return FanaticsNativeResolution("PARSED", "fanatics_h1_native_coordinate", coordinate=coordinate)


def _lot_for_coordinate(coordinate: FanaticsNativeCoordinate) -> watcher.Lot:
    return watcher.Lot(
        url="https://fanaticscollect.com/read-only-native-identity",
        title=coordinate.name,
        current_price=1.0,
        source_type="FIXED_PRICE",
        grader="PSA",
        grade=coordinate.grade,
        listing_text=coordinate.name,
        card_set=coordinate.set_name,
        card_number=coordinate.local_id,
        language=coordinate.language_label,
        year=coordinate.year,
        variant=" ".join(
            value
            for value in (coordinate.edition, coordinate.finish, coordinate.variant)
            if value
        ),
    )


def _exposed_full_numbers(text: str) -> set[str]:
    output: set[str] = set()
    for match in _FULL_NUMBER_RE.finditer(unicodedata.normalize("NFKC", str(text or ""))):
        output.add(_norm_full_number(f"{match.group('left')}/{match.group('right')}"))
    return output


def resolve_fanatics_native_identity(
    title: str,
    *,
    proof_text: str = "",
    resolver: Callable[[watcher.Lot], multimarket.CanonicalCard] = multimarket.resolve_tcgdex_card,
) -> FanaticsNativeResolution:
    """Resolve a Fanatics H1 coordinate through the exact V4 TCGdex resolver."""
    parsed = parse_fanatics_native_coordinate(title)
    coordinate = parsed.coordinate
    if parsed.status != "PARSED" or coordinate is None:
        return parsed

    canonical = resolver(_lot_for_coordinate(coordinate))
    if canonical.status != "EXACT":
        return FanaticsNativeResolution(
            canonical.status or "NO_MATCH",
            f"tcgdex_{(canonical.reason or canonical.status or 'no_match').casefold()}",
            coordinate=coordinate,
        )
    if canonical.language_code != coordinate.language_code:
        return FanaticsNativeResolution("AMBIGUOUS", "tcgdex_language_conflict", coordinate=coordinate)
    if _norm_local(canonical.local_id) != coordinate.local_id:
        return FanaticsNativeResolution("AMBIGUOUS", "tcgdex_local_id_conflict", coordinate=coordinate)

    # The provider set/name must agree exactly with the resolved catalog labels.
    # This intentionally refuses implicit translation or set-family guessing.
    if _norm(canonical.set_name) != _norm(coordinate.set_name):
        return FanaticsNativeResolution("AMBIGUOUS", "tcgdex_set_name_conflict", coordinate=coordinate)
    if _norm(canonical.name) != _norm(coordinate.name):
        return FanaticsNativeResolution("AMBIGUOUS", "tcgdex_card_name_conflict", coordinate=coordinate)

    exposed = _exposed_full_numbers(f"{title}\n{proof_text}")
    canonical_number = _norm_full_number(canonical.full_number)
    if exposed and canonical_number not in exposed:
        return FanaticsNativeResolution("AMBIGUOUS", "conflicting_full_fraction", coordinate=coordinate)

    identity = CommercialIdentity(
        name=canonical.name,
        set_name=canonical.set_name,
        number=canonical.full_number or coordinate.local_id,
        language=coordinate.language_code,
        grader="PSA",
        grade=coordinate.grade,
        edition=coordinate.edition,
        finish=coordinate.finish,
        variant=coordinate.variant,
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return FanaticsNativeResolution("NO_MATCH", "commercial_identity_incomplete", coordinate=coordinate)
    return FanaticsNativeResolution(
        "EXACT",
        "FANATICS_H1_NATIVE_TCGDEX_EXACT",
        coordinate=coordinate,
        identity=identity,
    )


def scan_fanatics_native_inventory(
    page: Any,
    _seeds: Sequence[Any],
    *,
    observed_at,
    max_detail_pages: int = 200,
    scroll_rounds: int = 20,
) -> tuple[list[MarketplaceListing], ScanStatus]:
    """Broad public Fanatics scan whose identity no longer depends on GCC history."""
    try:
        urls, rounds = scan._fanatics_urls(page, scroll_rounds=scroll_rounds)
    except Exception as error:
        return [], ScanStatus("fanatics", "ERROR", detail=type(error).__name__, complete=False)

    # Install the same deterministic TCGdex wrapper stack used later by Global
    # confirmation.  In the resilient runner this function is rebound to the
    # full proven bridge stack before scanning starts; installers are idempotent.
    confirmed.install_global_external_market_stack()

    output: list[MarketplaceListing] = []
    rejects: Counter[str] = Counter()
    limit = max(1, int(max_detail_pages))
    for url in urls[:limit]:
        title = ""
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(500)
            title = page.locator("h1").first.inner_text(timeout=4000).strip()
            body = page.locator("body").inner_text(timeout=5000)
        except Exception:
            rejects["page_error"] += 1
            continue

        upper = body.upper()
        if "THIS ITEM IS NOT AVAILABLE" in upper or re.search(r"\bSOLD\s*:", upper):
            rejects["unavailable_or_sold"] += 1
            continue
        before_guide = re.split(r"Guide Price", body, maxsplit=1, flags=re.IGNORECASE)[0]
        price = scan.legacy._price_from_usd_text(before_guide)
        if price is None:
            rejects["price_unproven"] += 1
            continue

        resolution = resolve_fanatics_native_identity(
            title,
            proof_text=before_guide,
            resolver=multimarket.resolve_tcgdex_card,
        )
        if resolution.status != "EXACT" or resolution.identity is None:
            rejects[resolution.reason or resolution.status or "identity_unproven"] += 1
            continue

        observation = fanatics_fixed_offer(
            identity=resolution.identity,
            price_usd=price,
            observed_at=observed_at,
            source_id=url,
            identity_proven=True,
            buyer_fee_rate=0.0,
            note=(
                "Fanatics marketplace-first Buy Now ASK; native H1 -> exact TCGdex identity; "
                "GCC history is not an identity prerequisite; ASK is not SOLD"
            ),
        )
        output.append(listing_from_observation(observation, source_url=url, title=title))

    complete = len(urls) <= limit
    detail = (
        "direct marketplace browse; Fanatics-native H1 -> exact TCGdex; "
        f"GCC identity catalog not required; rejects={dict(rejects)}"
    )
    return output, ScanStatus(
        "fanatics",
        "OK",
        pages=rounds,
        candidates=len(urls),
        exact=len(output),
        detail=detail,
        complete=complete,
    )


_INSTALLED = False
_ORIGINAL_SCAN = None
_ORIGINAL_FANATICS_SCAN = None


def _scan_with_catalog_independent_fanatics(args, *, observed_at):
    listings, statuses, gcc_fair, catalog_status = _ORIGINAL_SCAN(args, observed_at=observed_at)

    if getattr(args, "no_browser_sources", False):
        return listings, statuses, gcc_fair, catalog_status

    fanatics_status = next((row for row in statuses if row.market == "fanatics"), None)
    if fanatics_status is None or fanatics_status.status != "SKIPPED":
        return listings, statuses, gcc_fair, catalog_status
    if "identity catalog unavailable" not in str(fanatics_status.detail or ""):
        return listings, statuses, gcc_fair, catalog_status

    # GCC history may be temporarily unavailable.  Fanatics native discovery must
    # still work; magi/COMC keep their existing GCC-catalog dependency until their
    # own dedicated phases.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(locale="en-US", user_agent="Mozilla/5.0")
            page = context.new_page()
            fan_rows, fan_status = scan_fanatics_native_inventory(
                page,
                (),
                observed_at=observed_at,
                max_detail_pages=max(1, int(args.browser_detail_cap)),
                scroll_rounds=max(1, int(args.browser_scroll_rounds)),
            )
            context.close()
            browser.close()
    except Exception as error:
        fan_rows = []
        fan_status = ScanStatus(
            "fanatics",
            "ERROR",
            detail=f"native catalog-independent scan failed: {type(error).__name__}",
            complete=False,
        )

    merged = {listing.stable_key: listing for listing in listings if listing.market != "fanatics"}
    for listing in fan_rows:
        merged[listing.stable_key] = listing
    statuses = [row for row in statuses if row.market != "fanatics"] + [fan_status]
    return list(merged.values()), statuses, gcc_fair, catalog_status


def install_global_fanatics_native_identity() -> None:
    """Install Fanatics-native identity before the Cardova scan wrapper."""
    global _INSTALLED, _ORIGINAL_SCAN, _ORIGINAL_FANATICS_SCAN
    if _INSTALLED:
        return
    _ORIGINAL_SCAN = marketplace._scan
    _ORIGINAL_FANATICS_SCAN = scan.scan_fanatics_inventory
    scan.scan_fanatics_inventory = scan_fanatics_native_inventory
    # marketplace imported the scanner by name, so patch that bound reference too.
    marketplace.scan_fanatics_inventory = scan_fanatics_native_inventory
    marketplace._scan = _scan_with_catalog_independent_fanatics
    _INSTALLED = True
