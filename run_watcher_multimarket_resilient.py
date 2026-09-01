from __future__ import annotations

import runpy

from v4_global_tcgdex_resilience import install_v4_tcgdex_resilience


def main() -> None:
    """Bootstrap the canonical V4 runner with proven TCGdex transport resilience."""
    install_v4_tcgdex_resilience()
    runpy.run_module("run_watcher_multimarket", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
