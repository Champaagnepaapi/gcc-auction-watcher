from __future__ import annotations

from dataclasses import replace

import watcher
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
    """Make strong valuation-provider evidence the sole V4 fair-value authority.

    Opportunity marketplaces and valuation providers are deliberately separate:
    GCC supplies the live opportunity; direct eBay is reserved for a future
    active-listing opportunity scanner; PokeTrace, PSA APR and PriceCharting are
    valuation sources. Strict identity, SOLD semantics, cache/budgets and
    fail-closed arbitration remain mandatory.

    Therefore:

    - GCC historical sales cannot create, anchor, confirm or cap fair value;
    - PokeTrace remains the first external graded market path;
    - PSA APR remains the exact PSA fallback;
    - PriceCharting is a bounded valuation fallback (PSA 10 guide automatic,
      generic grade buckets weak only);
    - direct eBay SOLD scraping cannot become fair-value authority;
    - external PENDING/WEAK/UNAVAILABLE cannot fall back to GCC economics;
    - GCC terminal safety rejection stays terminal;
    - no purchase/bid/checkout behavior is introduced.
    """

    # Install after the already-active provider resilience wrappers so this
    # source-role guard preserves their PSA APR behavior while removing direct
    # eBay SOLD from the economic fallback and adding PriceCharting.
    install_v4_pricecharting_valuation_source_roles()

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
        "(opportunity markets separated from valuation providers)"
    )
