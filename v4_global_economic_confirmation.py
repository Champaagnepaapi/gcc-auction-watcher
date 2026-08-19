"""Economic confirmation gate for Global Multi-Vault opportunities.

The Global lane may discover an exact ASK on GCC/Fanatics/magi/COMC/Cardova, but
it must not notify from that ASK alone. This module requires a compatible graded
market aggregate from the existing PokeTrace/eBay family or from the strict PPT
adapter before a candidate can become notification-eligible.

PPT and PokeTrace/eBay are correlated and count as one provider family. They are
never treated as two independent confirmations. ASK/current auction evidence is
never used to establish fair value.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional, Sequence

import v4_canonical_multimarket as multimarket
import watcher
from v4_global_market_core import (
    AUCTION_SNAPSHOT_LE5,
    EBAY_GRADED_AGGREGATE,
    FIXED_ASK,
    CommercialIdentity,
)
from v4_global_ppt_confirmation import PptSnapshot
from v4_multimarket_safety import install_multimarket_safety_hardening
from v4_poketrace_market_retrieval import install_v4_poketrace_market_retrieval
from v4_tcgdex_exact_coordinate_recovery import install_v4_tcgdex_exact_coordinate_recovery
from v4_tcgdex_generalized_coordinate_recovery import (
    install_v4_tcgdex_generalized_coordinate_recovery,
)
from v4_tcgdex_japanese_set_aliases import install_v4_tcgdex_japanese_set_aliases
from v4_tcgdex_run1054_set_aliases import install_v4_tcgdex_run1054_set_aliases
from v4_tcgdex_source_pinned_finish import install_v4_tcgdex_source_pinned_finish
from v4_tcgdex_two_of_three_backport import install_v4_tcgdex_two_of_three_backport
from v4_tcgdex_unique_coordinate_fallback import (
    install_v4_tcgdex_unique_coordinate_fallback,
)

EXTERNAL_MIN_SALES = 3
EXTERNAL_CONFIRM_RATIO = 1.25
CORRELATED_PROVIDER_CONFLICT_RATIO = 1.35
RECENT_DAYS = 90
DEFAULT_MIN_DISCOUNT = 30.0

_GLOBAL_EXTERNAL_STACK_INSTALLED = False


@dataclass(frozen=True)
class ExternalAggregate:
    provider: str
    status: str
    fair_eur: Optional[float] = None
    sold_count: int = 0
    last_sale_at: Optional[datetime] = None
    evidence_strength: str = "UNAVAILABLE"
    correlation_group: str = EBAY_GRADED_AGGREGATE
    note: str = ""

    @property
    def usable_center(self) -> bool:
        return (
            self.status == "MATCHED"
            and self.fair_eur is not None
            and self.fair_eur > 0
            and self.sold_count >= EXTERNAL_MIN_SALES
        )


@dataclass(frozen=True)
class ConfirmationDecision:
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
    correlation_group: str = EBAY_GRADED_AGGREGATE
    note: str = ""


def install_global_external_market_stack() -> None:
    """Reuse the exact V4 production catalog/provider stack for Global confirms.

    The first recovery live accidentally called the base TCGdex resolver directly,
    bypassing the deterministic V4 wrappers already merged on main (#119→#123 and
    subsequent source-pinned hardening). Install those proven wrappers in the same
    production order instead of reimplementing a second Global resolver.

    This is identity/provider plumbing only: no valuation, notification or
    transaction capability is enabled here.
    """

    global _GLOBAL_EXTERNAL_STACK_INSTALLED
    if _GLOBAL_EXTERNAL_STACK_INSTALLED:
        return

    install_v4_tcgdex_exact_coordinate_recovery()
    install_v4_tcgdex_run1054_set_aliases()
    install_v4_tcgdex_japanese_set_aliases()
    install_v4_tcgdex_generalized_coordinate_recovery()
    install_v4_tcgdex_two_of_three_backport()
    install_v4_tcgdex_unique_coordinate_fallback()
    install_v4_tcgdex_source_pinned_finish()

    # PokeTrace remains market-only after TCGdex identity. Reuse the production
    # structured EN/JA retrieval contract plus the fail-closed provider identity /
    # microvariant matcher; the process/notification wrappers are inert here.
    install_v4_poketrace_market_retrieval()
    install_multimarket_safety_hardening()
    _GLOBAL_EXTERNAL_STACK_INSTALLED = True


def _norm_language(value: object) -> str:
    text = str(value or "").strip().casefold()
    return {
        "japanese": "ja",
        "japonais": "ja",
        "jp": "ja",
        "english": "en",
        "anglais": "en",
    }.get(text, text)


def identity_from_card(card: Mapping[str, object]) -> Optional[CommercialIdentity]:
    raw = card.get("identity")
    if not isinstance(raw, Mapping):
        return None
    try:
        return CommercialIdentity(**dict(raw))
    except (TypeError, ValueError):
        return None


def _parse_observed_at(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _lot_for_identity(identity: CommercialIdentity) -> watcher.Lot:
    language = _norm_language(identity.language)
    language_label = (
        "Japanese" if language == "ja" else "English" if language == "en" else identity.language
    )
    sensitive = " ".join(
        value for value in (identity.edition, identity.finish, identity.variant) if value
    ).strip()
    clean_title = " ".join(
        value
        for value in (
            identity.name,
            identity.set_name,
            identity.number,
            language_label,
            identity.grader,
            identity.grade,
            sensitive,
        )
        if value
    )
    return watcher.Lot(
        url="https://global-confirmation.invalid/read-only",
        title=clean_title,
        current_price=1.0,
        source_type="FIXED_PRICE",
        grader=identity.grader,
        grade=identity.grade,
        listing_text=clean_title,
        card_set=identity.set_name,
        card_number=identity.number,
        language=language_label,
        variant=sensitive,
    )


def resolve_global_canonical(
    identity: CommercialIdentity,
) -> tuple[watcher.Lot, multimarket.CanonicalCard]:
    """Resolve the exact TCGdex macro identity used by every external bridge.

    Global discovery already proved the commercial listing identity. This extra
    resolver is not allowed to relax it; it only supplies real TCGdex card/set
    coordinates to provider adapters. The live runner installs the same layered
    deterministic TCGdex stack as V4 production before calling this function.
    A non-EXACT result remains fail-closed.
    """
    lot = _lot_for_identity(identity)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return lot, multimarket.CanonicalCard(
            "NO_MATCH", reason="GLOBAL_EXTERNAL_IDENTITY_INCOMPLETE"
        )
    try:
        canonical = multimarket.resolve_tcgdex_card(lot)
    except Exception as error:
        return lot, multimarket.CanonicalCard(
            "ERROR", reason=f"GLOBAL_TCGDEX_ERROR:{type(error).__name__}"
        )
    if canonical.status != "EXACT":
        return lot, canonical
    if canonical.language_code != _norm_language(identity.language):
        return lot, multimarket.CanonicalCard(
            "AMBIGUOUS", reason="GLOBAL_TCGDEX_LANGUAGE_CONFLICT"
        )
    return lot, canonical


def ppt_external(snapshot: PptSnapshot, *, now: datetime) -> ExternalAggregate:
    recent = (
        snapshot.last_sale_at is not None
        and snapshot.last_sale_at >= now - timedelta(days=RECENT_DAYS)
    )
    if snapshot.status != "MATCHED":
        return ExternalAggregate("PokemonPriceTracker", snapshot.status, note=snapshot.note)
    if not recent:
        return ExternalAggregate(
            "PokemonPriceTracker",
            "STALE_OR_UNDATED",
            snapshot.fair_eur,
            snapshot.sales_count,
            snapshot.last_sale_at,
            "INSUFFICIENT",
            note="PPT aggregate lacks a recent <=90d last sale",
        )
    return ExternalAggregate(
        "PokemonPriceTracker",
        "MATCHED",
        snapshot.fair_eur,
        snapshot.sales_count,
        snapshot.last_sale_at,
        "STRONG" if snapshot.sales_count >= EXTERNAL_MIN_SALES else "INSUFFICIENT",
        note=snapshot.note,
    )


def fetch_poketrace_external(
    identity: CommercialIdentity,
    *,
    budget: multimarket.RequestBudget,
    now: datetime,
    canonical: Optional[multimarket.CanonicalCard] = None,
    lot: Optional[watcher.Lot] = None,
) -> ExternalAggregate:
    """Reuse the production V4 PokeTrace exact gate with a real TCGdex identity."""
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return ExternalAggregate("PokeTrace/eBay SOLD", "BLOCKED_IDENTITY")

    if lot is None or canonical is None:
        lot, canonical = resolve_global_canonical(identity)
    if canonical.status != "EXACT":
        return ExternalAggregate(
            "PokeTrace/eBay SOLD",
            f"TCGDEX_{canonical.status or 'UNRESOLVED'}",
            note=canonical.reason or "exact TCGdex canonical unavailable",
        )

    evidence = multimarket._poketrace_evidence(lot, canonical, budget, now)
    estimate = evidence.estimate
    if (
        evidence.status == watcher.EXTERNAL_MATCHED
        and evidence.strength == watcher.EVIDENCE_STRONG
        and estimate is not None
        and estimate.central > 0
        and int(estimate.exact_grade_count or 0) >= EXTERNAL_MIN_SALES
    ):
        return ExternalAggregate(
            "PokeTrace/eBay SOLD",
            "MATCHED",
            round(float(estimate.central), 2),
            int(estimate.exact_grade_count or 0),
            None,
            evidence.strength,
            note=(evidence.note or "") + "; TCGdex canonical exact; corroboration only: no explicit last-sale timestamp",
        )
    return ExternalAggregate(
        "PokeTrace/eBay SOLD",
        evidence.status or "UNAVAILABLE",
        evidence_strength=evidence.strength or "UNAVAILABLE",
        note=(evidence.note or "") + "; TCGdex canonical exact",
    )


def select_correlated_external(
    ppt: ExternalAggregate,
    poketrace: ExternalAggregate,
) -> tuple[Optional[ExternalAggregate], str]:
    """Choose one representative of the correlated eBay aggregate family."""
    ppt_ok = ppt.usable_center and ppt.evidence_strength == "STRONG"
    pt_ok = poketrace.usable_center and poketrace.evidence_strength == watcher.EVIDENCE_STRONG
    if ppt_ok and pt_ok:
        ratio = max(float(ppt.fair_eur), float(poketrace.fair_eur)) / min(
            float(ppt.fair_eur), float(poketrace.fair_eur)
        )
        if ratio > CORRELATED_PROVIDER_CONFLICT_RATIO:
            return None, f"CORRELATED_PROVIDER_CONFLICT:{ratio:.3f}"
        # PPT has a proved recent last-sale timestamp; PokeTrace is retained as
        # same-family corroboration but never counted as a second market.
        return ppt, f"PPT_PRIMARY_POKETRACE_CORRELATED:{ratio:.3f}"
    if ppt_ok:
        return ppt, "PPT_RECENT_PRIMARY"
    if pt_ok:
        return poketrace, "POKETRACE_CORROBORATION_ONLY"
    return None, "NO_USABLE_EXTERNAL_AGGREGATE"


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


def evaluate_card(
    card: Mapping[str, object],
    *,
    ppt: ExternalAggregate,
    poketrace: ExternalAggregate,
    min_discount: float = DEFAULT_MIN_DISCOUNT,
) -> ConfirmationDecision:
    identity = identity_from_card(card)
    if identity is None or not identity.complete_for_exact_market or not identity.opportunity_language:
        return ConfirmationDecision("BLOCKED_IDENTITY", False, note="exact EN/JA identity required")
    try:
        gcc_fair = float(card.get("fair_value_eur"))
    except (TypeError, ValueError):
        return ConfirmationDecision("BLOCKED_FAIR_VALUE", False)
    if gcc_fair <= 0:
        return ConfirmationDecision("BLOCKED_FAIR_VALUE", False)

    all_in, offer = _best_actionable_offer(card)
    if offer is None or all_in is None:
        return ConfirmationDecision(
            "NO_ACTIONABLE_ALL_IN_OFFER", False, gcc_fair_eur=round(gcc_fair, 2)
        )

    external, selection_note = select_correlated_external(ppt, poketrace)
    if external is None or external.fair_eur is None:
        status = "MARKET_CONFLICT_BLOCKED" if selection_note.startswith("CORRELATED_PROVIDER_CONFLICT") else "NO_EXTERNAL_CONFIRMATION"
        return ConfirmationDecision(
            status,
            False,
            best_market=str(offer.get("market") or ""),
            source_url=str(offer.get("source_url") or ""),
            offer_all_in_eur=round(all_in, 2),
            gcc_fair_eur=round(gcc_fair, 2),
            note=selection_note,
        )

    ext = float(external.fair_eur)
    ratio = max(gcc_fair, ext) / min(gcc_fair, ext)
    if ratio > EXTERNAL_CONFIRM_RATIO:
        return ConfirmationDecision(
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
            note=f"GCC/external ratio exceeds {EXTERNAL_CONFIRM_RATIO:.2f}; {selection_note}",
        )

    # Conservative confirmation: never raise the GCC fair value from the
    # external aggregate. The lower compatible center is the notification basis.
    confirmed_fair = min(gcc_fair, ext)
    discount = (confirmed_fair - all_in) / confirmed_fair * 100.0
    would_notify = discount + 1e-9 >= max(0.0, float(min_discount))
    return ConfirmationDecision(
        "MULTIMARKET_CONFIRMED" if would_notify else "NO_GLOBAL_EDGE",
        would_notify,
        best_market=str(offer.get("market") or ""),
        source_url=str(offer.get("source_url") or ""),
        offer_all_in_eur=round(all_in, 2),
        gcc_fair_eur=round(gcc_fair, 2),
        external_fair_eur=round(ext, 2),
        confirmed_fair_eur=round(confirmed_fair, 2),
        discount_pct=round(discount, 1),
        market_ratio=round(ratio, 3),
        external_provider=external.provider,
        external_sales_count=external.sold_count,
        note=selection_note,
    )


def decision_payload(decision: ConfirmationDecision) -> dict[str, object]:
    payload = asdict(decision)
    payload.update(
        {
            "external_family": EBAY_GRADED_AGGREGATE,
            "independent_market_increment": 1 if decision.external_provider else 0,
            "ask_is_sold": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
        }
    )
    return payload
