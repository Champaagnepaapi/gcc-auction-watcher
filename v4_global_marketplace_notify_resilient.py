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
from v4_global_marketplace_magi_detail_retry import (
    install_global_marketplace_magi_detail_retry,
)
from v4_global_marketplace_magi_japanese_native_identity import (
    install_global_marketplace_magi_japanese_native_identity,
)
from v4_global_marketplace_magi_native_identity import (
    install_global_marketplace_magi_native_identity,
)
from v4_global_marketplace_magi_promo_source_proof import (
    install_global_marketplace_magi_promo_source_proof,
)
from v4_global_marketplace_magi_recovery_budget import (
    install_global_marketplace_magi_recovery_budget,
)
from v4_global_marketplace_magi_set_code_proof import (
    install_global_marketplace_magi_set_code_proof,
)
from v4_global_marketplace_magi_set_name_unique_card import (
    install_global_marketplace_magi_set_name_unique_card,
)
from v4_global_marketplace_magi_unique_full_number import (
    install_global_marketplace_magi_unique_full_number,
)
from v4_global_marketplace_poketrace_recall import (
    install_global_marketplace_poketrace_recall,
)
from v4_global_marketplace_queue import install_marketplace_queue_hardening
from v4_global_marketplace_tcgdex_source_alias_recovery import (
    install_global_marketplace_tcgdex_source_alias_recovery,
)
from v4_global_marketplace_unicode_identity import (
    install_global_marketplace_unicode_identity,
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
    # Global-only Unicode normalization preserves the exact historical Latin
    # contract while allowing already-proved Japanese names/sets to remain
    # complete commercial identities without translation.
    install_global_marketplace_unicode_identity()
    # Magi keeps one broad public inventory query but proves standard Japanese
    # single-card coordinates natively through TCGdex; GCC history is no longer
    # an identity prerequisite for this vault.
    install_global_marketplace_magi_native_identity()
    # Exact coordinate evidence may live in the current Magi detail body even
    # when page.title() omits it. Related-item/footer text remains excluded.
    install_global_marketplace_magi_detail_coordinate()
    # Retry the exact same public detail URL once on transport failure only.
    install_global_marketplace_magi_detail_retry()
    # S-P promo coordinates such as 324/S-P are checked directly against the
    # immutable TCGdex source pin before spending the shared Japanese REST budget.
    install_global_marketplace_magi_promo_source_proof()
    # A provider-exposed exact set code can satisfy the set axis after TCGdex
    # proves the same set ID + localId + denominator + Japanese card name.
    install_global_marketplace_magi_set_code_proof()
    # A Latin same-card projection is now retrieval convenience, not a mandatory
    # identity axis. Clean alias absence can fall back to the already-proved
    # Japanese TCGdex identity; conflicts/transients still fail closed.
    install_global_marketplace_magi_japanese_native_identity()
    # Recovery-only TCGdex paths have a separate bounded/cached budget so they
    # can never starve the normal exact-coordinate resolver.
    install_global_marketplace_magi_recovery_budget()
    # If Magi omits only the set code, reuse the existing bounded TCGdex
    # full-number uniqueness resolver. Exact Japanese card-name confirmation
    # remains mandatory and ambiguous coordinates stay blocked.
    install_global_marketplace_magi_unique_full_number()
    # If Magi omits the number but states one exact Japanese set name, TCGdex may
    # supply the coordinate only when exactly one card name from that set matches
    # the current product title. Name-only listings remain blocked.
    install_global_marketplace_magi_set_name_unique_card()
    # Cardova public inventory wraps the exact production scanner selected by
    # the preceding marketplace hardenings.
    install_global_cardova_public_inventory()
    install_global_marketplace_identity_dimension_hardening()
    install_marketplace_queue_hardening()
    confirmed.install_global_external_market_stack = _install_stack_with_global_bridges
    return marketplace.main()


if __name__ == "__main__":
    raise SystemExit(main())
