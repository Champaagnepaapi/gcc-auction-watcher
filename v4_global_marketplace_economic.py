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
    """Marketplace-first valuation.

    GCC SOLD fair is optional. When present it remains a conservative independent
    anchor and conflicts can block. When absent, a strong exact external aggregate
    (PPT/PokeTrace correlation family, >=3 sales) may establish the fair value on
    its own. This implements the project rule that strong external evidence can
    rescue listings with weak/absent GCC history.
    """

    identity = legacy.identity_from_card(card)
    if identity is None or not identity.complete_for_exact_market or not identity.opportunity_language:
        return MarketplaceDecision("BLOCKED_IDENTITY", False, note="exact EN/JA identity required")

    all_in, offer = _best_actionable_offer(card)
    if offer is None or all_in is None:
        return MarketplaceDecision("NO_ACTIONABLE_ALL_IN_OFFER", False)

    external, selection_note = legacy.select_correlated_external(ppt, poketrace)
    gcc_fair = _optional_positive(card.get("fair_value_eur"))
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
            gcc_fair_eur=round(gcc_fair, 2) if gcc_fair is not None else None,
            note=selection_note,
        )

    ext = float(external.fair_eur)
    ratio = None
    if gcc_fair is not None:
        ratio = max(gcc_fair, ext) / min(gcc_fair, ext)
        if ratio > legacy.EXTERNAL_CONFIRM_RATIO:
            return MarketplaceDecision(
                "MARKET_CONFLICT_BLOCKED",
                False,
                best_market=str(offer.get("market") or ""),
                source_url=str(offer.get("source_url") or ""),
                offer_all_in_eur=round(all_in, 2),
                gcc_fair_eur=round(gcc_fair, 2),
                external_fair_eur=round(ext, 2),
                market_ratio=round(ratio, 3),
                external_provider=external.provider,
                external_sales_count=external.sold_count,
                valuation_basis="GCC_PLUS_EXTERNAL",
                note=f"GCC/external ratio exceeds {legacy.EXTERNAL_CONFIRM_RATIO:.2f}; {selection_note}",
            )
        confirmed_fair = min(gcc_fair, ext)
        valuation_basis = "GCC_PLUS_EXTERNAL"
    else:
        confirmed_fair = ext
        valuation_basis = "EXTERNAL_ONLY"

    discount = (confirmed_fair - all_in) / confirmed_fair * 100.0
    would_notify = discount + 1e-9 >= max(0.0, float(min_discount))
    return MarketplaceDecision(
        "MULTIMARKET_CONFIRMED" if would_notify else "NO_GLOBAL_EDGE",
        would_notify,
        best_market=str(offer.get("market") or ""),
        source_url=str(offer.get("source_url") or ""),
        offer_all_in_eur=round(all_in, 2),
        gcc_fair_eur=round(gcc_fair, 2) if gcc_fair is not None else None,
        external_fair_eur=round(ext, 2),
        confirmed_fair_eur=round(confirmed_fair, 2),
        discount_pct=round(discount, 1),
        market_ratio=round(ratio, 3) if ratio is not None else None,
        external_provider=external.provider,
        external_sales_count=external.sold_count,
        valuation_basis=valuation_basis,
        note=selection_note,
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
            "ask_is_sold": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
        }
    )
    return payload
