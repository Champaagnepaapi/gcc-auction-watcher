from __future__ import annotations

import runpy

import v4_pricecharting_valuation as pricecharting_roles
from v4_global_tcgdex_resilience import install_v4_tcgdex_resilience
from v4_pricecharting_mandatory_policy import (
    install_v4_pricecharting_mandatory_guide_policy,
)
from v4_recall_policy import install_v4_recall_policy
from v4_robot_kb_readonly_market import install_v4_robot_kb_readonly_market
from v4_tcgdex_source_pinned_outage_fallback import (
    install_v4_tcgdex_source_pinned_outage_fallback,
)


_ORIGINAL_PRICECHARTING_SOURCE_ROLE_INSTALL = (
    pricecharting_roles.install_v4_pricecharting_valuation_source_roles
)


def _install_pricecharting_and_readonly_kb_roles() -> None:
    """Install final V4 valuation roles after canonical provider bootstrap.

    PriceCharting is a systematic GUIDE reference, not a fake SOLD source. The
    optional Robot KB lane can contribute only exact completed non-GCC SOLD rows
    through its authenticated read-only bridge. Exact/recent SOLD evidence keeps
    priority over the PriceCharting guide.
    """
    _ORIGINAL_PRICECHARTING_SOURCE_ROLE_INSTALL()
    install_v4_robot_kb_readonly_market()
    install_v4_pricecharting_mandatory_guide_policy()


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
    # run_watcher_multimarket imports this installer by name. Replace that one
    # bootstrap hook before runpy so the final canonical provider stack gets the
    # mandatory PriceCharting reference and the optional Robot KB exact-SOLD
    # bridge without duplicating the underlying source-role implementation.
    pricecharting_roles.install_v4_pricecharting_valuation_source_roles = (
        _install_pricecharting_and_readonly_kb_roles
    )
    # PokeTrace's exact-card/exact-grade aggregate avg remains aggregate evidence,
    # not an item-level SOLD. PriceCharting is consulted systematically but stays
    # GUIDE; stronger exact/recent SOLD evidence remains economically primary.
    runpy.run_module("run_watcher_multimarket", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
