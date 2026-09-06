from __future__ import annotations

"""Bounded exact-ASK fallback for recall-oriented manual review.

ASK evidence remains ASK. This lane never inserts a fake ComparableSale, never
labels an active listing as SOLD, and never changes the canonical strong-SOLD
arbitration result. It only emits a clearly-labelled manual-review notification
when GCC is materially below the *lowest exact* eBay BIN ask after a haircut.
"""

import os
from datetime import datetime
from email.header import Header
from typing import Optional

import watcher
import v4_exact_active_ask_position as asks


_STATE_KEY = "v4_exact_ask_fallback_review"
_SCHEMA_VERSION = 1
_ORIGINAL_PROCESS = None
_INSTALLED = False


def _max_cards() -> int:
    try:
        return max(0, min(8, int(os.getenv("V4_ASK_FALLBACK_MAX_CARDS_PER_RUN", "4"))))
    except ValueError:
        return 4


def _haircut() -> float:
    try:
        value = float(os.getenv("V4_ASK_FALLBACK_HAIRCUT_PCT", "10"))
    except ValueError:
        value = 10.0
    return max(0.0, min(35.0, value))


def _min_discount() -> float:
    try:
        value = float(os.getenv("V4_ASK_FALLBACK_MIN_DISCOUNT_PCT", "20"))
    except ValueError:
        value = 20.0
    return max(10.0, min(45.0, value))


def _key(lot: watcher.Lot) -> str:
    url = str(lot.url or "").strip().rstrip("/")
    return url or watcher.external_commercial_identity_key(lot)


def _already_sent(state: dict, lot: watcher.Lot) -> bool:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        return False
    entries = root.get("entries")
    return isinstance(entries, dict) and bool(entries.get(_key(lot)))


def _mark_sent(state: dict, lot: watcher.Lot, now: datetime, price: float, ask: float) -> None:
    root = state.get(_STATE_KEY)
    if not isinstance(root, dict) or root.get("schema_version") != _SCHEMA_VERSION:
        root = {"schema_version": _SCHEMA_VERSION, "entries": {}}
        state[_STATE_KEY] = root
    entries = root.setdefault("entries", {})
    entries[_key(lot)] = {
        "notified_at": now.isoformat(),
        "gcc_price": round(price, 2),
        "ask_price": round(ask, 2),
    }


def _priority(candidate: watcher.ValuationCandidate) -> tuple[int, float, float]:
    lot = candidate.lot
    if lot.source_type == "auction":
        minutes = float(lot.minutes_to_end if lot.minutes_to_end is not None else 9999)
        # ending auctions first; ≤12 min is the highest-value review window
        return (0 if minutes <= 12 else 1, minutes, float(lot.current_price or 0.0))
    return (2, float(lot.current_price or 0.0), 0.0)


def _notify_review(
    lot: watcher.Lot,
    evidence: asks.ActiveAskEvidence,
    *,
    reference: float,
    discount_pct: float,
) -> None:
    grade = watcher.format_grade_label(lot.grader, lot.grade) or "grade inconnu"
    timing = ""
    if lot.source_type == "auction":
        timing = (
            f"Fin: {lot.minutes_to_end} min\n"
            if lot.minutes_to_end is not None
            else f"Fin: {lot.end_text or 'inconnue'}\n"
        )
    msg = (
        "GCC REVIEW — ASK EXACT (PAS SOLD)\n\n"
        f"{lot.title}\n"
        f"{grade}\n"
        f"Prix GCC: {float(lot.current_price or 0):.2f} €\n"
        f"ASK eBay exact le moins cher: {evidence.price:.2f} €\n"
        f"Référence prudente après haircut {_haircut():.0f}%: {reference:.2f} €\n"
        f"Décote vs référence ASK: {discount_pct:.1f}%\n"
        f"{timing}"
        "Signal secondaire: ASK compatible, pas une vente. Vérifier manuellement avant décision.\n\n"
        f"ASK: {evidence.url}\n"
        f"GCC: {lot.url}"
    )
    watcher.log("*** NOTIFICATION: ASK EXACT MANUAL REVIEW ***")
    print(msg, flush=True)
    if not watcher.NTFY_TOPIC:
        return
    try:
        watcher.requests.post(
            f"{watcher.NTFY_SERVER}/{watcher.NTFY_TOPIC}",
            data=msg.encode("utf-8"),
            headers={
                "Title": Header("GCC REVIEW — ASK EXACT", "utf-8").encode(),
                "Priority": "4",
                "Tags": "mag,card_index",
            },
            timeout=10,
        ).raise_for_status()
    except Exception as exc:
        watcher.log(f"ASK fallback ntfy échouée: {type(exc).__name__}")


def process_with_exact_ask_fallback(
    page,
    candidates,
    state,
    budgets,
    diagnostics,
    run_now,
):
    opportunities = _ORIGINAL_PROCESS(
        page, candidates, state, budgets, diagnostics, run_now
    )
    if _max_cards() <= 0:
        return opportunities

    already_actionable = {str(op.lot.url or "") for op in opportunities}
    lookups = 0
    for candidate in sorted(candidates, key=_priority):
        lot = candidate.lot
        if str(lot.url or "") in already_actionable:
            continue
        price = float(lot.current_price or 0.0)
        if price <= 0 or not watcher.commercial_identity_is_sufficient(lot):
            continue
        if _already_sent(state, lot):
            continue

        evidence: Optional[asks.ActiveAskEvidence] = asks._cached_active_ask(
            state, lot, run_now
        )
        if evidence is None:
            if lookups >= _max_cards():
                continue
            lookups += 1
            evidence = asks.scrape_lowest_exact_ebay_ask(page, lot)
            if evidence is not None:
                asks._store_active_ask(state, lot, evidence, run_now)
        if evidence is None or not evidence.gcc_is_cheapest:
            continue

        reference = evidence.price * (1.0 - _haircut() / 100.0)
        if reference <= 0:
            continue
        discount_pct = (reference - price) / reference * 100.0
        if discount_pct < _min_discount():
            continue

        _notify_review(
            lot,
            evidence,
            reference=reference,
            discount_pct=discount_pct,
        )
        _mark_sent(state, lot, run_now, price, evidence.price)

    watcher.log(
        "ASK fallback review: "
        f"network_lookups={lookups}/{_max_cards()} | haircut={_haircut():.0f}% | "
        f"min_discount={_min_discount():.0f}%"
    )
    return opportunities


def install_v4_ask_fallback_review() -> None:
    global _ORIGINAL_PROCESS, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_PROCESS = watcher.process_external_market_candidates
    watcher.process_external_market_candidates = process_with_exact_ask_fallback
    _INSTALLED = True
