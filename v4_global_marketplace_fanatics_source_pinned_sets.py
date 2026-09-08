"""Fanatics-only source-pinned Japanese set namespaces.

Current Fanatics Buy Now H1s sometimes expose a Japanese card as an English/
romanized set label plus a bare local collector number.  The shared Japanese
alias registry cannot safely carry these numerator-only provider labels because
it is also consumed by Magi and other V4 paths.

This layer therefore scopes three independently reviewed TCGdex set bridges to
one Fanatics resolution call only.  When one reviewed set phrase is explicitly
present in the provider H1, it also collapses generic parser partitions to one
bounded source-set candidate whose card name is the provider text between that
set phrase and the exact collector number after stripping only leading material
display tokens (Holo/Reverse/Poke Ball/Master Ball).  This prevents multiple
synthetic name partitions from becoming separate exact identities merely because
the Japanese source alias intentionally tolerates localized-name mismatch.

The existing V4 canonical resolver still performs the exact set/localId read and
revalidates the source-pinned official set count; all downstream Fanatics
language, grade, explicit full-fraction, finish/edition and ambiguity gates remain
unchanged.  No alias or generalized resolver cache entry leaks outside the one
synchronous Fanatics resolution call.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
import re
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
_LEADING_DISPLAY_RE = re.compile(
    r"^(?:(?:MASTER\s*BALL|MASTERBALL|POK[EÉ]\s*BALL|POKEBALL|"
    r"REVERSE\s+HOLO|REVERSE|NON[-\s]?HOLO|HOLO)\b[\s\-:|/]*)+",
    re.IGNORECASE,
)
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


def _source_card_name(title: str, alias, local_id: str) -> str:
    """Extract one bounded provider card name after an exact reviewed set phrase."""
    raw = str(title or "")
    phrase_pattern = re.compile(
        r"\s+".join(re.escape(token) for token in str(alias.listing_set).split()),
        re.IGNORECASE,
    )
    phrase_matches = list(phrase_pattern.finditer(raw))
    if len(phrase_matches) != 1:
        return ""

    normalized_local = v1._norm_local(local_id)
    if not normalized_local or not normalized_local.isdigit():
        return ""
    number_pattern = re.compile(
        rf"(?<![A-Za-z0-9])#\s*0*{re.escape(normalized_local)}(?![A-Za-z0-9])",
        re.IGNORECASE,
    )
    tail = raw[phrase_matches[0].end() :]
    number_matches = list(number_pattern.finditer(tail))
    if len(number_matches) != 1:
        return ""

    segment = tail[: number_matches[0].start()].strip(" -|:/")
    previous = None
    while segment and segment != previous:
        previous = segment
        segment = _LEADING_DISPLAY_RE.sub("", segment, count=1).strip(" -|:/")
    return segment if v1._norm(segment) else ""


def _source_candidates(title: str, candidates):
    """Prefer one exact reviewed provider-set partition when it is provable."""
    output = list(candidates)
    matching_aliases = [
        alias for alias in _SOURCE_ALIASES if _phrase_present(title, alias.listing_set)
    ]
    if len(matching_aliases) != 1:
        return output

    alias = matching_aliases[0]
    japanese_rows = [
        row
        for row in candidates
        if row.language_code == "ja" and row.name and row.local_id
    ]
    if not japanese_rows:
        return output

    # Generic candidate partitions may differ in set/name only.  The provider
    # grade/localId/material dimensions must still agree before source collapse.
    metadata = {
        (
            row.language_code,
            row.language_label,
            row.local_id,
            row.grade,
            row.edition,
            row.finish,
            row.variant,
        )
        for row in japanese_rows
    }
    if len(metadata) != 1:
        return output

    row = japanese_rows[0]
    card_name = _source_card_name(title, alias, row.local_id)
    if not card_name:
        return output

    # For a reviewed explicit set phrase, returning only this deterministic
    # partition is stricter than carrying generic parser alternatives alongside
    # an alias that intentionally permits localized-name mismatch.
    return [replace(row, set_name=alias.listing_set, name=card_name)]


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
