"""Recover Magi identities when the provider omits only the set code.

The existing Japanese TCGdex resolver already has a bounded, deterministic
full-number fallback: for a numeric denominator it enumerates only sets with the
same official count, probes the exact localId, and returns EXACT only when the
coordinate is globally unique.  Magi previously never reached that path because
its native preflight required an explicit provider set code first.

This Global-only wrapper reuses that proven resolver after ``set_code_unproven``.
The exact Japanese card name must also be present in the bounded current-product
evidence. Ambiguity, provider errors, missing names and non-numeric denominators
remain blocking. No fuzzy matching or translation is introduced.
"""
from __future__ import annotations

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_detail_coordinate as detail_coordinate
import v4_global_marketplace_magi_japanese_native_identity as japanese_native
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_recovery_budget as recovery_budget
import v4_tcgdex_generalized_coordinate_recovery as generalized
from v4_global_market_core import CommercialIdentity


_ORIGINAL_RESOLVER = None
_INSTALLED = False


def recover_unique_full_number_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver,
) -> native.MagiNativeResolution:
    """Recover only a missing provider set code via TCGdex global uniqueness."""
    if original.status != "NO_MATCH" or original.reason != "set_code_unproven":
        return original

    evidence = detail_coordinate._current_product_evidence(ask)
    full_number, number_reason = detail_coordinate._full_number_from_evidence(evidence)
    if not full_number or "/" not in full_number:
        return native.MagiNativeResolution("NO_MATCH", number_reason or "collector_number_unproven")

    local, denominator = full_number.split("/", 1)
    if not local or not denominator.isdigit():
        return original

    synthetic = japan.Identity(
        name="",
        set_name="",
        number=full_number,
        language="Japanese",
        grader="PSA",
        grade="10",
        year=2000,
    )
    proof = resolver.resolve(synthetic, title="")
    if proof.status != "EXACT":
        status = "ERROR" if proof.status in {"ERROR", "BUDGET"} else proof.status
        return native.MagiNativeResolution(
            status if status in {"ERROR", "AMBIGUOUS"} else "NO_MATCH",
            f"target_catalog_unproven:{proof.reason or proof.status}",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    if not all((proof.card_id, proof.set_id, proof.local_id, proof.name_ja)):
        return native.MagiNativeResolution(
            "NO_MATCH",
            "tcgdex_unique_full_number_incomplete",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    if not generalized._same_local_id(local, proof.local_id):
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "tcgdex_unique_full_number_local_conflict",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    try:
        denominator_ok = bool(proof.official_count) and int(proof.official_count) == int(denominator)
    except (TypeError, ValueError):
        denominator_ok = False
    if not denominator_ok:
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "tcgdex_unique_full_number_denominator_conflict",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    if not magi_hardening._jp_contains(evidence, proof.name_ja):
        return native.MagiNativeResolution(
            "NO_MATCH",
            "target_japanese_card_name_unproven",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    set_label = japanese_native._resolver_set_label(proof, full_number=full_number)
    if not set_label:
        return native.MagiNativeResolution(
            "AMBIGUOUS",
            "tcgdex_native_set_label_ambiguous",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    identity = CommercialIdentity(
        name=str(proof.name_ja).strip(),
        set_name=set_label,
        number=full_number,
        language="ja",
        grader="PSA",
        grade="10",
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return native.MagiNativeResolution(
            "NO_MATCH",
            "commercial_identity_incomplete",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    return native.MagiNativeResolution(
        "EXACT",
        f"MAGI_NATIVE_TCGDEX_JA_UNIQUE_FULL_NUMBER+{proof.reason or 'TCGDEX_JA_UNIQUE_FULL_NUMBER'}",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _resolve_with_unique_full_number(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    resolver = recovery_budget.active_recovery_resolver(kwargs["resolver"])
    return recover_unique_full_number_resolution(
        ask,
        original,
        resolver=resolver,
    )


def install_global_marketplace_magi_unique_full_number() -> None:
    """Install after all existing Magi exact-coordinate wrappers."""
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_unique_full_number
    _INSTALLED = True
