"""Marketplace-first Global runner with validated exact-provider bridges.

Transport retries stay Global-only and exhausted retries remain fail-closed.
"""
from __future__ import annotations

import v4_global_live_confirmed as confirmed
import v4_global_marketplace_notify as marketplace
from v4_global_cardova_public_install import install_global_cardova_public_inventory
from v4_global_marketplace_fanatics_native_v3 import (
    install_global_marketplace_fanatics_native_v3,
)
from v4_global_marketplace_hardening import install_marketplace_first_hardening
from v4_global_marketplace_identity_dimension_hardening import (
    install_global_marketplace_identity_dimension_hardening,
)
from v4_global_marketplace_poketrace_recall import (
    install_global_marketplace_poketrace_recall,
)
from v4_global_marketplace_queue import install_marketplace_queue_hardening
from v4_global_marketplace_tcgdex_source_alias_recovery import (
    install_global_marketplace_tcgdex_source_alias_recovery,
)
from v4_global_provider_exact_bridge import install_global_provider_exact_bridge
from v4_global_tcgdex_resilience import install_global_tcgdex_resilience
from v4_tcgdex_detailed_variants import install_v4_tcgdex_detailed_variants


_ORIGINAL_INSTALL = confirmed.install_global_external_market_stack


def _install_stack_with_global_bridges() -> None:
    install_global_tcgdex_resilience()
    _ORIGINAL_INSTALL()
    install_global_marketplace_tcgdex_source_alias_recovery()
    install_global_provider_exact_bridge()
    # Install detailed variants before the retrieval recall so every candidate
    # returned by an optional recall still reaches the same final exact gate.
    install_v4_tcgdex_detailed_variants()
    install_global_marketplace_poketrace_recall()


def main() -> int:
    install_marketplace_first_hardening()
    # Fanatics native identity is installed before Cardova because both wrap the
    # marketplace scan. Cardova must remain the outer public-inventory wrapper.
    install_global_marketplace_fanatics_native_v3()
    # Cardova public inventory is installed after the marketplace hardening so
    # it wraps the exact production scanner selected by that layer.
    install_global_cardova_public_inventory()
    install_global_marketplace_identity_dimension_hardening()
    install_marketplace_queue_hardening()
    confirmed.install_global_external_market_stack = _install_stack_with_global_bridges
    return marketplace.main()


if __name__ == "__main__":
    raise SystemExit(main())
