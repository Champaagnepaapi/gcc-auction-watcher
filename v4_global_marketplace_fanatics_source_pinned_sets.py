"""Fanatics-only source-pinned Japanese set namespaces.

Current Fanatics Buy Now H1s sometimes expose a Japanese card as an English/
romanized set label plus a bare local collector number.  The shared Japanese
alias registry cannot safely carry these numerator-only provider labels because
it is also consumed by Magi and other V4 paths.

This layer therefore scopes three independently reviewed TCGdex set bridges to
one Fanatics resolution call only.  It never leaves an alias or generalized
resolver cache entry behind.  The existing V4 canonical resolver still performs
the exact set/localId read and revalidates the source-pinned official set count;
all downstream Fanatics language, grade, explicit full-fraction, finish/edition
and ambiguity gates remain unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterator

import v4_global_fanatics_native_identity as v1
import v4_global_marketplace_fanatics_native_v3 as v3
import v4_tcgdex_generalized_coordinate_recovery as generalized


_SOURCE_PIN = "af33c9ac882e2acfadffaf19e8083aa976d12983"
_SOURCE_ALIASES = (
    generalized.ExactSetAlias(
        "ja",
        "Scarlet & Violet 151",
        "SV2a",
        165,
        allow_localized_name_mismatch=True,
        provenance=(
            f"TCGdex source pin {_SOURCE_PIN} data-asia/SV/SV2a.ts + exact card path; "
            "Fanatics Japanese Scarlet & Violet 151 label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "Web 1st Edition",
        "web1",
        48,
        allow_localized_name_mismatch=True,
        provenance=(
            f"TCGdex source pin {_SOURCE_PIN} data-asia/web/web1.ts + exact card path; "
            "Fanatics Japanese Web 1st Edition label"
        ),
    ),
    generalized.ExactSetAlias(
        "ja",
        "SV Glory Of The Rocket Gang",
        "SV10",
        98,
        allow_localized_name_mismatch=True,
        provenance=(
            f"TCGdex source pin {_SOURCE_PIN} data-asia/SV/SV10.ts + exact card path; "
            "Fanatics Japanese SV Glory Of The Rocket Gang label"
        ),
    ),
)
_ALIAS_BY_LABEL = {
    generalized._norm_text(alias.listing_set): alias for alias in _SOURCE_ALIASES
}
_ORIGINAL_CANDIDATES = None
_ORIGINAL_RESOLVE_COORDINATE = None
_INSTALLED = False


def _phrase_present(text: str, phrase: str) -> bool:
    haystack = f" {v1._norm(text)} "
    needle = f" {v1._norm(phrase)} "
    return bool(needle.strip()) and needle in haystack


def _alias_for_coordinate(coordinate: v1.FanaticsNativeCoordinate):
    if coordinate.language_code != "ja":
        return None
    return _ALIAS_BY_LABEL.get(generalized._norm_text(coordinate.set_name))


def _source_candidates(title: str, candidates):
    """Add only exact reviewed provider-set partitions; never invent a card name."""
    output = list(candidates)
    seen = {
        (v1._norm(row.set_name), v1._norm(row.name), row.local_id)
        for row in output
    }
    for alias in _SOURCE_ALIASES:
        if not _phrase_present(title, alias.listing_set):
            continue
        # Reuse card-name/localId/grade/dimensions already parsed from the H1.
        # This only repairs the set partition when finish tokens were absorbed
        # into it (e.g. "151 Master Ball Reverse Holo Pikachu #025").
        for row in tuple(candidates):
            if row.language_code != "ja" or not row.name or not row.local_id:
                continue
            candidate = replace(row, set_name=alias.listing_set)
            key = (v1._norm(candidate.set_name), v1._norm(candidate.name), candidate.local_id)
            if key in seen:
                continue
            seen.add(key)
            output.append(candidate)
            if len(output) >= v3._MAX_CANDIDATES:
                return output
    return output


def _candidates_with_source_sets(title: str):
    assert _ORIGINAL_CANDIDATES is not None
    candidates, reason = _ORIGINAL_CANDIDATES(title)
    expanded = _source_candidates(title, candidates)
    return expanded, reason


@contextmanager
def _scoped_alias(alias, lot) -> Iterator[bool]:
    """Expose one alias only during one synchronous Fanatics resolver call."""
    alias_key = generalized._alias_key(alias.language_code, alias.listing_set)
    existing_alias = generalized._SET_ALIASES_BY_KEY.get(alias_key)
    if existing_alias is not None and existing_alias != alias:
        # A conflicting global mapping is never overridden.
        yield False
        return

    *_, cache_key = generalized._lot_components(lot)
    old_positive = generalized._RECOVERY_CACHE.pop(cache_key, None)
    old_negative = cache_key in generalized._RECOVERY_NEGATIVE_CACHE
    generalized._RECOVERY_NEGATIVE_CACHE.discard(cache_key)
    generalized._SET_ALIASES_BY_KEY[alias_key] = alias
    try:
        yield True
    finally:
        # Do not leak Fanatics-only identity into another provider via caches.
        generalized._RECOVERY_CACHE.pop(cache_key, None)
        generalized._RECOVERY_NEGATIVE_CACHE.discard(cache_key)
        if old_positive is not None:
            generalized._RECOVERY_CACHE[cache_key] = old_positive
        if old_negative:
            generalized._RECOVERY_NEGATIVE_CACHE.add(cache_key)
        if existing_alias is None:
            generalized._SET_ALIASES_BY_KEY.pop(alias_key, None)
        else:
            generalized._SET_ALIASES_BY_KEY[alias_key] = existing_alias


def _resolve_coordinate_with_source_set(
    coordinate: v1.FanaticsNativeCoordinate,
    *,
    title: str,
    proof_text: str,
    resolver,
):
    assert _ORIGINAL_RESOLVE_COORDINATE is not None
    alias = _alias_for_coordinate(coordinate)
    if alias is None:
        return _ORIGINAL_RESOLVE_COORDINATE(
            coordinate, title=title, proof_text=proof_text, resolver=resolver
        )

    lot = v1._lot_for_coordinate(coordinate)
    with _scoped_alias(alias, lot) as installed:
        if not installed:
            return None, "tcgdex_fanatics_source_alias_conflict"
        return _ORIGINAL_RESOLVE_COORDINATE(
            coordinate, title=title, proof_text=proof_text, resolver=resolver
        )


def install_global_marketplace_fanatics_source_pinned_sets() -> None:
    """Install before provider-language recovery captures the v3 resolver."""
    global _ORIGINAL_CANDIDATES, _ORIGINAL_RESOLVE_COORDINATE, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_CANDIDATES = v3.fanatics_coordinate_candidates_v3
    _ORIGINAL_RESOLVE_COORDINATE = v3._resolve_coordinate_v3
    v3.fanatics_coordinate_candidates_v3 = _candidates_with_source_sets
    v3._resolve_coordinate_v3 = _resolve_coordinate_with_source_set
    _INSTALLED = True
