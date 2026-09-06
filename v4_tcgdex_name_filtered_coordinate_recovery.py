from __future__ import annotations

"""Narrow denominator-coordinate ambiguity with a constrained card-name bridge.

The exact coordinate remains the authority: listing language + printed localId +
printed denominator must already resolve to a bounded set of TCGdex cards, and
exactly one compatible card may remain. Card-name spelling is allowed to differ
only narrowly (punctuation/possessive spelling or a very small typo). This layer
never translates names, never uses substring containment, and never relaxes the
downstream grader, grade, language, variant or microvariant gates.
"""

from difflib import SequenceMatcher
import re
from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_unique_coordinate_fallback as unique


_TARGET_REASON = "TCGdex unique-coordinate printed number/denominator is not unique"
_MIN_SINGLE_TOKEN_RATIO = 0.85
_MIN_MULTI_TOKEN_RATIO = 0.90
_MAX_LENGTH_DELTA = 2
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None
_RESULT_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_INSTALLED = False


def _relaxed_name_tokens(value: object) -> tuple[str, ...]:
    """Normalize spelling noise without translating or dropping semantic words."""
    tokens = tuple(token for token in canonical._normalize(value).split() if token)
    # Unicode/ASCII possessives normalize to a standalone ``s`` token:
    # "Brock's Ninetales" -> ("brock", "s", "ninetales").
    # Dropping only that one-character possessive marker makes it equivalent to
    # GCC's common "Brock Ninetales" spelling without deleting normal words.
    return tuple(token for token in tokens if token != "s")


def _numeric_name_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(token for token in tokens if re.fullmatch(r"\d+(?:\.\d+)?", token))


def _approximate_name_equivalent(listing_name: object, provider_name: object) -> bool:
    """Return True only for very close spellings of the same card name.

    This is intentionally not a general fuzzy search. It is used only *after*
    exact TCGdex coordinate/language proof and uniqueness is still mandatory.
    Numeric tokens must agree exactly so e.g. form/number labels cannot drift.
    """
    left_tokens = _relaxed_name_tokens(listing_name)
    right_tokens = _relaxed_name_tokens(provider_name)
    if not left_tokens or not right_tokens:
        return False
    if left_tokens == right_tokens:
        return True
    if _numeric_name_tokens(left_tokens) != _numeric_name_tokens(right_tokens):
        return False
    if len(left_tokens) != len(right_tokens):
        return False

    left = " ".join(left_tokens)
    right = " ".join(right_tokens)
    if abs(len(left) - len(right)) > _MAX_LENGTH_DELTA:
        return False

    # For multi-token names, require at least one substantial token to match
    # exactly. This catches tiny spelling noise around a proven coordinate while
    # avoiding broad semantic substitutions such as Brock's Ninetales -> Brock's
    # Rhydon. Single-token Pokemon names can tolerate one small typo because the
    # exact coordinate/language and unique-candidate gates already anchor identity.
    if len(left_tokens) > 1:
        exact_substantial = any(
            a == b and len(a) >= 3 for a, b in zip(left_tokens, right_tokens)
        )
        if not exact_substantial:
            return False
        threshold = _MIN_MULTI_TOKEN_RATIO
    else:
        if min(len(left), len(right)) < 5:
            return False
        threshold = _MIN_SINGLE_TOKEN_RATIO

    return SequenceMatcher(None, left, right, autojunk=False).ratio() >= threshold


def _canonicalize_name_compatible_candidate(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    expected_set_id: str,
    expected_count: int,
) -> canonical.CanonicalCard | None:
    """Preserve exact-name/localized behavior, then allow one constrained bridge."""
    exact = unique._canonicalize_unique_card(
        lot,
        card,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=expected_set_id,
        expected_count=expected_count,
    )
    if exact is not None:
        return exact

    provider_name = str(card.get("name") or "").strip()
    if not _approximate_name_equivalent(listing_name, provider_name):
        return None

    # Name equivalence was established above. All material coordinate checks are
    # still repeated by the canonical coordinate builder. Downstream commercial
    # identity/variant/grader/grade gates remain untouched.
    return generalized._canonical_from_coordinate(
        lot,
        card,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=expected_set_id,
        expected_count=expected_count,
        allow_localized_name_mismatch=True,
    )


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
            # Preserve fail-closed behavior when catalogue coverage itself cannot
            # prove denominator exclusion.
            return None
        if generalized._set_count_matches(set_payload, expected_count):
            candidate_sets.append(set_payload)

    if not candidate_sets or len(candidate_sets) > unique._MAX_NUMERIC_DENOMINATOR_SET_PROBES:
        return None

    compatible_by_card_id: dict[str, canonical.CanonicalCard] = {}
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

        resolved = _canonicalize_name_compatible_candidate(
            lot,
            probed,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            expected_set_id=set_id,
            expected_count=expected_count,
        )
        if resolved is not None and resolved.status == "EXACT":
            compatible_by_card_id[resolved.card_id] = resolved
            # Fuzzy/exact name may narrow candidates, but it may never choose
            # between two still-compatible TCGdex cards.
            if len(compatible_by_card_id) > 1:
                return None

    if len(compatible_by_card_id) != 1:
        return None
    return next(iter(compatible_by_card_id.values()))


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
