from __future__ import annotations

import re
from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized


# This fallback runs only after every existing exact/alias TCGdex path returned
# NO_MATCH. It never guesses a set name or translates a card name. A coordinate
# must be globally unique in the listing language under one of the bounded
# proofs below, otherwise the result remains NO_MATCH/AMBIGUOUS.
_MAX_NUMERIC_DENOMINATOR_SET_PROBES = 16
_MAX_ALPHANUMERIC_LOCALID_BRIEFS = 16

_SET_INDEX_CACHE: dict[str, tuple[Mapping[str, Any], ...]] = {}
_RESULT_CACHE: dict[
    tuple[str, str, str, str, int], canonical.CanonicalCard
] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None

_LOCALIZED_SCRIPT_PATTERNS = {
    "ja": re.compile(r"[\u3040-\u30ff\u3400-\u9fff]"),
    "ko": re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]"),
    "zh-tw": re.compile(r"[\u3400-\u9fff]"),
    "th": re.compile(r"[\u0e00-\u0e7f]"),
}


def _error(reason: str) -> canonical.CanonicalCard:
    return canonical.CanonicalCard("ERROR", reason=reason)


def _ambiguous(reason: str) -> canonical.CanonicalCard:
    return canonical.CanonicalCard("AMBIGUOUS", reason=reason)


def _set_index(
    language_code: str,
) -> tuple[Mapping[str, Any], ...] | canonical.CanonicalCard:
    cached = _SET_INDEX_CACHE.get(language_code)
    if cached is not None:
        return cached
    try:
        status, payload, _ = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets",
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return _error(f"TCGdex unique-coordinate set index {type(exc).__name__}")
    if status == 404:
        return ()
    if status != 200:
        return _error(f"TCGdex unique-coordinate set index HTTP {status}")

    sets = tuple(canonical._extract_list_payload(payload))
    for set_payload in sets:
        if not str(set_payload.get("id") or "").strip():
            return _error("TCGdex unique-coordinate malformed set index")
    _SET_INDEX_CACHE[language_code] = sets
    return sets


def _set_has_known_count(set_payload: Mapping[str, Any]) -> bool:
    counts = set_payload.get("cardCount")
    if not isinstance(counts, Mapping):
        return False
    for value in (counts.get("official"), counts.get("total")):
        try:
            int(str(value).strip())
        except (TypeError, ValueError):
            continue
        return True
    return False


def _raw_card_matches_coordinate(
    card: Mapping[str, Any],
    *,
    expected_set_id: str,
    reference: str,
    expected_count: int | None,
) -> bool:
    card_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    set_payload = card.get("set")
    if not card_id or not local_id or not isinstance(set_payload, Mapping):
        return False
    set_id = str(set_payload.get("id") or "").strip()
    if set_id != expected_set_id or not generalized._same_local_id(local_id, reference):
        return False

    _, denominator = canonical._canonical_number_parts(reference)
    if denominator.isdigit() and not canonical._denominator_matches(card, denominator):
        return False
    if expected_count is not None and not generalized._set_count_matches(
        set_payload, expected_count
    ):
        return False
    return True


def _probe_exact_set_coordinate(
    lot: watcher.Lot,
    *,
    language_code: str,
    set_id: str,
    expected_count: int | None,
) -> Mapping[str, Any] | canonical.CanonicalCard | None:
    identity = watcher.extract_card_identity(lot)
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    for local_id in generalized._reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets/{set_id}/{local_id}",
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return _error(
                f"TCGdex unique-coordinate set/localId {type(exc).__name__}"
            )
        if status == 404:
            continue
        if status != 200:
            return _error(f"TCGdex unique-coordinate set/localId HTTP {status}")
        card = canonical._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            return _error("TCGdex unique-coordinate invalid card payload")
        if not _raw_card_matches_coordinate(
            card,
            expected_set_id=set_id,
            reference=reference,
            expected_count=expected_count,
        ):
            return _error("TCGdex unique-coordinate inconsistent card payload")
        return card
    return None


def _localized_name_bridge_allowed(
    language_code: str,
    listing_name: str,
    card: Mapping[str, Any],
) -> bool:
    """Permit a script bridge only when direct name comparison is impossible.

    A same-script disagreement is a material conflict and remains blocked. This
    is deliberately narrower than a translation table: no translation is done.
    """

    pattern = _LOCALIZED_SCRIPT_PATTERNS.get(language_code)
    if pattern is None:
        return False
    provider_name = str(card.get("name") or "").strip()
    if not provider_name:
        return False
    return bool(pattern.search(provider_name)) and not bool(pattern.search(listing_name))


def _canonicalize_unique_card(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    expected_set_id: str,
    expected_count: int | None,
) -> canonical.CanonicalCard | None:
    allow_localized_name_mismatch = False
    if not generalized._card_name_compatible(listing_name, card):
        if not _localized_name_bridge_allowed(language_code, listing_name, card):
            return None
        allow_localized_name_mismatch = True
    return generalized._canonical_from_coordinate(
        lot,
        card,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=expected_set_id,
        expected_count=expected_count,
        allow_localized_name_mismatch=allow_localized_name_mismatch,
    )


def _recover_numeric_denominator(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    reference: str,
    denominator: str,
) -> canonical.CanonicalCard | None:
    try:
        expected_count = int(denominator)
    except (TypeError, ValueError):
        return None

    index = _set_index(language_code)
    if isinstance(index, canonical.CanonicalCard):
        return index

    candidate_sets: list[Mapping[str, Any]] = []
    for set_payload in index:
        if not _set_has_known_count(set_payload):
            # Without a set count this set cannot be excluded from a global
            # denominator-uniqueness proof. Fail closed instead of skipping it.
            return _error("TCGdex unique-coordinate set index missing cardCount")
        if generalized._set_count_matches(set_payload, expected_count):
            candidate_sets.append(set_payload)

    if not candidate_sets:
        return None
    if len(candidate_sets) > _MAX_NUMERIC_DENOMINATOR_SET_PROBES:
        return _ambiguous(
            "TCGdex unique-coordinate too many sets share printed denominator"
        )

    coordinate_matches: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for set_payload in candidate_sets:
        set_id = str(set_payload.get("id") or "").strip()
        probed = _probe_exact_set_coordinate(
            lot,
            language_code=language_code,
            set_id=set_id,
            expected_count=expected_count,
        )
        if isinstance(probed, canonical.CanonicalCard):
            return probed
        if probed is None:
            continue
        card_id = str(probed.get("id") or "").strip()
        coordinate_matches[card_id] = (set_id, probed)

    if not coordinate_matches:
        return None
    if len(coordinate_matches) > 1:
        return _ambiguous(
            "TCGdex unique-coordinate printed number/denominator is not unique"
        )

    set_id, card = next(iter(coordinate_matches.values()))
    return _canonicalize_unique_card(
        lot,
        card,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=set_id,
        expected_count=expected_count,
    )


def _recover_namespace_coordinate(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    reference: str,
    namespace: str,
) -> canonical.CanonicalCard | None:
    index = _set_index(language_code)
    if isinstance(index, canonical.CanonicalCard):
        return index

    matching_sets = [
        set_payload
        for set_payload in index
        if generalized._norm_number(set_payload.get("id"))
        == generalized._norm_number(namespace)
    ]
    if not matching_sets:
        return None
    if len(matching_sets) > 1:
        return _ambiguous("TCGdex unique-coordinate namespace set id is not unique")

    set_id = str(matching_sets[0].get("id") or "").strip()
    probed = _probe_exact_set_coordinate(
        lot,
        language_code=language_code,
        set_id=set_id,
        expected_count=None,
    )
    if isinstance(probed, canonical.CanonicalCard) or probed is None:
        return probed
    return _canonicalize_unique_card(
        lot,
        probed,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=set_id,
        expected_count=None,
    )


def _recover_alphanumeric_localid(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    reference: str,
) -> canonical.CanonicalCard | None:
    left, right = canonical._canonical_number_parts(reference)
    if right or not left or left.isdigit() or not any(ch.isalpha() for ch in left):
        return None

    briefs_by_id: dict[str, Mapping[str, Any]] = {}
    for local_id in generalized._reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/cards",
                params={"localId": f"eq:{local_id}"},
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return _error(
                f"TCGdex unique-coordinate localId search {type(exc).__name__}"
            )
        if status == 404:
            continue
        if status != 200:
            return _error(f"TCGdex unique-coordinate localId search HTTP {status}")
        for brief in canonical._extract_list_payload(payload):
            card_id = str(brief.get("id") or "").strip()
            if not card_id:
                return _error("TCGdex unique-coordinate malformed card brief")
            brief_local = str(brief.get("localId") or "").strip()
            if brief_local and not generalized._same_local_id(brief_local, reference):
                return _error("TCGdex unique-coordinate inconsistent card brief")
            briefs_by_id[card_id] = brief

    if not briefs_by_id:
        return None
    if len(briefs_by_id) > _MAX_ALPHANUMERIC_LOCALID_BRIEFS:
        return _ambiguous("TCGdex unique-coordinate localId search exceeded safe cap")
    if len(briefs_by_id) > 1:
        return _ambiguous("TCGdex unique-coordinate alphanumeric localId is not unique")

    card_id = next(iter(briefs_by_id))
    try:
        status, detail = canonical._fetch_tcgdex_card_detail(language_code, card_id)
    except Exception as exc:
        return _error(f"TCGdex unique-coordinate detail {type(exc).__name__}")
    if status != 200 or not isinstance(detail, Mapping):
        return _error(f"TCGdex unique-coordinate detail HTTP {status}")

    set_payload = detail.get("set")
    set_id = (
        str(set_payload.get("id") or "").strip()
        if isinstance(set_payload, Mapping)
        else ""
    )
    if not set_id or not _raw_card_matches_coordinate(
        detail,
        expected_set_id=set_id,
        reference=reference,
        expected_count=None,
    ):
        return _error("TCGdex unique-coordinate inconsistent detail")

    return _canonicalize_unique_card(
        lot,
        detail,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        expected_set_id=set_id,
        expected_count=None,
    )


def _recover_unique_coordinate(lot: watcher.Lot) -> canonical.CanonicalCard | None:
    language_code, listing_set, reference, listing_name, _, _ = generalized._lot_components(
        lot
    )
    if not (language_code and reference and listing_name):
        return None

    left, right = canonical._canonical_number_parts(reference)
    if not left:
        return None
    if right.isdigit():
        return _recover_numeric_denominator(
            lot,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            reference=reference,
            denominator=right,
        )
    if right:
        return _recover_namespace_coordinate(
            lot,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            reference=reference,
            namespace=right,
        )
    return _recover_alphanumeric_localid(
        lot,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        reference=reference,
    )


def _reclassify_original_no_match(result: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    if result.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif result.status == "AMBIGUOUS":
        diagnostics.tcgdex_ambiguous += 1
    elif result.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _resolve_with_unique_coordinate_fallback(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    _, _, _, _, _, key = generalized._lot_components(lot)

    cached = _RESULT_CACHE.get(key)
    if cached is not None:
        if cached.status == "EXACT":
            canonical._DIAGNOSTICS.tcgdex_exact += 1
        elif cached.status == "AMBIGUOUS":
            canonical._DIAGNOSTICS.tcgdex_ambiguous += 1
        return cached
    if key in _NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "NO_MATCH":
        return original

    recovered = _recover_unique_coordinate(lot)
    if recovered is None:
        _NEGATIVE_CACHE.add(key)
        return original

    if recovered.status in {"EXACT", "AMBIGUOUS", "ERROR"}:
        _reclassify_original_no_match(recovered)
    if recovered.status in {"EXACT", "AMBIGUOUS"}:
        _RESULT_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _SET_INDEX_CACHE.clear()
    _RESULT_CACHE.clear()
    _NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_unique_coordinate_fallback() -> None:
    """Install bounded deterministic recovery for globally unique coordinates.

    Accepted proofs after an ordinary TCGdex NO_MATCH:
    - numeric printed denominator -> all TCGdex sets with that exact card count
      are probed for the exact localId and exactly one may exist;
    - non-numeric printed namespace -> exact TCGdex set id + exact localId;
    - alphanumeric localId without denominator -> exact global localId search and
      exactly one card brief.

    Numeric localId without a denominator remains unresolved. No fuzzy set/name
    matching, translation guessing, denominator bypass, microvariant relaxation,
    valuation change, purchase, bid or checkout is introduced.
    """

    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_unique_coordinate_fallback", False):
        return
    _ORIGINAL_RESOLVER = current
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    _resolve_with_unique_coordinate_fallback._v4_unique_coordinate_fallback = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_unique_coordinate_fallback
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
