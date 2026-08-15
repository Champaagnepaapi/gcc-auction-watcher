"""High-ROI V4 efficiency signals without changing economic decisions.

This module deliberately does NOT implement an expected-profit score and does
NOT make V4 depend on Robot KB/Neon. It adds two low-risk optimisations:

* preserve GCC fixed-listing ``createdAt`` as diagnostic metadata;
* use robust same-card/same-grader/same-grade SOLD momentum + listing age to
  prioritise scarce external checks and annotate an opportunity that V4 already
  selected.

No signal here can create an opportunity, alter fair value/max_recommended,
relax identity matching, or perform a transaction.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Optional

import watcher
import v4_smart_external_priority as smart_priority


@dataclass(frozen=True)
class StaleMomentumSignal:
    recent_median: float
    baseline_median: float
    recent_count: int
    baseline_count: int
    momentum_pct: float
    listing_age_days: Optional[float]
    price_gap_pct: float
    stale_listing: bool
    actionable_edge: bool


_ORIGINAL_FIXED_RESULT_TO_LOT = None
_ORIGINAL_PROCESS = None
_ORIGINAL_NOTIFY = None
_ORIGINAL_PRIORITY_SCORE = None
_INSTALLED = False


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def parse_gcc_created_at(value: object) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _aware(parsed)


def _fixed_result_with_created_at(result, item_url, coverage, **kwargs):
    lot = _ORIGINAL_FIXED_RESULT_TO_LOT(result, item_url, coverage, **kwargs)
    if lot is not None and isinstance(result, dict):
        created_at = parse_gcc_created_at(result.get("createdAt"))
        if created_at is not None:
            # Dataclass Lot is intentionally not widened: this is diagnostic
            # metadata and survives the in-place detail inspection wrappers.
            setattr(lot, "gcc_created_at", created_at)
    return lot


def listing_age_days(lot: watcher.Lot, now: datetime) -> Optional[float]:
    created_at = _aware(getattr(lot, "gcc_created_at", None))
    current = _aware(now) or datetime.now(timezone.utc)
    if created_at is None or created_at > current:
        return None
    return max(0.0, (current - created_at).total_seconds() / 86400.0)


def _target_exact_sales(candidate) -> list[watcher.ComparableSale]:
    lot = candidate.lot
    target_grade = watcher._target_grade(lot)
    target_grader = (lot.grader or "").strip().upper()
    if target_grade is None or not target_grader:
        return []
    result = []
    for sale in getattr(candidate.gcc, "sales", []) or []:
        if not isinstance(sale, watcher.ComparableSale):
            continue
        if not sale.exact_card or sale.price <= 0 or sale.sold_at is None:
            continue
        if sale.grade_qualifier:
            continue
        if (sale.grader or "").strip().upper() != target_grader:
            continue
        if sale.grade is None or abs(float(sale.grade) - float(target_grade)) > 1e-9:
            continue
        result.append(sale)
    return result


def market_momentum_signal(candidate, now: Optional[datetime] = None) -> Optional[StaleMomentumSignal]:
    """Return a conservative SOLD-only momentum signal for one exact slab tier.

    Recent and baseline windows never use asks/live auctions. The signal is
    diagnostic and is intentionally unavailable when either window is sparse.
    """
    current = _aware(now) or datetime.now(timezone.utc)
    recent_days = max(30, _env_int("V4_ROI_MOMENTUM_RECENT_DAYS", 90))
    baseline_days = max(recent_days + 30, _env_int("V4_ROI_MOMENTUM_BASELINE_DAYS", 365))
    min_recent = max(2, _env_int("V4_ROI_MOMENTUM_MIN_RECENT_SALES", 2))
    min_baseline = max(2, _env_int("V4_ROI_MOMENTUM_MIN_BASELINE_SALES", 2))

    recent_prices: list[float] = []
    baseline_prices: list[float] = []
    for sale in _target_exact_sales(candidate):
        sold_at = _aware(sale.sold_at)
        if sold_at is None or sold_at > current:
            continue
        age_days = (current - sold_at).total_seconds() / 86400.0
        if age_days <= recent_days:
            recent_prices.append(float(sale.price))
        elif age_days <= baseline_days:
            baseline_prices.append(float(sale.price))

    if len(recent_prices) < min_recent or len(baseline_prices) < min_baseline:
        return None

    recent_median = median(recent_prices)
    baseline_median = median(baseline_prices)
    if recent_median <= 0 or baseline_median <= 0:
        return None

    momentum_pct = (recent_median / baseline_median - 1.0) * 100.0
    try:
        gcc_price = float(candidate.lot.current_price)
    except (TypeError, ValueError):
        gcc_price = 0.0
    price_gap_pct = (
        max(0.0, (recent_median - gcc_price) / recent_median * 100.0)
        if gcc_price > 0 else 0.0
    )
    age = listing_age_days(candidate.lot, current)
    stale_days = max(1.0, _env_float("V4_ROI_STALE_LISTING_DAYS", 14.0))
    stale = age is not None and age >= stale_days
    min_momentum = _env_float("V4_ROI_MIN_MOMENTUM_PCT", 15.0)
    min_gap = _env_float("V4_ROI_MIN_STALE_GAP_PCT", 15.0)
    edge = bool(stale and momentum_pct >= min_momentum and price_gap_pct >= min_gap)

    return StaleMomentumSignal(
        recent_median=round(recent_median, 2),
        baseline_median=round(baseline_median, 2),
        recent_count=len(recent_prices),
        baseline_count=len(baseline_prices),
        momentum_pct=round(momentum_pct, 1),
        listing_age_days=(round(age, 1) if age is not None else None),
        price_gap_pct=round(price_gap_pct, 1),
        stale_listing=stale,
        actionable_edge=edge,
    )


def _priority_score_with_momentum(candidate) -> float:
    base = float(_ORIGINAL_PRIORITY_SCORE(candidate))
    if candidate.lot.source_type != "fixed":
        return base
    signal = market_momentum_signal(candidate)
    if signal is None or signal.momentum_pct <= 0:
        return base

    # Information-value bonus only. Existing queue category remains dominant in
    # v4_smart_external_priority and economics are untouched.
    bonus = min(20.0, signal.momentum_pct / 2.0)
    if signal.actionable_edge:
        bonus += 20.0
    return round(base + bonus, 4)


def _process_with_stale_momentum(page, candidates, state, budgets, diagnostics, run_now):
    opportunities = _ORIGINAL_PROCESS(page, candidates, state, budgets, diagnostics, run_now)
    by_url = {candidate.lot.url: candidate for candidate in candidates}
    for op in opportunities:
        if op.lot.source_type != "fixed":
            continue
        candidate = by_url.get(op.lot.url)
        if candidate is None:
            continue
        signal = market_momentum_signal(candidate, run_now)
        if signal is not None and signal.actionable_edge:
            setattr(op, "stale_momentum_signal", signal)
            watcher.log(
                "Stale momentum diagnostic: "
                f"+{signal.momentum_pct:.1f}% SOLD momentum, "
                f"listing {signal.listing_age_days:.1f}d, "
                f"GCC {signal.price_gap_pct:.1f}% below recent exact median | "
                f"{op.lot.title}"
            )
    return opportunities


def _momentum_block(op: watcher.Opportunity) -> str:
    signal = getattr(op, "stale_momentum_signal", None)
    if not isinstance(signal, StaleMomentumSignal) or not signal.actionable_edge:
        return ""
    age_text = (
        f"{signal.listing_age_days:.1f} j"
        if signal.listing_age_days is not None else "inconnue"
    )
    return (
        "STALE LISTING + MOMENTUM — SIGNAL DIAGNOSTIQUE\n"
        f"Ancienneté annonce GCC : {age_text}\n"
        f"SOLD exacts récents : médiane {signal.recent_median:.2f} € "
        f"(n={signal.recent_count})\n"
        f"SOLD exacts antérieurs : médiane {signal.baseline_median:.2f} € "
        f"(n={signal.baseline_count})\n"
        f"Momentum : +{signal.momentum_pct:.1f}% | GCC sous médiane récente : "
        f"{signal.price_gap_pct:.1f}%\n"
        "Diagnostic seulement — ne modifie ni fair value ni prix max conseillé."
    )


def _inject_before_listing_url(data: object, block: str, listing_url: str) -> object:
    if not block:
        return data
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return data
        rewritten = _inject_before_listing_url(text, block, listing_url)
        return rewritten.encode("utf-8") if isinstance(rewritten, str) else data
    if not isinstance(data, str):
        return data
    marker = listing_url if listing_url and listing_url in data else ""
    if marker:
        return data.replace(marker, block + "\n\n" + marker, 1)
    return data.rstrip() + "\n\n" + block


def _notify_with_stale_momentum(op: watcher.Opportunity, decision: watcher.NotificationDecision) -> None:
    block = _momentum_block(op)
    if not block or not watcher.NTFY_TOPIC:
        return _ORIGINAL_NOTIFY(op, decision)
    original_post = watcher.requests.post

    def post_with_signal(url, *args, **kwargs):
        kwargs["data"] = _inject_before_listing_url(
            kwargs.get("data"), block, op.lot.url
        )
        return original_post(url, *args, **kwargs)

    watcher.requests.post = post_with_signal
    try:
        return _ORIGINAL_NOTIFY(op, decision)
    finally:
        watcher.requests.post = original_post


def install_v4_roi_efficiency() -> None:
    global _ORIGINAL_FIXED_RESULT_TO_LOT, _ORIGINAL_PROCESS, _ORIGINAL_NOTIFY
    global _ORIGINAL_PRIORITY_SCORE, _INSTALLED
    if _INSTALLED:
        return

    _ORIGINAL_FIXED_RESULT_TO_LOT = watcher._gcc_fixed_result_to_lot
    _ORIGINAL_PROCESS = watcher.process_external_market_candidates
    _ORIGINAL_NOTIFY = watcher.notify
    _ORIGINAL_PRIORITY_SCORE = smart_priority.external_priority_score

    watcher._gcc_fixed_result_to_lot = _fixed_result_with_created_at
    watcher.process_external_market_candidates = _process_with_stale_momentum
    watcher.notify = _notify_with_stale_momentum
    smart_priority.external_priority_score = _priority_score_with_momentum
    _INSTALLED = True

    watcher.log(
        "ROI efficiency: stale-listing + exact SOLD momentum diagnostics enabled; "
        "no expected-profit score, no economic decision changes"
    )
