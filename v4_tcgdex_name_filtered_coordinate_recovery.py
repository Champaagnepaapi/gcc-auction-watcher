from __future__ import annotations

"""Deterministically narrow denominator-coordinate ambiguity by exact card name.

The existing unique-coordinate fallback correctly refuses to choose between
multiple sets that share e.g. `53/102`, but it currently declares ambiguity
*before* asking whether those coordinates contain the exact listing card name.
This post-wrapper applies that already-existing exact name gate first and only
recovers when one candidate remains. No fuzzy matching, translation, substring,
Levenshtein or microvariant guessing is introduced.
"""

from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_unique_coordinate_fallback as unique


_TARGET_REASON = "TCGdex unique-coordinate printed number/denominator is not unique"
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None
_RESULT_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_INSTALLED = False


def _recover_exact_name_from_ambiguous_coordinate(
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
    left, denominator = canonical._canonical_number_parts(reference)
    if not (language_code and listing_name and left and denominator.isdigit()):
        return None
    expected_count = int(denominator)

    index = unique._set_index(language_code)
    if isinstance(index, canonical.CanonicalCard):
        return index

    candidate_sets: list[Mapping[str, Any]] = []
    for set_payload in index:
        if not unique._set_has_known_count(set_payload):
            # Preserve the original fail-closed contract when catalogue coverage
            # itself cannot prove denominator exclusion.
            return None
        if generalized._set_count_matches(set_payload, expected_count):
            candidate_sets.append(set_payload)

    if not candidate_sets or len(candidate_sets) > unique._MAX_NUMERIC_DENOMINATOR_SET_PROBES:
        return None

    exact_by_card_id: dict[str, canonical.CanonicalCard] = {}
    for set_payload in candidate_sets:
        set_id = str(set_payload.get("id") or "").strip()
        if not set_id:
            return None
        probed = unique._probe_exact_set_coordinate(
            lot,
            language_code=language_code,
            set_id=set_id,
            expected_count=expected_count,
        )
        if isinstance(probed, canonical.CanonicalCard):
            if probed.status == "ERROR":
                return probed
            continue
        if probed is None:
            continue

        resolved = unique._canonicalize_unique_card(
            lot,
            probed,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            expected_set_id=set_id,
            expected_count=expected_count,
        )
        if resolved is not None and resolved.status == "EXACT":
            exact_by_card_id[resolved.card_id] = resolved
            if len(exact_by_card_id) > 1:
                return None

    if len(exact_by_card_id) != 1:
        return None
    return next(iter(exact_by_card_id.values()))


def _resolve_with_name_filtered_coordinate(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    _, _, _, _, _, key = generalized._lot_components(lot)

    cached = _RESULT_CACHE.get(key)
    if cached is not None:
        canonical._DIAGNOSTICS.tcgdex_exact += 1
        return cached
    if key in _NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "AMBIGUOUS" or original.reason != _TARGET_REASON:
        return original

    recovered = _recover_exact_name_from_ambiguous_coordinate(lot)
    if recovered is None:
        _NEGATIVE_CACHE.add(key)
        return original
    if recovered.status == "ERROR":
        return recovered
    if recovered.status != "EXACT":
        return original

    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_ambiguous > 0:
        diagnostics.tcgdex_ambiguous -= 1
    diagnostics.tcgdex_exact += 1
    _RESULT_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RESULT_CACHE.clear()
    _NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_name_filtered_coordinate_recovery() -> None:
    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = canonical.resolve_tcgdex_card
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    canonical.resolve_tcgdex_card = _resolve_with_name_filtered_coordinate
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
    _INSTALLED = True
