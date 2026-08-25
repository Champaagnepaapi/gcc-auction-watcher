"""Exact source-pinned recovery for Magi Poke Ball / Master Ball mirror cards.

The normal Magi preflight intentionally blocks material variant claims. This
wrapper keeps that default and recovers only the two ball-mirror classes already
represented by the V4 detailed-variant contract when immutable TCGdex source
proof makes every material axis deterministic.

The PR-only rejection diagnostic can emit a bounded stage enum for failed ball
mirror proof. It never logs body text, source payloads, credentials or prices.
"""
from __future__ import annotations

import os
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
_ITEM_URL_RE = re.compile(r"^https://magi\.camp/items/\d+(?:[/?#].*)?$", re.I)
_EXPECTED_PRIOR_REASON = "sensitive_variant_unproven"
_DIAGNOSTICS_ENABLED = os.getenv("GLOBAL_MAGI_REJECTION_DIAGNOSTICS", "false").strip().lower() in {
    "1", "true", "yes"
}
_SOURCE_MAX_REQUESTS = max(
    0, int(os.getenv("GLOBAL_MAGI_SENSITIVE_SOURCE_MAX_REQUESTS", "8"))
)
_SOURCE_REQUESTS = 0
_SOURCE_CACHE: dict[str, Optional[str]] = {}
_ORIGINAL_RESOLVER = None
_INSTALLED = False


def clear_sensitive_source_runtime_state() -> None:
    global _SOURCE_REQUESTS
    _SOURCE_REQUESTS = 0
    _SOURCE_CACHE.clear()


def _source_text(path: str) -> Optional[str]:
    """Bounded immutable-source getter dedicated to sensitive variants."""
    global _SOURCE_REQUESTS
    if path in _SOURCE_CACHE:
        return _SOURCE_CACHE[path]
    if _SOURCE_REQUESTS >= _SOURCE_MAX_REQUESTS:
        return None
    _SOURCE_REQUESTS += 1
    try:
        response = source_finish._SESSION.get(
            f"{source_finish._SOURCE_RAW_BASE}/{path}",
            timeout=source_finish._SOURCE_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        if status == 404:
            _SOURCE_CACHE[path] = None
        return None
    text = str(getattr(response, "text", "") or "")
    if not text or len(text) > 250_000:
        return None
    _SOURCE_CACHE[path] = text
    return text


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
    values: list[str] = []
    seen: set[str] = set()
    for match in _SET_TOKEN_RE.finditer(normalized):
        token = match.group(1).strip()
        upper = token.upper()
        if upper.startswith("PSA"):
            continue
        key = token.casefold()
        if key not in seen:
            seen.add(key)
            values.append(token)
    return tuple(values)


def _first_line(evidence: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(evidence or ""))
    lines = normalized.splitlines()
    return lines[0].strip() if lines else normalized.strip()


def _full_number_for_sensitive(evidence: str) -> str:
    """Prefer exact title coordinate before bounded body fallback."""
    first = _first_line(evidence)
    full_number, _ = detail_coordinate._full_number_from_evidence(first)
    if full_number:
        return full_number

    full_number, reason = detail_coordinate._full_number_from_evidence(evidence)
    if full_number:
        return full_number
    if reason == "collector_number_ambiguous":
        line_number, _line_set, _ = detail_coordinate._line_scoped_explicit_coordinate(evidence)
        return line_number
    return ""


def _set_tokens_for_sensitive(evidence: str) -> tuple[str, ...]:
    """Prefer exact title set token; fall back to bounded product evidence."""
    first_tokens = _set_tokens(_first_line(evidence))
    if first_tokens:
        return first_tokens
    return _set_tokens(evidence)


def _pinned_variant_supported(card_text: str, special_variant: str) -> bool:
    foil = {"poke_ball": "pokeball", "master_ball": "masterball"}.get(special_variant)
    if not foil:
        return False
    return bool(
        re.search(
            rf"\btype\s*:\s*['\"]reverse['\"][\s\S]{{0,180}}?\bfoil\s*:\s*['\"]{foil}['\"]",
            card_text,
            re.IGNORECASE,
        )
    )


def _resolve_sensitive_variant_identity(
    *,
    evidence: str,
    source_text_get: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[Optional[CommercialIdentity], str, str, str]:
    """Return exact identity plus a bounded diagnostic stage enum."""
    source_text_get = source_text_get or _source_text
    current = japan.current_text(evidence)
    _marker, special_variant = _variant_marker(current)
    if not special_variant:
        return None, "", "", "variant_marker_or_conflict_unproven"

    full_number = _full_number_for_sensitive(current)
    if not full_number or "/" not in full_number:
        return None, "", "", "full_number_unproven"
    local, denominator = full_number.split("/", 1)
    if not local.isdigit() or not denominator.isdigit():
        return None, "", "", "numeric_coordinate_unproven"

    set_tokens = _set_tokens_for_sensitive(current)
    if len(set_tokens) != 1:
        return None, "", "", f"set_token_count_{len(set_tokens)}"

    proofs = {}
    for set_code in set_tokens:
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
        key = (proof.card_id, proof.set_id.casefold(), str(proof.local_id))
        proofs[key] = proof
    if len(proofs) != 1:
        return None, "", "", f"source_coordinate_proof_count_{len(proofs)}"

    proof = next(iter(proofs.values()))
    series = source_finish._asia_series_for_set_id(proof.set_id)
    if not series or not proof.local_id:
        return None, "", "", "source_series_or_local_unproven"
    card_text = source_text_get(f"data-asia/{series}/{proof.set_id}/{proof.local_id}.ts")
    if not card_text:
        return None, "", "", "source_card_text_unavailable"
    if not _pinned_variant_supported(card_text, special_variant):
        return None, "", "", "source_requested_foil_unproven"

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
        return None, "", "", "commercial_identity_incomplete"
    return identity, proof.card_id, proof.set_id, "exact"


def source_pinned_sensitive_variant_identity(
    *,
    evidence: str,
    source_text_get: Optional[Callable[[str], Optional[str]]] = None,
) -> tuple[Optional[CommercialIdentity], str, str]:
    identity, card_id, set_id, _reason = _resolve_sensitive_variant_identity(
        evidence=evidence,
        source_text_get=source_text_get,
    )
    return identity, card_id, set_id


def recover_sensitive_variant_resolution(
    ask: japan.Ask,
    original: native.MagiNativeResolution,
    *,
    source_text_get: Optional[Callable[[str], Optional[str]]] = None,
) -> native.MagiNativeResolution:
    if original.status != "NO_MATCH" or original.reason != _EXPECTED_PRIOR_REASON:
        return original
    evidence = detail_coordinate._current_product_evidence(ask)
    identity, card_id, set_id, diagnostic = _resolve_sensitive_variant_identity(
        evidence=evidence,
        source_text_get=source_text_get,
    )
    if identity is None:
        if _DIAGNOSTICS_ENABLED and _ITEM_URL_RE.fullmatch(str(ask.url or "").strip()):
            print(
                f"[MAGI_VARIANT_DIAG] reason={diagnostic} | url={str(ask.url).strip()}",
                flush=True,
            )
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
