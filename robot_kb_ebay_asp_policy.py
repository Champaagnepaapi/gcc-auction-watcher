from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

MIN_STRONG_SOLD_COMPS = 3


class LookupStatus(str, Enum):
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CACHE_SUFFICIENT = "CACHE_SUFFICIENT"
    QUERY_US = "QUERY_US"
    QUERY_UK_FALLBACK = "QUERY_UK_FALLBACK"
    PENDING_EBAY_QUOTA = "PENDING_EBAY_QUOTA"


class PriceConfidence(str, Enum):
    STRONG_PROVIDER_REPORTED = "STRONG_PROVIDER_REPORTED"
    WEAK_BEST_OFFER_EXACT_PRICE = "WEAK_BEST_OFFER_EXACT_PRICE"
    UNKNOWN = "UNKNOWN"


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
        self.confirmed_missed_due_to_quota += 1
        if identity_key in self.pending_identity_keys:
            self.pending_identity_keys.remove(identity_key)


def choose_lookup(
    candidate: CandidateContext,
    *,
    remaining_requests: int,
    us_strong_sold: int | None = None,
) -> LookupDecision:
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
    fmt = str(row.get("buying_format") or row.get("listing_type") or "").casefold()
    if "best offer" in fmt or "best_offer" in fmt:
        return PriceConfidence.WEAK_BEST_OFFER_EXACT_PRICE
    if "auction" in fmt or "buy it now" in fmt or "fixed" in fmt:
        return PriceConfidence.STRONG_PROVIDER_REPORTED
    return PriceConfidence.UNKNOWN


@dataclass(frozen=True)
class EbayAspObservation:
    ebay_item_id: str
    title: str
    sale_price: float
    currency: str
    date_sold: str
    buying_format: str
    marketplace: str
    url: str
    price_confidence: PriceConfidence
    raw_payload: Mapping[str, object]


def normalize_sale_row(
    row: Mapping[str, object], *, marketplace: str
) -> EbayAspObservation | None:
    item_id = str(row.get("item_id") or row.get("ebay_item_id") or "").strip()
    title = str(row.get("title") or "").strip()
    currency = str(row.get("currency") or "").strip()
    date_sold = str(row.get("date_sold") or row.get("ended_at") or "").strip()
    buying_format = str(row.get("buying_format") or row.get("listing_type") or "").strip()
    url = str(row.get("link") or row.get("url") or "").strip()
    try:
        sale_price = float(row.get("sale_price") if row.get("sale_price") is not None else row.get("price"))
    except (TypeError, ValueError):
        return None
    if not item_id or not title or not currency or not date_sold or sale_price <= 0:
        return None
    return EbayAspObservation(
        ebay_item_id=item_id,
        title=title,
        sale_price=sale_price,
        currency=currency,
        date_sold=date_sold,
        buying_format=buying_format,
        marketplace=marketplace,
        url=url,
        price_confidence=classify_sale_price(row),
        raw_payload=dict(row),
    )


@dataclass(frozen=True)
class EbayAspSaleEvent:
    ebay_item_id: str
    observations: tuple[EbayAspObservation, ...]


def dedupe_global(observations: Iterable[EbayAspObservation]) -> list[EbayAspSaleEvent]:
    grouped: dict[str, list[EbayAspObservation]] = {}
    for observation in observations:
        grouped.setdefault(observation.ebay_item_id, []).append(observation)
    return [
        EbayAspSaleEvent(item_id, tuple(rows))
        for item_id, rows in sorted(grouped.items())
    ]


def same_english_card_across_marketplaces(
    *, identity_equal: bool, regional_variant_proven: bool
) -> bool:
    return bool(identity_equal and not regional_variant_proven)
