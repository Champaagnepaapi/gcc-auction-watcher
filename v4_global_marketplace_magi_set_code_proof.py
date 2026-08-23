"""Magi exact-set-code proof for numeric Japanese coordinates.

Some Magi listings expose the exact printed coordinate as ``SV8a 209/187`` but
not the localized Japanese set name. The native resolver already requires the
provider set code to equal the exact Japanese TCGdex set ID, plus exact localId,
denominator and Japanese card name. This wrapper removes only the redundant
localized-set-name text requirement for that measured case.
"""
from __future__ import annotations

from typing import Mapping, Optional

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_native_identity as native
import v4_tcgdex_generalized_coordinate_recovery as generalized


_ORIGINAL_RESOLVER = None
_INSTALLED = False


def recover_exact_set_code_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    resolver,
    alias_json_get,
    proof_cache: Optional[dict] = None,
    alias_cache: Optional[dict] = None,
) -> native.MagiNativeResolution:
    """Recover only the redundant Japanese-set-name rejection, fail-closed."""
    if original.status != "NO_MATCH" or original.reason != "target_japanese_set_unproven":
        return original

    full_number, set_code, _reason = native._preflight(ask)
    if not full_number or not set_code or "/" not in full_number:
        return original
    local, denominator = full_number.split("/", 1)
    if not denominator.isdigit():
        return original

    proof_cache = proof_cache if proof_cache is not None else {}
    alias_cache = alias_cache if alias_cache is not None else {}
    proof = native._proof_for_coordinate(
        resolver,
        full_number=full_number,
        set_code=set_code,
        cache=proof_cache,
    )
    if proof.status != "EXACT":
        return original
    if not native._same_set(proof.set_id, set_code):
        return original
    if not generalized._same_local_id(proof.local_id, local):
        return original
    try:
        denominator_ok = bool(proof.official_count) and int(proof.official_count) == int(denominator)
    except (TypeError, ValueError):
        denominator_ok = False
    if not denominator_ok:
        return original

    current = japan.current_text("\n".join(value for value in (ask.title, ask.text) if value))
    if not proof.name_ja or not magi_hardening._jp_contains(current, proof.name_ja):
        return original

    if proof.card_id in alias_cache:
        alias_card, alias_reason = alias_cache[proof.card_id]
    else:
        alias_card, alias_reason = native._fetch_latin_alias_same_card(
            proof,
            json_get=alias_json_get,
        )
        alias_cache[proof.card_id] = (alias_card, alias_reason)
    if alias_card is None:
        status = "ERROR" if "budget" in alias_reason or "transient" in alias_reason else "NO_MATCH"
        return native.MagiNativeResolution(
            status,
            alias_reason,
            card_id=proof.card_id,
            set_id=proof.set_id,
        )

    identity = native._identity_from_alias(alias_card, full_number=full_number)
    if identity is None:
        return native.MagiNativeResolution(
            "NO_MATCH",
            "commercial_identity_incomplete",
            card_id=proof.card_id,
            set_id=proof.set_id,
        )
    return native.MagiNativeResolution(
        "EXACT",
        f"MAGI_NATIVE_TCGDEX_JA_SET_CODE_EXACT+{alias_reason}",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _resolve_with_exact_set_code(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    return recover_exact_set_code_resolution(ask, original, **kwargs)


def install_global_marketplace_magi_set_code_proof() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_exact_set_code
    _INSTALLED = True
