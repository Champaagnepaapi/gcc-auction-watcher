from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

MIN_STRONG_SOLD_COMPS = 3


class PriceConfidence(str, Enum):
    STRONG = "STRONG"
    WEAK_EXACT_PRICE = "WEAK_EXACT_PRICE"
    UNKNOWN = "UNKNOWN"


class LookupStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CACHE_SUFFICIENT = "CACHE_SUFFICIENT"
    QUERY_US = "QUERY_US"
    QUERY_UK_FALLBACK = "QUERY_UK_FALLBACK"
    PENDING_EBAY_QUOTA = "PENDING_EBAY_QUOTA"


@dataclass(frozen=True)
class CandidateContext:
    identity_exact: bool
    economically_interesting: bool
    cached_strong_sold: int = 0


@dataclass(frozen=True)
class LookupDecision:
    status: LookupStatus
    reason: str


@dataclass
class QuotaImpactTelemetry:
    eligible_candidates: int = 0
    lookups_attempted: int = 0
    lookups_blocked_quota: int = 0
    confirmed_missed_due_to_quota: int = 0
    pending_identity_keys: list[str] = field(default_factory=list)

    def record_eligible(self) -> None:
        self.eligible_candidates += 1

    def record_attempt(self) -> None:
        self.lookups_attempted += 1

    def record_quota_block(self, identity_key: str) -> None:
        self.lookups_blocked_quota += 1
        if identity_key and identity_key not in self.pending_identity_keys:
            self.pending_identity_keys.append(identity_key)

    def record_confirmed_miss(self, identity_key: str) -> None:
        # This is only called on retrospective replay when evidence that already
        # existed at the original snapshot would have confirmed the opportunity.
        self.confirmed_missed_due_to_quota += 1
        if identity_key in self.pending_identity_keys:
            self.pending_identity_keys.remove(identity_key)


def choose_lookup(
    candidate: CandidateContext,
    *,
    remaining_requests: int,
    us_strong_sold: int | None = None,
) -> LookupDecision:
    """Basic-plan policy: exact identity + interesting candidate only.

    US is queried first. UK is only a fallback when the US result has fewer
    than MIN_STRONG_SOLD_COMPS strong exact SOLD comps. No call is made when
    the hard quota is exhausted. A missing provider result is never negative
    evidence.
    """
    if not candidate.identity_exact:
        return LookupDecision(LookupStatus.NOT_ELIGIBLE, "IDENTITY_NOT_EXACT")
    if not candidate.economically_interesting:
        return LookupDecision(LookupStatus.NOT_ELIGIBLE, "NOT_ECONOMICALLY_INTERESTING")
    if candidate.cached_strong_sold >= MIN_STRONG_SOLD_COMPS:
        return LookupDecision(LookupStatus.CACHE_SUFFICIENT, "CACHED_SOLD_SUFFICIENT")
    if remaining_requests <= 0:
        return LookupDecision(LookupStatus.PENDING_EBAY_QUOTA, "EBAY_ASP_QUOTA_EXHAUSTED")
    if us_strong_sold is None:
        return LookupDecision(LookupStatus.QUERY_US, "US_FIRST")
    if us_strong_sold >= MIN_STRONG_SOLD_COMPS:
        return LookupDecision(LookupStatus.CACHE_SUFFICIENT, "US_SOLD_SUFFICIENT")
    return LookupDecision(LookupStatus.QUERY_UK_FALLBACK, "US_SOLD_INSUFFICIENT")


def classify_sale_price(row: Mapping[str, object]) -> PriceConfidence:
    """Do not silently treat Best Offer display price as proven exact price."""
    fmt = str(row.get("buying_format") or row.get("listing_type") or "").casefold()
    if "best offer" in fmt or "best_offer" in fmt:
        return PriceConfidence.WEAK_EXACT_PRICE
    if "auction" in fmt or "buy it now" in fmt or "fixed" in fmt:
        return PriceConfidence.STRONG
    return PriceConfidence.UNKNOWN


def dedupe_sales_global(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """One eBay item_id is one market event, regardless of US/UK storefront.

    Marketplace/domain/currency observations are retained as provenance arrays;
    they do not create duplicate sales.
    """
    by_id: dict[str, dict[str, object]] = {}
    no_id: list[dict[str, object]] = []
    for source in rows:
        row = dict(source)
        item_id = str(row.get("ebay_item_id") or row.get("item_id") or "").strip()
        if not item_id:
            no_id.append(row)
            continue
        current = by_id.get(item_id)
        market = str(row.get("marketplace") or row.get("site") or "").strip()
        currency = str(row.get("currency") or "").strip()
        url = str(row.get("url") or row.get("link") or "").strip()
        if current is None:
            current = row
            current["ebay_item_id"] = item_id
            current["marketplaces_seen"] = []
            current["currencies_seen"] = []
            current["urls_seen"] = []
            by_id[item_id] = current
        if market and market not in current["marketplaces_seen"]:
            current["marketplaces_seen"].append(market)
        if currency and currency not in current["currencies_seen"]:
            current["currencies_seen"].append(currency)
        if url and url not in current["urls_seen"]:
            current["urls_seen"].append(url)
    return list(by_id.values()) + no_id


def same_english_card_across_marketplaces(*, identity_equal: bool, regional_variant_proven: bool) -> bool:
    """US/UK storefront is market provenance, not card identity by default.

    A proven regional printing/promo/microvariant remains a separate identity.
    """
    return bool(identity_equal and not regional_variant_proven)
