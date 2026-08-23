"""Marketplace-first Global runner with validated exact-provider bridges.

Transport retries stay Global-only and exhausted retries remain fail-closed.
"""
from __future__ import annotations

import v4_global_live_confirmed as confirmed
import v4_global_marketplace_notify as marketplace
from v4_global_cardova_public_install import install_global_cardova_public_inventory
from v4_global_marketplace_fanatics_language_proof import (
    install_global_marketplace_fanatics_language_proof,
)
from v4_global_marketplace_hardening import install_marketplace_first_hardening
from v4_global_marketplace_identity_dimension_hardening import (
    install_global_marketplace_identity_dimension_hardening,
)
from v4_global_marketplace_magi_detail_coordinate import (
    install_global_marketplace_magi_detail_coordinate,
)
from v4_global_marketplace_magi_native_identity import (
    install_global_marketplace_magi_native_identity,
)
from v4_global_marketplace_magi_promo_source_proof import (
    install_global_marketplace_magi_promo_source_proof,
)
from v4_global_marketplace_magi_set_code_proof import (
    install_global_marketplace_magi_set_code_proof,
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
    # Fanatics native identity is installed before Magi/Cardova because all
    # three wrap the marketplace scan. Missing Fanatics language is accepted
    # only after a deterministic two-language TCGdex set proof.
    install_global_marketplace_fanatics_language_proof()
    # Magi keeps one broad public inventory query but proves standard Japanese
    # single-card coordinates natively through TCGdex; GCC history is no longer
    # an identity prerequisite for this vault.
    install_global_marketplace_magi_native_identity()
    # Exact coordinate evidence may live in the current Magi detail body even
    # when page.title() omits it. Related-item/footer text remains excluded.
    install_global_marketplace_magi_detail_coordinate()
    # S-P promo coordinates such as 324/S-P are checked directly against the
    # immutable TCGdex source pin before spending the shared Japanese REST budget.
    install_global_marketplace_magi_promo_source_proof()
    # A provider-exposed exact set code can satisfy the set axis after TCGdex
    # proves the same set ID + localId + denominator + Japanese card name.
    install_global_marketplace_magi_set_code_proof()
    # Cardova public inventory wraps the exact production scanner selected by
    # the preceding marketplace hardenings.
    install_global_cardova_public_inventory()
    install_global_marketplace_identity_dimension_hardening()
    install_marketplace_queue_hardening()
    confirmed.install_global_external_market_stack = _install_stack_with_global_bridges
    return marketplace.main()


if __name__ == "__main__":
    raise SystemExit(main())
