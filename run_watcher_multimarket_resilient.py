from __future__ import annotations

import runpy

from v4_global_tcgdex_resilience import install_v4_tcgdex_resilience
from v4_tcgdex_source_pinned_outage_fallback import (
    install_v4_tcgdex_source_pinned_outage_fallback,
)


def main() -> None:
    """Bootstrap canonical V4 with bounded TCGdex outage resilience."""
    install_v4_tcgdex_resilience()
    # Run only after the proven transport retry/breaker layer. This fallback can
    # recover a retryable REST outage only for already-reviewed Japanese exact
    # set/localId coordinates proven again by the immutable TCGdex source pin.
    install_v4_tcgdex_source_pinned_outage_fallback()
    runpy.run_module("run_watcher_multimarket", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
