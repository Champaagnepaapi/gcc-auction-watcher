"""Read-only Global economic confirmation with exact provider-coordinate bridges."""
from __future__ import annotations

import v4_global_live_confirmed as confirmed
from v4_global_provider_exact_bridge import install_global_provider_exact_bridge


_ORIGINAL_INSTALL = confirmed.install_global_external_market_stack


def _install_stack_with_global_bridges() -> None:
    _ORIGINAL_INSTALL()
    install_global_provider_exact_bridge()


def main() -> int:
    confirmed.install_global_external_market_stack = _install_stack_with_global_bridges
    return confirmed.main()


if __name__ == "__main__":
    raise SystemExit(main())
