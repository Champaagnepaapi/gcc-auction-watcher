from __future__ import annotations

"""Recover TCGdex Rainbow display suffixes only with explicit foil proof.

GCC can append ``Rainbow`` to a card's display name while TCGdex keeps the base
card name and records the material variant in ``variants_detailed`` as
``type=holo, foil=rainbow``. This layer is deliberately narrower than a generic
name alias:

- the localized GCC set label must resolve to exactly one TCGdex set;
- printed localId and numeric denominator remain exact;
- the TCGdex base card name must equal the GCC name with one trailing Rainbow
  token removed;
- the exact TCGdex card payload must independently prove a rainbow holo foil;
- the sanitized detailed variant payload is carried forward so downstream
  provider gates can require the same ``special_finish=rainbow``.

No ASK/SOLD semantics, valuation, provider budget or transaction behavior is
changed here.
"""

from dataclasses import replace
import re
from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_raw_consensus as raw_consensus
import v4_tcgdex_detailed_variants as detailed
import v4_tcgdex_generalized_coordinate_recovery as generalized


_RAINBOW_TOKEN = "rainbow"
_RAINBOW_PATTERN = r"\brainbow\b"
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None
_ORIGINAL_DECOMPOSE_VARIANT = None
_INSTALLED = False
_DIMENSIONS_INSTALLED = False
_RESULT_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()


def _rainbow_base_name(listing_name: object) -> str:
    normalized = canonical._normalize(listing_name)
    token = canonical._normalize(_RAINBOW_TOKEN)
    suffix = f" {token}"
    if not normalized or not token or not normalized.endswith(suffix):
        return ""
    return normalized[: -len(suffix)].strip()


def _rainbow_detail_proven(
    card: Mapping[str, Any], *, language_code: str
) -> tuple[bool, str, tuple[Mapping[str, object], ...]]:
    state, entries = detailed.sanitize_variants_detailed(
        card.get("variants_detailed"), language_code=language_code
    )
    if state != "USABLE":
        return False, state, entries
    proven = any(
        str(entry.get("type") or "") == "holo"
        and _RAINBOW_TOKEN in tuple(str(value) for value in (entry.get("foil") or ()))
        for entry in entries
    )
    return proven, state, entries


def _attach_rainbow_detail(
    result: canonical.CanonicalCard,
    *,
    state: str,
    entries: tuple[Mapping[str, object], ...],
) -> canonical.CanonicalCard:
    variants = dict(result.variants) if isinstance(result.variants, Mapping) else {}
    variants[detailed.DETAILED_SCHEMA_KEY] = detailed.DETAILED_SCHEMA_VERSION
    variants[detailed.DETAILED_STATE_KEY] = state
    variants[detailed.DETAILED_ENTRIES_KEY] = entries
    return replace(result, variants=variants)


def _decompose_variant_with_rainbow(variant_str: str):
    assert _ORIGINAL_DECOMPOSE_VARIANT is not None
    result = dict(_ORIGINAL_DECOMPOSE_VARIANT(variant_str))
    if not re.search(_RAINBOW_PATTERN, raw_consensus.normalize_text(variant_str)):
        return result
    existing = result.get("special_finish")
    if existing and existing != _RAINBOW_TOKEN:
        result["special_finish"] = "__conflict__"
    else:
        result["special_finish"] = _RAINBOW_TOKEN
    return result


def _install_rainbow_dimension_support() -> None:
    """Teach existing commercial gates one explicit, source-backed microvariant."""
    global _DIMENSIONS_INSTALLED, _ORIGINAL_DECOMPOSE_VARIANT
    if _DIMENSIONS_INSTALLED:
        return

    watcher.COMMERCIAL_DIMENSION_PATTERNS.setdefault("special_finish", {})[
        _RAINBOW_TOKEN
    ] = _RAINBOW_PATTERN
    raw_consensus.MULTILINGUAL_DIMENSION_PATTERNS.setdefault("special_finish", {})[
        _RAINBOW_TOKEN
    ] = _RAINBOW_PATTERN
    detailed._SPECIAL_FINISH_BY_FOIL[_RAINBOW_TOKEN] = _RAINBOW_TOKEN

    current = raw_consensus.decompose_commercial_variant
    if not getattr(current, "_v4_tcgdex_rainbow_variant", False):
        _ORIGINAL_DECOMPOSE_VARIANT = current
        _decompose_variant_with_rainbow._v4_tcgdex_rainbow_variant = True  # type: ignore[attr-defined]
        raw_consensus.decompose_commercial_variant = _decompose_variant_with_rainbow

    _DIMENSIONS_INSTALLED = True


def _recover_rainbow_from_exact_set_name(
    lot: watcher.Lot,
) -> canonical.CanonicalCard | None:
    (
        language_code,
        listing_set,
        reference,
        listing_name,
        _,
        _,
    ) = generalized._lot_components(lot)
    base_name = _rainbow_base_name(listing_name)
    if not (language_code and listing_set and reference and base_name):
        return None

    try:
        status, payload, _ = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets",
            params={"name": f"eq:{listing_set}"},
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        return canonical.CanonicalCard(
            "ERROR", reason=f"TCGdex rainbow exact-set {type(error).__name__}"
        )
    if status != 200:
        if generalized._transient_status(status):
            return canonical.CanonicalCard(
                "ERROR", reason=f"TCGdex rainbow exact-set transient HTTP {status}"
            )
        return None

    sets = canonical._extract_list_payload(payload)
    if len(sets) != 1:
        return None
    set_id = str(sets[0].get("id") or "").strip()
    if not set_id:
        return canonical.CanonicalCard(
            "ERROR", reason="TCGdex rainbow exact-set malformed set"
        )

    for local_id in generalized._reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets/{set_id}/{local_id}",
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return canonical.CanonicalCard(
                "ERROR", reason=f"TCGdex rainbow coordinate {type(error).__name__}"
            )
        if status == 404:
            continue
        if status != 200:
            if generalized._transient_status(status):
                return canonical.CanonicalCard(
                    "ERROR", reason=f"TCGdex rainbow coordinate transient HTTP {status}"
                )
            return None

        card = canonical._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            return canonical.CanonicalCard(
                "ERROR", reason="TCGdex rainbow coordinate invalid payload"
            )

        proven, detail_state, detail_entries = _rainbow_detail_proven(
            card, language_code=language_code
        )
        if not proven:
            return None

        result = generalized._canonical_from_coordinate(
            lot,
            card,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=base_name,
            expected_set_id=set_id,
            expected_count=None,
            allow_localized_name_mismatch=False,
        )
        if result is None:
            return None
        return _attach_rainbow_detail(
            result,
            state=detail_state,
            entries=detail_entries,
        )
    return None


def _reclassify_original_no_match(result: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    if result.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif result.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _resolve_with_rainbow_variant_recovery(
    lot: watcher.Lot,
) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    _, _, _, _, _, key = generalized._lot_components(lot)

    cached = _RESULT_CACHE.get(key)
    if cached is not None:
        canonical._DIAGNOSTICS.tcgdex_exact += 1
        return cached
    if key in _NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "NO_MATCH" or not _rainbow_base_name(
        watcher.extract_card_identity(lot).get("core") or ""
    ):
        return original

    recovered = _recover_rainbow_from_exact_set_name(lot)
    if recovered is None:
        _NEGATIVE_CACHE.add(key)
        return original
    if recovered.status in {"EXACT", "ERROR"}:
        _reclassify_original_no_match(recovered)
    if recovered.status == "EXACT":
        _RESULT_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RESULT_CACHE.clear()
    _NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_rainbow_variant_recovery() -> None:
    """Install exact Rainbow foil recovery after detailed-variant support."""
    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE, _INSTALLED
    if _INSTALLED:
        return

    _install_rainbow_dimension_support()
    _ORIGINAL_RESOLVER = canonical.resolve_tcgdex_card
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    canonical.resolve_tcgdex_card = _resolve_with_rainbow_variant_recovery
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
    _INSTALLED = True
