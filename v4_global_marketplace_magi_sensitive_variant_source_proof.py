"""Exact source-pinned recovery for Magi Poke Ball / Master Ball mirror cards.

The normal Magi preflight intentionally blocks material variant claims. This
wrapper keeps that default and recovers only the two ball-mirror classes already
represented by the V4 detailed-variant contract when immutable TCGdex source
proof makes every material axis deterministic.

Required proof:
- prior final reason is ``sensitive_variant_unproven``;
- exactly one explicit Japanese marker: モンスターボールミラー or
  マスターボールミラー, with no other sensitive marker remaining;
- one exact numeric full collector coordinate in current Magi evidence;
- exactly one set-code-shaped provider token whose immutable TCGdex set/card
  coordinate proves exact set id, official denominator, local id and Japanese
  card/set names;
- the exact pinned card file contains ``reverse`` with the requested foil.

The resulting CommercialIdentity reuses the existing representation:
``finish=reverse`` and ``variant=poke_ball|master_ball``. No new variant
convention, fuzzy matching or per-card exception is introduced.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, Optional

import japan_edge_hunter as japan
import v4_global_magi_registry_hardening as magi_hardening
import v4_global_marketplace_magi_detail_coordinate as detail_coordinate
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_standard_source_proof as standard_source
import v4_tcgdex_source_pinned_finish as source_finish
from v4_global_market_core import CommercialIdentity


_MARKERS = {
    unicodedata.normalize("NFKC", "モンスターボールミラー"): "poke_ball",
    unicodedata.normalize("NFKC", "マスターボールミラー"): "master_ball",
}
_SET_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,6}\d+[A-Za-z0-9.-]*)(?![A-Za-z0-9])")
_EXPECTED_PRIOR_REASON = "sensitive_variant_unproven"
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def _variant_marker(evidence: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", str(evidence or ""))
    found = [(marker, variant) for marker, variant in _MARKERS.items() if marker in normalized]
    if len(found) != 1:
        return "", ""
    marker, variant = found[0]
    remainder = normalized.replace(marker, " ")
    # The selected ball-mirror marker is the only sensitive claim this recovery
    # can prove. Edition/error/stamp/other finish claims remain blocking.
    if native._SENSITIVE_RE.search(remainder):
        return "", ""
    return marker, variant


def _set_tokens(evidence: str) -> tuple[str, ...]:
    normalized = unicodedata.normalize("NFKC", str(evidence or ""))
    values = []
    for match in _SET_TOKEN_RE.finditer(normalized):
        token = match.group(1).strip()
        upper = token.upper()
        if upper.startswith("PSA"):
            continue
        if token not in values:
            values.append(token)
    return tuple(values)


def _pinned_variant_supported(card_text: str, special_variant: str) -> bool:
    foil = {"poke_ball": "pokeball", "master_ball": "masterball"}.get(special_variant)
    if not foil:
        return False
    # TCGdex source stores both axes in each variant object. The bounded span
    # prevents a foil token from being associated with an unrelated distant
    # variant declaration while allowing nested thirdParty metadata.
    return bool(
        re.search(
            rf"\btype\s*:\s*['\"]reverse['\"][\s\S]{{0,180}}?\bfoil\s*:\s*['\"]{foil}['\"]",
            card_text,
            re.IGNORECASE,
        )
    )


def source_pinned_sensitive_variant_identity(
    *,
    evidence: str,
    source_text_get: Callable[[str], Optional[str]] = standard_source._source_text,
) -> tuple[Optional[CommercialIdentity], str, str]:
    current = japan.current_text(evidence)
    _marker, special_variant = _variant_marker(current)
    if not special_variant:
        return None, "", ""

    full_number, _ = detail_coordinate._full_number_from_evidence(current)
    if not full_number or "/" not in full_number:
        return None, "", ""
    local, denominator = full_number.split("/", 1)
    if not local.isdigit() or not denominator.isdigit():
        return None, "", ""

    proofs = []
    for set_code in _set_tokens(current):
        proof = standard_source.source_pinned_standard_proof(
            full_number=full_number,
            set_code=set_code,
            source_text_get=source_text_get,
        )
        if proof is None:
            continue
        if not proof.name_ja or not proof.set_name_ja:
            continue
        if not magi_hardening._jp_contains(current, proof.name_ja):
            continue
        if not magi_hardening._jp_contains(current, proof.set_name_ja):
            continue
        proofs.append(proof)
    if len(proofs) != 1:
        return None, "", ""

    proof = proofs[0]
    series = source_finish._asia_series_for_set_id(proof.set_id)
    if not series or not proof.local_id:
        return None, "", ""
    card_text = source_text_get(f"data-asia/{series}/{proof.set_id}/{proof.local_id}.ts")
    if not card_text or not _pinned_variant_supported(card_text, special_variant):
        return None, "", ""

    identity = CommercialIdentity(
        name=proof.name_ja,
        set_name=proof.set_name_ja,
        number=f"{int(local)}/{int(denominator)}",
        language="ja",
        grader="PSA",
        grade="10",
        finish="reverse",
        variant=special_variant,
    )
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "", ""
    return identity, proof.card_id, proof.set_id


def recover_sensitive_variant_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    source_text_get: Callable[[str], Optional[str]] = standard_source._source_text,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != _EXPECTED_PRIOR_REASON:
        return original
    evidence = detail_coordinate._current_product_evidence(ask)
    identity, card_id, set_id = source_pinned_sensitive_variant_identity(
        evidence=evidence,
        source_text_get=source_text_get,
    )
    if identity is None:
        return original
    return native.MagiNativeResolution(
        "EXACT",
        "MAGI_NATIVE_TCGDEX_SOURCE_PINNED_EXACT_BALL_MIRROR_VARIANT",
        identity=identity,
        card_id=card_id,
        set_id=set_id,
    )


def _resolve_with_sensitive_variant_source(ask, **kwargs):
    assert _ORIGINAL_RESOLVER is not None
    original = _ORIGINAL_RESOLVER(ask, **kwargs)
    return recover_sensitive_variant_resolution(ask, original)


def install_global_marketplace_magi_sensitive_variant_source_proof() -> None:
    global _ORIGINAL_RESOLVER, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = native.resolve_magi_native_identity
    native.resolve_magi_native_identity = _resolve_with_sensitive_variant_source
    _INSTALLED = True
