from __future__ import annotations

import runpy

from v4_global_tcgdex_resilience import install_v4_tcgdex_resilience
from v4_recall_policy import install_v4_recall_policy
from v4_tcgdex_source_pinned_outage_fallback import (
    install_v4_tcgdex_source_pinned_outage_fallback,
)


def main() -> None:
    """Bootstrap canonical V4 with bounded provider resilience."""
    install_v4_tcgdex_resilience()
    # Run only after the proven transport retry/breaker layer. This fallback can
    # recover a retryable REST outage only for already-reviewed Japanese exact
    # set/localId coordinates proven again by the immutable TCGdex source pin.
    install_v4_tcgdex_source_pinned_outage_fallback()
    # Recall-first economics: keep exact PokeTrace aggregates usable, let strong
    # evidence act below the old 30% blanket floor, and widen explicit PSA grade
    # scope without changing card/language/variant/SOLD truth semantics.
    install_v4_recall_policy()
    # PokeTrace's exact-card/exact-grade aggregate avg remains aggregate evidence,
    # not an item-level SOLD. Do not discard that avg merely because the provider
    # omitted an informative low/high envelope; volume/recency uncertainty is
    # handled by the adaptive discount policy instead of a blanket WEAK downgrade.
    runpy.run_module("run_watcher_multimarket", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
