"""Recover exact Magi identities directly from proved Japanese TCGdex cards.

A Latin TCGdex projection is useful for provider retrieval, but it is not an
identity axis. When Magi already proves the exact Japanese set/localId/card ID,
collector denominator, Japanese card name and PSA 10, a clean absence of an
EN/ID projection must not erase that exact identity.

This layer remains fail-closed: coordinate conflicts, transient/provider errors,
ambiguous set aliases and unproved Japanese names still block. Immutable
source-pinned exact proofs may skip the redundant Latin projection entirely.
It is installed only in the Global marketplace process and reuses the existing
source-pinned Japanese alias registry for resolver-compatible set labels.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_notify as marketplace
import v4_global_marketplace_scan as scan
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_japanese_set_aliases as japanese_aliases
from v4_global_market_core import CommercialIdentity
from v4_global_marketplace_unicode_identity import (
    install_global_marketplace_unicode_identity,
)


_RECOVERABLE_ALIAS_ABSENCE = frozenset(
    {"tcgdex_alias_not_found", "tcgdex_alias_non_latin_identity"}
)
_SOURCE_PINNED_NATIVE_REASONS = frozenset(
    {
        "TCGDEX_SOURCE_PINNED_S_P_PROMO_EXACT",
        "TCGDEX_SOURCE_PINNED_STANDARD_COORDINATE_EXACT",
    }
)
_ORIGINAL_RESOLVER = None
_ORIGINAL_ALIAS_FETCH = None
_ORIGINAL_SCAN = None
_INSTALLED = False


def _resolver_set_label(proof, *, full_number: str) -> str:
    """Choose one deterministic set label that can re-enter the V4 resolver."""
    matching = [
        alias
        for alias in japanese_aliases._ALIASES
        if str(alias.language_code).casefold() == "ja"
        and native._same_set(alias.tcgdex_set_id, proof.set_id)
        and generalized._validate_reference_for_alias(full_number, alias)
    ]
    if len(matching) > 1:
        return ""
    if len(matching) == 1:
        return str(matching[0].listing_set or "").strip()
    return str(proof.set_name_ja or proof.set_id or "").strip()


def _coordinate_still_exact(
    *,
    full_number: str,
    set_code: str,
    proof,
    original: native.MagiNativeResolution,
) -> bool:
    if proof is None or proof.status != "EXACT":
        return False
    if not proof.card_id or not proof.set_id or not proof.local_id or not proof.name_ja:
        return False
    if original.card_id and original.card_id != proof.card_id:
        return False
    if original.set_id and not native._same_set(original.set_id, proof.set_id):
        return False
    if not native._same_set(set_code, proof.set_id) or "/" not in full_number:
        return False

    local, denominator = full_number.split("/", 1)
    if not generalized._same_local_id(local, proof.local_id):
        return False
    if denominator.isdigit():
        try:
            return bool(proof.official_count) and int(proof.official_count) == int(denominator)
        except (TypeError, ValueError):
            return False
    return native._same_set(denominator, proof.set_id)


def recover_japanese_native_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    proof_cache: dict[tuple[str, str], object],
) -> native.MagiNativeResolution:
    """Recover only clean Latin-alias absence after exact Japanese proof."""
    if original.status != "NO_MATCH" or original.reason not in _RECOVERABLE_ALIAS_ABSENCE:
        return original

    full_number, set_code, _reason = native._preflight(ask)
    if not full_number or not set_code:
        return original
    proof = proof_cache.get((set_code.casefold(), full_number.upper()))
    if not _coordinate_still_exact(
        full_number=full_number,
        set_code=set_code,
        proof=proof,
        original=original,
    ):
        return original

    current = japan.current_text("\n".join(value for value in (ask.title, ask.text) if value))
    if not magi_hardening._jp_contains(current, proof.name_ja):
        return original

    set_label = _resolver_set_label(proof, full_number=full_number)
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
        f"MAGI_NATIVE_TCGDEX_JA_NATIVE_EXACT+{proof.reason or 'TCGDEX_JA_EXACT'}",
        identity=identity,
        card_id=proof.card_id,
        set_id=proof.set_id,
    )


def _alias_fetch_with_source_native(proof, *, json_get):
    assert _ORIGINAL_ALIAS_FETCH is not None
    # An immutable source-pinned card proof already proves the exact Japanese
    # identity. Do not make a redundant Latin projection request that can fail
    # during the same TCGdex outage we just recovered from.
    if proof.status == "EXACT" and proof.reason in _SOURCE_PINNED_NATIVE_REASONS:
        return None, "tcgdex_alias_not_found"
    return _ORIGINAL_ALIAS_FETCH(proof, json_get=json_get)


def _resolve_with_japanese_native(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    call_kwargs = dict(kwargs)
    proof_cache = call_kwargs.get("proof_cache")
    if proof_cache is None:
        proof_cache = {}
        call_kwargs["proof_cache"] = proof_cache
    alias_cache = call_kwargs.get("alias_cache")
    if alias_cache is None:
        alias_cache = {}
        call_kwargs["alias_cache"] = alias_cache

    original = _ORIGINAL_RESOLVER(ask, **call_kwargs)
    return recover_japanese_native_resolution(
        ask,
        original,
        proof_cache=proof_cache,
    )


def _scan_with_japanese_native(*args, **kwargs):
    assert _ORIGINAL_SCAN is not None
    rows, status = _ORIGINAL_SCAN(*args, **kwargs)
    old = "exact Japanese TCGdex -> same immutable card Latin projection"
    new = (
        "exact Japanese TCGdex -> deterministic Latin same-card alias when available, "
        "otherwise TCGdex-proven Japanese native identity"
    )
    detail = str(status.detail or "")
    detail = detail.replace(old, new) if old in detail else f"{detail}; Japanese native identity fallback enabled"
    return rows, replace(status, detail=detail)


def install_global_marketplace_magi_japanese_native_identity() -> None:
    """Install after the Magi source/set-code proof wrappers in Global only."""
    global _ORIGINAL_RESOLVER, _ORIGINAL_ALIAS_FETCH, _ORIGINAL_SCAN, _INSTALLED
    if _INSTALLED:
        return

    install_global_marketplace_unicode_identity()
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    _ORIGINAL_ALIAS_FETCH = native._fetch_latin_alias_same_card
    _ORIGINAL_SCAN = native.scan_magi_native_inventory

    native._fetch_latin_alias_same_card = _alias_fetch_with_source_native
    native.resolve_magi_native_identity = _resolve_with_japanese_native
    native.scan_magi_native_inventory = _scan_with_japanese_native
    scan.scan_magi_inventory = _scan_with_japanese_native
    marketplace.scan_magi_inventory = _scan_with_japanese_native
    _INSTALLED = True
