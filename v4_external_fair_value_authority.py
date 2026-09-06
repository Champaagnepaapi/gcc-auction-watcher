from __future__ import annotations

from dataclasses import replace

import watcher
from v4_pricecharting_mandatory_policy import (
    install_v4_pricecharting_mandatory_guide_policy,
)
from v4_pricecharting_valuation import (
    install_v4_pricecharting_valuation_source_roles,
)


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
    """Make external valuation providers the sole V4 fair-value authority.

    Source roles are explicit:

    - PokeTrace / PSA APR keep priority when stronger compatible market evidence
      exists;
    - PriceCharting is consulted systematically as a GUIDE reference for exact
      PSA 8/9/10 cards and may stand alone when stronger evidence is unavailable;
    - Grade 9 / Grade 8 guide buckets are accepted as PSA 9 / PSA 8-equivalent
      guide estimates, without claiming item-level SOLD or underlying grader;
    - direct eBay SOLD scraping is removed from fair-value authority in this
      source-role phase;
    - GCC history cannot create, anchor, confirm or cap fair value;
    - no purchase/bid/checkout behavior is introduced.
    """

    # Install source roles before arbitration. The mandatory guide layer wraps
    # the canonical PokeTrace path too, so PriceCharting is still consulted when
    # PokeTrace is already strong instead of being only a last fallback.
    install_v4_pricecharting_valuation_source_roles()
    install_v4_pricecharting_mandatory_guide_policy()

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
        "Fair value authority: EXTERNAL_ONLY + mandatory PriceCharting guide "
        "reference (GCC history observational only)"
    )
