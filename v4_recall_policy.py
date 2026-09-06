from __future__ import annotations

"""Recall-first V4 policy without weakening commercial identity.

This policy intentionally changes *economic sensitivity*, not truth semantics:
- exact card/set/number/language/variant gates remain owned by the canonical pipeline;
- SOLD/ASK/live-auction meanings stay distinct;
- cross-grader evidence is never relabelled as an exact same-grader sale;
- no purchase, bid, checkout or payment action is introduced.

The user reviews notifications manually, so the production objective is to reduce
false negatives while keeping uncertainty visible in the required discount.
"""

import os
from typing import Optional

import watcher
import v4_canonical_multimarket as multimarket


# PSA does issue numeric grades below 8. Keep the already-established 8.5
# support, allow lower numeric/half grades that are explicitly present on the
# listing, and preserve the canonical ban on synthesising a PSA 9.5 tier.
PSA_RECALL_GRADES = frozenset(
    grade / 2.0 for grade in range(2, 19)
) | frozenset({10.0})
PSA_RECALL_GRADES = frozenset(
    grade for grade in PSA_RECALL_GRADES if grade != 9.5
)

_INSTALLED = False
_FINAL_HOOKS_INSTALLED = False
_ORIGINAL_ADAPTIVE_DISCOUNT = None
_ORIGINAL_MAIN = None


def _recall_floor() -> float:
    try:
        value = float(os.getenv("V4_RECALL_MIN_DISCOUNT_PCT", "20"))
    except ValueError:
        value = 20.0
    return max(10.0, min(35.0, value))


def recall_adaptive_discount_threshold(
    count: int,
    dispersion: str,
    liquidity: str,
    recent_90_count: int,
    dated_count: int,
    exact_grade_count: int,
    source_consistent: Optional[bool] = None,
    depends_on_other_graders: bool = False,
) -> float:
    """Use uncertainty as a premium instead of a blanket 30% rejection floor.

    High-volume/exact evidence can act at 20-25%. Sparse, stale, dispersed,
    cross-grader or conflicting evidence progressively requires more discount.
    Missing dates are uncertainty, not proof that the market observation is bad.
    """

    if count <= 1:
        threshold = 35.0
    elif count == 2:
        threshold = 30.0
    elif count <= 4:
        threshold = 25.0
    else:
        threshold = 20.0

    if dispersion == "élevée":
        threshold += 8.0
    elif dispersion == "moyenne":
        threshold += 3.0

    if liquidity == "faible":
        threshold += 5.0
    elif liquidity == "moyenne":
        threshold += 2.0

    if dated_count <= 0:
        # Aggregates such as PokeTrace may be current provider observations but
        # do not expose item-level sold dates. Keep them usable with a premium.
        threshold += 5.0
    elif recent_90_count == 0:
        threshold += 5.0
    elif recent_90_count / dated_count < 0.5:
        threshold += 3.0

    if count and exact_grade_count / count < 0.5:
        threshold += 3.0
    if source_consistent is False:
        threshold += 5.0
    if depends_on_other_graders:
        # Cross-grader evidence may support a review/estimate, but uncertainty
        # must remain explicit; it is never silently treated as exact-grade SOLD.
        threshold += 5.0

    return max(_recall_floor(), min(45.0, threshold))


def _install_final_recall_hooks() -> None:
    """Run after run_watcher_multimarket has installed its final process stack."""
    global _FINAL_HOOKS_INSTALLED
    if _FINAL_HOOKS_INSTALLED:
        return
    from v4_ask_fallback_review import install_v4_ask_fallback_review

    install_v4_ask_fallback_review()
    _FINAL_HOOKS_INSTALLED = True


def _main_with_final_recall_hooks(*args, **kwargs):
    _install_final_recall_hooks()
    return _ORIGINAL_MAIN(*args, **kwargs)


def install_v4_recall_policy() -> None:
    global _INSTALLED, _ORIGINAL_ADAPTIVE_DISCOUNT, _ORIGINAL_MAIN
    if _INSTALLED:
        return

    _ORIGINAL_ADAPTIVE_DISCOUNT = watcher.adaptive_discount_threshold
    watcher.adaptive_discount_threshold = recall_adaptive_discount_threshold

    # Scope expansion only: downstream provider/identity/grade matching remains
    # exact and simply returns no-match/insufficient when a provider has no tier.
    multimarket.PSA_PRODUCTION_GRADES = PSA_RECALL_GRADES

    # Keep user-facing diagnostics aligned with the effective recall floor.
    watcher.MIN_DISCOUNT = _recall_floor()

    # Delay the process wrapper until watcher.main() is invoked: the canonical
    # runner installs/replaces process_external_market_candidates after this
    # bootstrap module, so installing the ASK fallback earlier would be lost.
    _ORIGINAL_MAIN = watcher.main
    watcher.main = _main_with_final_recall_hooks

    _INSTALLED = True
    watcher.log(
        "Recall-first V4 policy enabled: adaptive discount floor "
        f"{watcher.MIN_DISCOUNT:.0f}% | PSA numeric scope 1-10 (no synthetic 9.5); "
        "identity/SOLD semantics unchanged"
    )
