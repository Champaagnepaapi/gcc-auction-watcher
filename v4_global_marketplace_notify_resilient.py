"""Marketplace-first Global runner with validated exact-provider bridges.

Transport retries stay Global-only and exhausted retries remain fail-closed.
"""
from __future__ import annotations

import v4_global_live_confirmed as confirmed
import v4_global_marketplace_notify as marketplace
from v4_global_marketplace_hardening import install_marketplace_first_hardening
from v4_global_provider_exact_bridge import install_global_provider_exact_bridge
from v4_global_tcgdex_resilience import install_global_tcgdex_resilience


_ORIGINAL_INSTALL = confirmed.install_global_external_market_stack


def _install_stack_with_global_bridges() -> None:
    install_global_tcgdex_resilience()
    _ORIGINAL_INSTALL()
    install_global_provider_exact_bridge()


def main() -> int:
    install_marketplace_first_hardening()
    confirmed.install_global_external_market_stack = _install_stack_with_global_bridges
    return marketplace.main()


if __name__ == "__main__":
    raise SystemExit(main())
