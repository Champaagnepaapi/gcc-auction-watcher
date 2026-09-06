from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Optional, Sequence

import v4_global_economic_confirmation as legacy
from v4_global_market_core import AUCTION_SNAPSHOT_LE5, FIXED_ASK


@dataclass(frozen=True)
class MarketplaceDecision:
    status: str
    would_notify: bool
    best_market: str = ""
    source_url: str = ""
    offer_all_in_eur: Optional[float] = None
    gcc_fair_eur: Optional[float] = None
    external_fair_eur: Optional[float] = None
    confirmed_fair_eur: Optional[float] = None
    discount_pct: Optional[float] = None
    market_ratio: Optional[float] = None
    external_provider: str = ""
    external_sales_count: int = 0
    valuation_basis: str = ""
    note: str = ""


def _best_actionable_offer(card: Mapping[str, object]):
    raw = card.get("offers")
    offers = raw if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)) else []
    candidates = []
    for offer in offers:
        if not isinstance(offer, Mapping):
            continue
        if offer.get("evidence_type") not in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}:
            continue
        try:
            all_in = float(offer.get("all_in_eur"))
        except (TypeError, ValueError):
            continue
        if all_in <= 0:
            continue
        candidates.append((all_in, offer))
    return min(candidates, key=lambda item: item[0]) if candidates else (None, None)


def _optional_positive(value: object) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def evaluate_marketplace_card(
    card: Mapping[str, object],
    *,
    ppt: legacy.ExternalAggregate,
    poketrace: legacy.ExternalAggregate,
    min_discount: float = legacy.DEFAULT_MIN_DISCOUNT,
) -> MarketplaceDecision:
    """Evaluate a marketplace offer against valuation-provider evidence only.

    GCC/Fanatics/COMC/Cardova/Magi (and future Mercari/SNKRDUNK/eBay active
    listings) are opportunity sources: their listing price is the candidate cost,
    never fair value. Historical GCC fair may remain attached to the report for
    diagnostics/Robot KB compatibility, but it cannot anchor, confirm, cap or
    conflict-block the economic decision.

    The current Global valuation family remains the strict external aggregate
    path (PPT/PokeTrace). PriceCharting is added to the V4 valuation-provider tree
    separately; Global PriceCharting wiring can extend this evaluator without
    changing the marketplace-role invariant defined here.
    """

    identity = legacy.identity_from_card(card)
    if identity is None or not identity.complete_for_exact_market or not identity.opportunity_language:
        return MarketplaceDecision("BLOCKED_IDENTITY", False, note="exact EN/JA identity required")

    all_in, offer = _best_actionable_offer(card)
    if offer is None or all_in is None:
        return MarketplaceDecision("NO_ACTIONABLE_ALL_IN_OFFER", False)

    external, selection_note = legacy.select_correlated_external(ppt, poketrace)
    diagnostic_gcc_fair = _optional_positive(card.get("fair_value_eur"))
    if external is None or external.fair_eur is None:
        status = (
            "MARKET_CONFLICT_BLOCKED"
            if selection_note.startswith("CORRELATED_PROVIDER_CONFLICT")
            else "NO_EXTERNAL_CONFIRMATION"
        )
        return MarketplaceDecision(
            status,
            False,
            best_market=str(offer.get("market") or ""),
            source_url=str(offer.get("source_url") or ""),
            offer_all_in_eur=round(all_in, 2),
            gcc_fair_eur=(
                round(diagnostic_gcc_fair, 2)
                if diagnostic_gcc_fair is not None
                else None
            ),
            valuation_basis="EXTERNAL_ONLY",
            note=selection_note,
        )

    confirmed_fair = float(external.fair_eur)
    discount = (confirmed_fair - all_in) / confirmed_fair * 100.0
    would_notify = discount + 1e-9 >= max(0.0, float(min_discount))
    return MarketplaceDecision(
        "MULTIMARKET_CONFIRMED" if would_notify else "NO_GLOBAL_EDGE",
        would_notify,
        best_market=str(offer.get("market") or ""),
        source_url=str(offer.get("source_url") or ""),
        offer_all_in_eur=round(all_in, 2),
        gcc_fair_eur=(
            round(diagnostic_gcc_fair, 2)
            if diagnostic_gcc_fair is not None
            else None
        ),
        external_fair_eur=round(confirmed_fair, 2),
        confirmed_fair_eur=round(confirmed_fair, 2),
        discount_pct=round(discount, 1),
        market_ratio=None,
        external_provider=external.provider,
        external_sales_count=external.sold_count,
        valuation_basis="EXTERNAL_ONLY",
        note=(
            f"{selection_note}; GCC history diagnostic-only"
            if diagnostic_gcc_fair is not None
            else selection_note
        ),
    )


def aggregate_from_payload(payload: object, *, provider: str) -> legacy.ExternalAggregate:
    if not isinstance(payload, Mapping):
        return legacy.ExternalAggregate(provider, "UNAVAILABLE")
    try:
        fair = float(payload.get("fair_eur")) if payload.get("fair_eur") is not None else None
    except (TypeError, ValueError):
        fair = None
    try:
        count = int(payload.get("sold_count") or payload.get("sales_count") or 0)
    except (TypeError, ValueError):
        count = 0
    strength = str(payload.get("evidence_strength") or "UNAVAILABLE")
    status = str(payload.get("status") or "UNAVAILABLE")
    return legacy.ExternalAggregate(
        provider=provider,
        status=status,
        fair_eur=fair,
        sold_count=count,
        evidence_strength=strength,
        note=str(payload.get("note") or ""),
    )


def decision_payload(decision: MarketplaceDecision) -> dict[str, object]:
    payload = asdict(decision)
    payload.update(
        {
            "external_family": legacy.EBAY_GRADED_AGGREGATE,
            "independent_market_increment": 1 if decision.external_provider else 0,
            "marketplace_listing_is_valuation": False,
            "gcc_history_economic_authority": False,
            "ask_is_sold": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
        }
    )
    return payload