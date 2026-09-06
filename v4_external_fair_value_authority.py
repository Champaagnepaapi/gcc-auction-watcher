from __future__ import annotations

from dataclasses import replace

import watcher


_POLICY_MARKER = "_v4_external_fair_value_authority_installed"
_POLICY_REASON = (
    "historique GCC ignoré pour la fair value; preuve marché externe forte requise"
)


def gcc_without_economic_authority(
    gcc: watcher.GccMarketEvidence,
) -> watcher.GccMarketEvidence:
    """Return a GCC evidence view that cannot create or anchor fair value.

    GCC remains the source of the live listing identity/current price, but its
    historical sales are observational only. Hard terminal safety rejections are
    preserved unchanged and are never bypassed.
    """

    if gcc.terminal:
        return gcc
    return replace(
        gcc,
        sales=[],
        estimate=None,
        opportunity=None,
        branch=watcher.GCC_BRANCH_UNAVAILABLE,
        strength=watcher.EVIDENCE_UNAVAILABLE,
        rejection=_POLICY_REASON,
    )


def install_v4_external_fair_value_authority() -> None:
    """Make strong external market evidence the sole V4 fair-value authority.

    The existing external provider tree, strict identity gates, SOLD semantics,
    cache, budgets and arbitration implementation stay intact. This wrapper only
    removes GCC history from the economic side of arbitration. Therefore:

    - strong exact external evidence can still create EXTERNAL_RESCUE;
    - external PENDING/WEAK/UNAVAILABLE cannot fall back to GCC_ONLY economics;
    - GCC terminal safety rejection stays terminal;
    - no purchase/bid/checkout behavior is introduced.
    """

    current = watcher.arbitrate_market_evidence
    if getattr(current, _POLICY_MARKER, False):
        return

    def external_fair_value_arbitration(
        gcc: watcher.GccMarketEvidence,
        external: watcher.ExternalMarketEvidence,
    ) -> watcher.ArbitrationResult:
        if gcc.terminal:
            return current(gcc, external)
        return current(gcc_without_economic_authority(gcc), external)

    setattr(external_fair_value_arbitration, _POLICY_MARKER, True)
    setattr(external_fair_value_arbitration, "_wrapped_arbitration", current)
    watcher.arbitrate_market_evidence = external_fair_value_arbitration
    watcher.log(
        "Fair value authority: EXTERNAL_ONLY "
        "(GCC history observational; strong external market evidence required)"
    )
