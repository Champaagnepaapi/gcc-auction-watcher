from __future__ import annotations

import runpy

from v4_global_tcgdex_resilience import install_v4_tcgdex_resilience
from v4_poketrace_aggregate_quality_guard import (
    install_v4_poketrace_aggregate_quality_guard,
)
from v4_tcgdex_source_pinned_outage_fallback import (
    install_v4_tcgdex_source_pinned_outage_fallback,
)


def main() -> None:
    """Bootstrap canonical V4 with bounded provider resilience and signal quality."""
    install_v4_tcgdex_resilience()
    # Run only after the proven transport retry/breaker layer. This fallback can
    # recover a retryable REST outage only for already-reviewed Japanese exact
    # set/localId coordinates proven again by the immutable TCGdex source pin.
    install_v4_tcgdex_source_pinned_outage_fallback()
    # Install before the canonical runner wires structured PokeTrace retrieval.
    # Degenerate aggregate-only price ranges are downgraded to weak evidence so
    # APR/eBay fallback must corroborate them before any automatic valuation.
    install_v4_poketrace_aggregate_quality_guard()
    runpy.run_module("run_watcher_multimarket", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
