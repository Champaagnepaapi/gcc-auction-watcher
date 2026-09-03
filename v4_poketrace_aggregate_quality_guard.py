from __future__ import annotations

from dataclasses import replace
from typing import Callable, Optional

import watcher
import v4_canonical_multimarket as multimarket
import v4_poketrace_market_retrieval as retrieval


_BASE_POKETRACE_EVIDENCE: Optional[Callable] = None
_INSTALLED = False


def _degenerate_strong_poketrace_aggregate(
    evidence: watcher.ExternalMarketEvidence,
) -> bool:
    """Reject a strong aggregate when it carries no informative price range.

    PokeTrace's graded eBay surface is aggregate-only.  A response where
    low == central == high cannot prove dispersion: in the observed production
    failure this shape came from missing low/high bounds that V4 had imputed
    from avg.  Treat it as insufficient rather than manufacturing a zero-width
    market range.
    """

    if not (
        evidence.status == watcher.EXTERNAL_MATCHED
        and evidence.strength == watcher.EVIDENCE_STRONG
        and str(evidence.source or "").strip().casefold() == "poketrace"
        and evidence.estimate is not None
    ):
        return False

    estimate = evidence.estimate
    try:
        low = float(estimate.low)
        central = float(estimate.central)
        high = float(estimate.high)
    except (TypeError, ValueError):
        return True
    if min(low, central, high) <= 0:
        return True

    # Prices are user-facing at cent precision.  A <= 1 cent total envelope is
    # non-informative for an aggregate market distribution and must be
    # corroborated by the independent APR/eBay fallback before it can act.
    return max(low, central, high) - min(low, central, high) <= 0.01


def _downgrade_degenerate_aggregate(
    evidence: watcher.ExternalMarketEvidence,
) -> watcher.ExternalMarketEvidence:
    if not _degenerate_strong_poketrace_aggregate(evidence):
        return evidence

    diagnostics = getattr(multimarket, "_DIAGNOSTICS", None)
    if diagnostics is not None:
        # The wrapped canonical collector has already counted this result as
        # strong.  Reclassify the same observation once so run diagnostics match
        # the evidence that downstream arbitration actually receives.
        if getattr(diagnostics, "poketrace_strong", 0) > 0:
            diagnostics.poketrace_strong -= 1
        diagnostics.poketrace_weak += 1

    estimate = evidence.estimate
    central = float(estimate.central) if estimate is not None else 0.0
    note = str(evidence.note or "").strip()
    guard_note = (
        "agrégat PokeTrace dégénéré/non informatif "
        f"({central:.2f} € sans plage exploitable); "
        "valorisation PokeTrace seule bloquée, fallback APR/eBay requis"
    )
    return replace(
        evidence,
        status=watcher.EXTERNAL_CLEAN_INSUFFICIENT,
        strength=watcher.EVIDENCE_WEAK,
        estimate=None,
        comparables=[],
        note=f"{note}; {guard_note}" if note else guard_note,
    )


def _quality_guarded_original_evidence(*args, **kwargs):
    base = _BASE_POKETRACE_EVIDENCE
    if base is None or base is _quality_guarded_original_evidence:
        raise RuntimeError("PokeTrace aggregate quality guard is not initialized")
    evidence = base(*args, **kwargs)
    return _downgrade_degenerate_aggregate(evidence)


def install_v4_poketrace_aggregate_quality_guard() -> None:
    """Guard PokeTrace aggregate evidence before structured retrieval publishes it.

    The production bootstrap installs this before run_watcher_multimarket.  The
    later structured-retrieval installer therefore keeps all TCGdex-first exact
    identity logic while calling this guarded original evidence function.
    """

    global _BASE_POKETRACE_EVIDENCE
    global _INSTALLED
    if _INSTALLED:
        return

    _BASE_POKETRACE_EVIDENCE = retrieval._ORIGINAL_EVIDENCE
    retrieval._ORIGINAL_EVIDENCE = _quality_guarded_original_evidence
    _INSTALLED = True
