"""Production hardening for the marketplace-first Global lane.

This module is intentionally scoped to the new marketplace-first runner. It
reuses the existing exact V4 provider stack while fixing four bootstrap issues
proved by the first live run:

* GCC ``character`` metadata may be generic (for example ``Trainer``) while the
  public listing title carries the actual card name. The title is therefore used
  as the candidate name after removing only the leading PSA grade label; exact
  TCGdex resolution still has to prove the downstream coordinate.
* GCC SOLD history is a retrieval/fair-value catalogue across EN/JA and the V4
  PSA production grades, not a prerequisite for discovering a live listing.
* Pending inventory is evaluated in economic priority order instead of arbitrary
  API insertion order.
* A transient/pending external provider never gets acknowledged merely because
  the correlated sibling returned a terminal no-match.

PokemonPriceTracker is also generalized from the earlier JP/PSA10-only Global
adapter to exact EN/JA PSA 8/8.5/9/10 coordinates. It remains aggregate SOLD
evidence, correlated with PokeTrace/eBay, and never turns an ASK into a sale.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence

import requests

import japan_edge_hunter as japan
import v4_global_live_confirmed as confirmed
import v4_global_live_shadow as legacy
import v4_global_marketplace_discovery as discovery
import v4_global_marketplace_notify as marketplace
import v4_global_marketplace_scan as scan
import v4_global_ppt_confirmation as ppt
from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FIXED_ASK,
    SOLD_EXACT,
    CommercialIdentity,
    PriceObservation,
    build_fair_value,
)


SUPPORTED_PSA_GRADES = frozenset({"8", "8.5", "9", "10"})
_RETRY_PROVIDER = frozenset(
    {
        "PROVIDER_ERROR",
        "TRANSIENT_UNAVAILABLE",
        "RATE_LIMIT",
        "PENDING_BUDGET",
        "UNAVAILABLE",
    }
)
_TERMINAL_PROVIDER = frozenset(
    {
        "MATCHED",
        "CLEAN_NO_MATCH",
        "CLEAN_INSUFFICIENT",
        "STALE_OR_UNDATED",
        "BLOCKED_IDENTITY",
        "BLOCKED_LANGUAGE",
        "BLOCKED_GRADE",
        "PROVIDER_DISABLED",
        "MICROVARIANT_UNPROVEN",
        "AMBIGUOUS",
        "FX_UNAVAILABLE",
        "TCGDEX_UNRESOLVED",
        "TCGDEX_NO_MATCH",
        "TCGDEX_AMBIGUOUS",
    }
)

_ORIGINAL_GCC_IDENTITY = discovery.gcc_identity_from_row
_ORIGINAL_GCC_LISTING = discovery.gcc_listing_from_row
_ORIGINAL_SCAN = marketplace._scan
_INSTALLED = False


def _grade(value: object) -> str:
    try:
        number = float(str(value or "").strip())
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _language(value: object) -> str:
    text = ppt._norm(value)
    if text in {"ja", "jp", "japanese", "japonais", "japan"}:
        return "ja"
    if text in {"en", "english", "anglais"}:
        return "en"
    return text


def _title_card_name(row: Mapping[str, Any]) -> str:
    item = row.get("item")
    if not isinstance(item, Mapping):
        return ""
    title = str(item.get("title") or "").strip()
    if not title:
        return ""
    # Remove only the leading slab-grade label. Everything else remains evidence
    # for exact TCGdex reconciliation; no fuzzy suffix stripping is performed.
    cleaned = re.sub(
        r"^\s*PSA\s*(?:GEM\s*MT\s*)?(?:10(?:\.0)?|9(?:\.0)?|8\.5|8(?:\.0)?)\s*(?:[-–—:]\s*)?",
        "",
        title,
        count=1,
        flags=re.I,
    ).strip()
    return cleaned or title


def gcc_identity_from_row_hardened(row: Mapping[str, Any]) -> Optional[CommercialIdentity]:
    base = _ORIGINAL_GCC_IDENTITY(row)
    if base is None:
        return None
    title_name = _title_card_name(row)
    if not title_name:
        return base
    return replace(base, name=title_name)


def gcc_listing_from_row_hardened(
    row: Mapping[str, Any], *, observed_at: datetime
) -> Optional[discovery.MarketplaceListing]:
    listing = _ORIGINAL_GCC_LISTING(row, observed_at=observed_at)
    if listing is None:
        return None
    # The official GCC pricing page lists marketplace commission on the seller
    # side, while a purchase transfers the card directly to the buyer's free
    # Vault. Treat displayed price as the immediate Vault acquisition basis;
    # optional later retrieval/shipping/insurance is a separate user action.
    return replace(
        listing,
        note=(
            "GCC live marketplace observation; displayed price is Vault acquisition basis; "
            "optional later withdrawal/shipping excluded; ASK/current auction is not SOLD"
        ),
    )


def _sold_time(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _sold_price(row: Mapping[str, Any]) -> Optional[float]:
    cents = row.get("priceInCents")
    if isinstance(cents, int) and not isinstance(cents, bool) and cents > 0:
        return cents / 100.0
    try:
        value = float(row.get("price") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _source_identity(row: Mapping[str, Any], identity: CommercialIdentity) -> Optional[japan.Identity]:
    item = row.get("item")
    collectible = item.get("collectible") if isinstance(item, Mapping) else None
    if not isinstance(collectible, Mapping):
        return None
    try:
        year = int(collectible.get("yearOfDistribution"))
    except (TypeError, ValueError):
        return None
    if not 1996 <= year <= 2100:
        return None
    return japan.Identity(
        name=identity.name,
        set_name=identity.set_name,
        number=identity.number,
        language="Japanese" if identity.language == "ja" else "English",
        grader=identity.grader,
        grade=identity.grade,
        year=year,
        edition=identity.edition,
        attribute=identity.finish,
        variety=identity.variant,
        rarity="",
    )


def build_identity_catalog_hardened(
    *, observed_at: datetime, gcc_sold_pages: int = 30
):
    """Build retrieval identities and optional exact GCC SOLD fairs independently.

    Every accepted sale requires explicit ``status=SOLD``, a timezone-aware
    ``soldAt`` and a positive final price. Fixed asks, active auctions and listing
    disappearance never enter this catalogue as sales.
    """
    groups: dict[str, list[PriceObservation]] = {}
    retrieval: dict[str, Any] = {}
    seen_sale_ids: set[str] = set()
    pages = rows_seen = sold_kept = 0
    client = requests.Session()
    try:
        for selling in ("AUCTION", "FIXED_PRICE"):
            for page_no in range(1, max(1, int(gcc_sold_pages)) + 1):
                response = client.get(
                    legacy.GCC_API_URL,
                    params={
                        "sellingTypeGroup": selling,
                        "status": "SOLD",
                        "sortType": "MOST_RECENT",
                        "page": page_no,
                        "limit": 100,
                        "includeCounts": "true" if page_no == 1 else "false",
                    },
                    headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
                    timeout=15,
                )
                response.raise_for_status()
                payload = response.json()
                rows = payload.get("results") if isinstance(payload, Mapping) else None
                if not isinstance(rows, list):
                    raise RuntimeError("GCC_SOLD_RESULTS_MALFORMED")
                pages += 1
                if not rows:
                    break
                rows_seen += len(rows)
                for raw in rows:
                    if not isinstance(raw, Mapping):
                        continue
                    if str(raw.get("status") or "").strip().upper() != "SOLD":
                        continue
                    sold_at = _sold_time(raw.get("soldAt"))
                    price = _sold_price(raw)
                    source_id = str(raw.get("id") or "").strip()
                    if sold_at is None or price is None or not source_id or source_id in seen_sale_ids:
                        continue
                    identity = gcc_identity_from_row_hardened(raw)
                    if identity is None or not identity.complete_for_exact_market:
                        continue
                    seen_sale_ids.add(source_id)
                    observation = PriceObservation(
                        source="gcc",
                        identity=identity,
                        evidence_type=SOLD_EXACT,
                        price=price,
                        currency="EUR",
                        observed_at=observed_at,
                        identity_proven=True,
                        sold_at=sold_at,
                        source_id=source_id,
                        note="explicit GCC status=SOLD + soldAt + final positive price",
                    )
                    groups.setdefault(identity.strict_key, []).append(observation)
                    sold_kept += 1
                    if identity.language == "ja" and identity.grader == "PSA" and identity.grade == "10":
                        source = _source_identity(raw, identity)
                        if source is not None:
                            retrieval.setdefault(
                                identity.strict_key,
                                SimpleNamespace(source_identity=source, identity=identity),
                            )
                info = payload.get("info") if isinstance(payload, Mapping) else None
                if isinstance(info, Mapping) and not info.get("nextPage"):
                    break
    except Exception as error:
        return [], {}, f"ERROR:{type(error).__name__}:pages={pages}:rows={rows_seen}:kept={sold_kept}"
    finally:
        client.close()

    fair: dict[str, float] = {}
    for key, evidence in groups.items():
        value = build_fair_value(
            evidence[0].identity,
            evidence,
            now=observed_at,
            currency_per_eur={},
        )
        if value is not None and value.notification_safe and value.central_eur > 0:
            fair[key] = value.central_eur
    return (
        list(retrieval.values()),
        fair,
        f"OK:retrieval={len(retrieval)}:fair={len(fair)}:sold={sold_kept}:pages={pages}",
    )


def _row_language_compatible(identity: CommercialIdentity, row: Mapping[str, object]) -> bool:
    declared = row.get("language")
    if declared in (None, ""):
        return True
    expected = _language(identity.language)
    actual = _language(declared)
    return expected in {"en", "ja"} and actual == expected


def _match_canonical_general(
    identity: CommercialIdentity,
    canonical,
    rows: Sequence[Mapping[str, object]],
    *,
    provider_set_id: str = "",
):
    if canonical.status != "EXACT" or not canonical.card_id:
        return "TCGDEX_UNRESOLVED", None, ""
    expected_catalog = ppt._norm(canonical.card_id)
    expected_number = ppt._collector(identity.number)
    expected_set_id = ppt._norm(provider_set_id)
    unique = ppt._unique_rows(rows)

    catalog_matches = []
    for row in unique:
        if not _row_language_compatible(identity, row):
            continue
        if ppt._collector(row.get("cardNumber") or row.get("number")) != expected_number:
            continue
        row_catalog = ppt._norm(row.get("externalCatalogId"))
        if not row_catalog or row_catalog != expected_catalog:
            continue
        if expected_set_id:
            row_set_id = ppt._norm(row.get("setId") or row.get("set_id"))
            if row_set_id and row_set_id != expected_set_id:
                continue
        catalog_matches.append(row)
    if len(catalog_matches) > 1:
        return "AMBIGUOUS", None, "TCGDEX_EXTERNAL_CATALOG_ID"
    if len(catalog_matches) == 1:
        row = catalog_matches[0]
        if not ppt._variant_compatible(identity, row):
            return "MICROVARIANT_UNPROVEN", None, "TCGDEX_EXTERNAL_CATALOG_ID"
        return "EXACT", row, "TCGDEX_EXTERNAL_CATALOG_ID"

    target_names = {ppt._norm(identity.name), ppt._norm(canonical.name)} - {""}
    target_sets = {ppt._norm(identity.set_name), ppt._norm(canonical.set_name)} - {""}
    fallback = []
    for row in unique:
        if not _row_language_compatible(identity, row):
            continue
        if ppt._norm(row.get("externalCatalogId")):
            continue
        if ppt._collector(row.get("cardNumber") or row.get("number")) != expected_number:
            continue
        if ppt._norm(row.get("name")) not in target_names:
            continue
        if ppt._norm(row.get("setName") or row.get("set_name")) not in target_sets:
            continue
        if expected_set_id:
            row_set_id = ppt._norm(row.get("setId") or row.get("set_id"))
            if row_set_id and row_set_id != expected_set_id:
                continue
        fallback.append(row)
    if len(fallback) > 1:
        return "AMBIGUOUS", None, "TCGDEX_SET_NAME_NUMBER_FALLBACK"
    if len(fallback) == 1:
        row = fallback[0]
        if not ppt._variant_compatible(identity, row):
            return "MICROVARIANT_UNPROVEN", None, "TCGDEX_SET_NAME_NUMBER_FALLBACK"
        return "EXACT", row, "TCGDEX_SET_NAME_NUMBER_FALLBACK"
    return "CLEAN_NO_MATCH", None, "TCGDEX_COORDINATE_NOT_FOUND"


def fetch_ppt_snapshot_generalized(
    identity: CommercialIdentity,
    *,
    api_key: str,
    budget: ppt.PptBudget,
    session: requests.Session,
    fx,
    timeout: float = 15.0,
    now: Optional[datetime] = None,
    canonical=None,
) -> ppt.PptSnapshot:
    observed_at = now or datetime.now(timezone.utc)
    language = _language(identity.language)
    grade = _grade(identity.grade)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return ppt.PptSnapshot("BLOCKED_IDENTITY", note="incomplete/non-actionable identity")
    if language not in {"en", "ja"}:
        return ppt.PptSnapshot("BLOCKED_LANGUAGE", note="PPT exact lane supports EN/JA only")
    if ppt._norm(identity.grader) != "psa" or grade not in SUPPORTED_PSA_GRADES:
        return ppt.PptSnapshot("BLOCKED_GRADE", note="PPT exact lane supports PSA 8/8.5/9/10")
    if not api_key:
        return ppt.PptSnapshot("PROVIDER_DISABLED", note="PPT key unavailable")

    language_query = "japanese" if language == "ja" else "english"
    reviewed = ppt.reviewed_set_id(identity) if language == "ja" else None
    matched = None
    provider_set_id = reviewed or ""
    resolution = "REVIEWED_SET_ID" if reviewed else ""

    if reviewed:
        status, payload = ppt._request(
            session,
            api_key,
            budget,
            {"language": language_query, "setId": reviewed, "search": ppt._collector(identity.number), "limit": 5},
            timeout,
        )
        if status is None:
            return ppt.PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return ppt.PptSnapshot("RATE_LIMIT", note="HTTP 429")
        if status != 200:
            return ppt.PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
        match_status, row = ppt._match(identity, ppt._rows(payload), reviewed)
        if match_status in {"AMBIGUOUS", "MICROVARIANT_UNPROVEN"}:
            return ppt.PptSnapshot(
                match_status,
                match_proof=match_status,
                note=match_status,
                provider_set_id=reviewed,
                identity_resolution=resolution,
            )
        if match_status == "EXACT":
            matched = row
    else:
        if canonical is None or canonical.status != "EXACT":
            return ppt.PptSnapshot("TCGDEX_UNRESOLVED", note="unmapped PPT set requires exact TCGdex coordinate; no network")
        status, payload = ppt._request(
            session,
            api_key,
            budget,
            {"language": language_query, "search": canonical.name or identity.name, "limit": 5},
            timeout,
        )
        if status is None:
            return ppt.PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason)
        if status == 429:
            budget.blocked_reason = "RATE_LIMIT"
            return ppt.PptSnapshot("RATE_LIMIT", note="HTTP 429")
        if status != 200:
            return ppt.PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}")
        match_status, row, proof = _match_canonical_general(identity, canonical, ppt._rows(payload))
        if match_status in {"AMBIGUOUS", "MICROVARIANT_UNPROVEN"}:
            return ppt.PptSnapshot(match_status, match_proof=proof, note=proof, identity_resolution=proof)
        if match_status == "EXACT" and row is not None:
            matched = row
            resolution = proof
            provider_set_id = str(row.get("setId") or row.get("set_id") or "").strip()

    if matched is None:
        return ppt.PptSnapshot("CLEAN_NO_MATCH", note="exact PPT coordinate not found", provider_set_id=provider_set_id, identity_resolution=resolution)
    tcgplayer_id = matched.get("tcgPlayerId") or matched.get("tcgplayerId")
    if not tcgplayer_id:
        return ppt.PptSnapshot("CLEAN_INSUFFICIENT", note="TCGPLAYER_ID_MISSING", provider_set_id=provider_set_id, identity_resolution=resolution)

    status, payload = ppt._request(
        session,
        api_key,
        budget,
        {
            "language": language_query,
            "tcgPlayerId": str(tcgplayer_id),
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "false",
            "days": 180,
            "maxDataPoints": 180,
        },
        timeout,
    )
    if status is None:
        return ppt.PptSnapshot("PENDING_BUDGET", note=budget.blocked_reason, provider_set_id=provider_set_id, identity_resolution=resolution)
    if status == 429:
        budget.blocked_reason = "RATE_LIMIT"
        return ppt.PptSnapshot("RATE_LIMIT", note="HTTP 429", provider_set_id=provider_set_id, identity_resolution=resolution)
    if status != 200:
        return ppt.PptSnapshot("PROVIDER_ERROR", note=f"HTTP {status}", provider_set_id=provider_set_id, identity_resolution=resolution)

    deep_rows = ppt._rows(payload)
    if reviewed:
        deep_status, row = ppt._match(identity, deep_rows, reviewed)
        deep_proof = "REVIEWED_SET_ID"
    else:
        deep_status, row, deep_proof = _match_canonical_general(
            identity, canonical, deep_rows, provider_set_id=provider_set_id
        )
    if deep_status != "EXACT" or row is None:
        return ppt.PptSnapshot(
            deep_status,
            match_proof=deep_proof,
            note="deep identity not exact",
            provider_set_id=provider_set_id,
            identity_resolution=resolution or deep_proof,
        )

    snapshot = ppt._snapshot_from_deep_row(
        identity,
        row,
        fx=fx,
        observed_at=observed_at,
        provider_set_id=provider_set_id,
        resolution=resolution or deep_proof,
    )
    return replace(
        snapshot,
        match_proof=(resolution or deep_proof),
        note=f"PPT {language_query} eBay graded aggregate; ASK/current auction never used",
    )


_LAST_FAIR: dict[str, float] = {}


def _scan_with_catalog(*args, **kwargs):
    global _LAST_FAIR
    listings, statuses, fair, catalog_status = _ORIGINAL_SCAN(*args, **kwargs)
    _LAST_FAIR = dict(fair)
    return listings, statuses, fair, catalog_status


def select_pending_prioritized(state, current, *, limit: int):
    pending = state.get("pending") if isinstance(state.get("pending"), list) else []
    ranked = []
    for index, raw in enumerate(pending):
        key = str(raw or "")
        listing = current.get(key)
        if listing is None:
            continue
        actionable = listing.evidence_type in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}
        fair = _LAST_FAIR.get(listing.identity.strict_key)
        known_discount = None
        if fair is not None and fair > 0 and listing.currency.upper() == "EUR" and listing.price > 0:
            known_discount = (float(fair) - float(listing.price)) / float(fair) * 100.0
        # Known GCC SOLD discounts are cheapest to prioritize. Unknown-fair
        # listings still remain pending and are drained afterwards, cheapest first.
        bucket = 0 if actionable and known_discount is not None else 1 if actionable else 2
        discount_sort = -(known_discount if known_discount is not None else -10_000.0)
        price_sort = float(listing.price) if listing.currency.upper() == "EUR" else 10**12
        ranked.append(((bucket, discount_sort, price_sort, index), key, listing))
    ranked.sort(key=lambda row: row[0])
    selected = ranked[: max(0, int(limit))]
    return [row[2] for row in selected], [row[1] for row in selected]


def evaluation_complete_hardened(card: Mapping[str, Any]) -> bool:
    confirmation = card.get("economic_confirmation")
    if not isinstance(confirmation, Mapping):
        return False
    canonical = confirmation.get("external_canonical")
    canonical_status = str(canonical.get("status") or "") if isinstance(canonical, Mapping) else ""
    if canonical_status in {"ERROR", "BUDGET"}:
        return False
    if canonical_status in {"NO_MATCH", "AMBIGUOUS"}:
        return True
    ppt_row = confirmation.get("ppt")
    pt_row = confirmation.get("poketrace")
    ppt_status = str(ppt_row.get("status") or "UNAVAILABLE") if isinstance(ppt_row, Mapping) else "UNAVAILABLE"
    pt_status = str(pt_row.get("status") or "UNAVAILABLE") if isinstance(pt_row, Mapping) else "UNAVAILABLE"
    if "MATCHED" in {ppt_status, pt_status}:
        return True
    if ppt_status in _RETRY_PROVIDER or pt_status in _RETRY_PROVIDER:
        return False
    return ppt_status in _TERMINAL_PROVIDER and pt_status in _TERMINAL_PROVIDER


def install_marketplace_first_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    discovery.gcc_identity_from_row = gcc_identity_from_row_hardened
    discovery.gcc_listing_from_row = gcc_listing_from_row_hardened
    scan.gcc_listing_from_row = gcc_listing_from_row_hardened
    scan.build_identity_catalog = build_identity_catalog_hardened
    marketplace.build_identity_catalog = build_identity_catalog_hardened
    marketplace._scan = _scan_with_catalog
    marketplace.select_pending_listings = select_pending_prioritized
    marketplace._evaluation_complete = evaluation_complete_hardened
    confirmed.fetch_snapshot = fetch_ppt_snapshot_generalized
    _INSTALLED = True
