from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping, Optional, Sequence

import v4_global_economic_confirmation as legacy
from v4_global_market_core import AUCTION_SNAPSHOT_LE5, FIXED_ASK


PRICECHARTING_GUIDE_STRENGTH = "GUIDE_STRONG"
PRICECHARTING_MIN_DISCOUNT_PCT = 40.0


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
    valuation_evidence_type: str = ""
    required_discount_pct: Optional[float] = None
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


def _usable_pricecharting_guide(
    evidence: Optional[legacy.ExternalAggregate],
) -> bool:
    return bool(
        evidence is not None
        and evidence.status == "MATCHED"
        and evidence.fair_eur is not None
        and evidence.fair_eur > 0
        and evidence.evidence_strength == PRICECHARTING_GUIDE_STRENGTH
    )


def _select_valuation_provider(
    ppt: legacy.ExternalAggregate,
    poketrace: legacy.ExternalAggregate,
    pricecharting: Optional[legacy.ExternalAggregate],
) -> tuple[Optional[legacy.ExternalAggregate], str, str, float]:
    """Prefer SOLD-derived aggregates; use PriceCharting only as a guide fallback."""

    external, selection_note = legacy.select_correlated_external(ppt, poketrace)
    if external is not None:
        return external, selection_note, "SOLD_AGGREGATE", legacy.DEFAULT_MIN_DISCOUNT

    # A material disagreement between stronger SOLD-derived providers remains
    # blocking. A weaker guide must never arbitrate away a real market conflict.
    if selection_note.startswith("CORRELATED_PROVIDER_CONFLICT"):
        return None, selection_note, "", legacy.DEFAULT_MIN_DISCOUNT

    if _usable_pricecharting_guide(pricecharting):
        return (
            pricecharting,
            "PRICECHARTING_GUIDE_FALLBACK",
            "PRICE_GUIDE",
            PRICECHARTING_MIN_DISCOUNT_PCT,
        )
    return None, selection_note, "", legacy.DEFAULT_MIN_DISCOUNT


def evaluate_marketplace_card(
    card: Mapping[str, object],
    *,
    ppt: legacy.ExternalAggregate,
    poketrace: legacy.ExternalAggregate,
    pricecharting: Optional[legacy.ExternalAggregate] = None,
    min_discount: float = legacy.DEFAULT_MIN_DISCOUNT,
) -> MarketplaceDecision:
    """Evaluate one marketplace opportunity against valuation providers only.

    GCC/Fanatics/COMC/Cardova/Magi and future Mercari/SNKRDUNK/eBay active
    listings are opportunity sources. Their listing prices are candidate costs,
    never fair value and never confirmation evidence for another marketplace.

    Historical GCC fair may remain attached to the report for diagnostics/Robot
    KB compatibility, but it cannot create, anchor, confirm, cap or conflict-block
    an economic decision.

    Valuation priority here is SOLD-derived PPT/PokeTrace aggregate evidence,
    then an exact PSA 10 PriceCharting guide fallback. PriceCharting is explicitly
    a GUIDE, not an item-level SOLD row, and therefore requires the more
    conservative 40% minimum discount when it is the sole valuation source.
    """

    identity = legacy.identity_from_card(card)
    if identity is None or not identity.complete_for_exact_market or not identity.opportunity_language:
        return MarketplaceDecision("BLOCKED_IDENTITY", False, note="exact EN/JA identity required")

    all_in, offer = _best_actionable_offer(card)
    if offer is None or all_in is None:
        return MarketplaceDecision("NO_ACTIONABLE_ALL_IN_OFFER", False)

    diagnostic_gcc_fair = _optional_positive(card.get("fair_value_eur"))
    external, selection_note, evidence_type, source_floor = _select_valuation_provider(
        ppt, poketrace, pricecharting
    )
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
            valuation_evidence_type=evidence_type,
            required_discount_pct=max(float(min_discount), float(source_floor)),
            note=selection_note,
        )

    confirmed_fair = float(external.fair_eur)
    required_discount = max(float(min_discount), float(source_floor))
    discount = (confirmed_fair - all_in) / confirmed_fair * 100.0
    would_notify = discount + 1e-9 >= required_discount
    valuation_basis = (
        "PRICECHARTING_GUIDE_ONLY"
        if evidence_type == "PRICE_GUIDE"
        else "EXTERNAL_ONLY"
    )
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
        valuation_basis=valuation_basis,
        valuation_evidence_type=evidence_type,
        required_discount_pct=round(required_discount, 1),
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
            "marketplace_sources_are_opportunity_only": True,
            "gcc_history_economic_authority": False,
            "ask_is_sold": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
        }
    )
    return payload
