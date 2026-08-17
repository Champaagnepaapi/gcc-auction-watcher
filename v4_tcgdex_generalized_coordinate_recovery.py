from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Mapping, Optional

import watcher
import v4_canonical_multimarket as canonical


# Source pin shared with PR #119. These are set-level aliases, not per-card
# exceptions. They only bridge exact GCC labels/namespaces to deterministic
# TCGdex set IDs; the card coordinate must still be proven live by TCGdex.
_SOURCE_COMMIT = "af33c9ac882e2acfadffaf19e8083aa976d12983"


@dataclass(frozen=True)
class ExactSetAlias:
    language_code: str
    listing_set: str
    tcgdex_set_id: str
    tcgdex_official_count: int
    required_reference_suffix: str = ""
    require_numeric_denominator: bool = False
    allow_localized_name_mismatch: bool = False
    provenance: str = ""


def _norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text).strip().casefold()


def _norm_number(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lstrip("#")).upper()


def _alias_key(language_code: str, listing_set: str) -> tuple[str, str]:
    return str(language_code or "").strip().lower(), _norm_text(listing_set)


_SET_ALIASES = (
    # GCC exposes English/romanized labels for these Japanese cards while the
    # TCGdex ja catalogue exposes localized set/card names. Exact set + printed
    # localId + exact numeric denominator remains deterministic.
    ExactSetAlias(
        "ja",
        "Eevee Heroes",
        "S6a",
        69,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex S6a set-level alias / GCC Eevee Heroes",
    ),
    ExactSetAlias(
        "ja",
        "Brilliant Stars",
        "S9",
        100,
        require_numeric_denominator=True,
        allow_localized_name_mismatch=True,
        provenance="TCGdex S9 set-level alias / GCC Japanese Brilliant Stars label",
    ),
    # GCC uses marketplace-facing promo labels while TCGdex uses official
    # Black Star Promo namespaces.
    ExactSetAlias(
        "fr",
        "Promo Mega Evolution",
        "mep",
        0,
        required_reference_suffix="MEP",
        provenance="TCGdex MEP Black Star Promos / GCC promo namespace",
    ),
    ExactSetAlias(
        "fr",
        "Promos Écarlate et Violet",
        "svp",
        225,
        provenance="TCGdex SVP Black Star Promos / GCC French promo namespace",
    ),
)

_SET_ALIASES_BY_KEY = {
    _alias_key(alias.language_code, alias.listing_set): alias
    for alias in _SET_ALIASES
}

# These tokens are marketplace display/finish descriptors observed in GCC names,
# not card-name identity. They are stripped only after TCGdex has already proven
# one exact set + localId coordinate, and the remaining base name must match.
_DISPLAY_SUFFIXES = (" holo", " gold")

_RECOVERY_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_RECOVERY_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None


def _lot_components(
    lot: watcher.Lot,
) -> tuple[str, str, str, str, int, tuple[str, str, str, str, int]]:
    identity = watcher.extract_card_identity(lot)
    language_code = canonical._language_code(lot)
    listing_set = str(lot.card_set or identity.get("series") or "").strip()
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    listing_name = str(identity.get("core") or "").strip()
    year_value = lot.year if lot.year is not None else identity.get("year")
    try:
        year = int(year_value)
    except (TypeError, ValueError):
        year = 0
    key = (
        language_code,
        _norm_text(listing_set),
        _norm_number(reference),
        _norm_text(listing_name),
        year,
    )
    return language_code, listing_set, reference, listing_name, year, key


def _set_count_matches(set_payload: Mapping[str, Any], expected: int) -> bool:
    counts = set_payload.get("cardCount")
    if not isinstance(counts, Mapping):
        return False
    observed: set[int] = set()
    for value in (counts.get("official"), counts.get("total")):
        try:
            observed.add(int(str(value).strip()))
        except (TypeError, ValueError):
            continue
    return int(expected) in observed


def _same_local_id(observed: Any, reference: str) -> bool:
    expected_left, _ = canonical._canonical_number_parts(reference)
    observed_left, _ = canonical._canonical_number_parts(observed)
    return bool(expected_left and observed_left and expected_left == observed_left)


def _reference_candidates(reference: str) -> list[str]:
    raw_left, _ = canonical._number_parts(reference)
    if not raw_left:
        return []
    candidates = [raw_left]
    if raw_left.isdigit():
        value = int(raw_left)
        for candidate in (str(value), f"{value:03d}", f"{value:02d}"):
            if candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _transient_status(status: int) -> bool:
    return status in {0, 408, 425, 429} or status >= 500


def _name_candidates(listing_name: str) -> set[str]:
    normalized = canonical._normalize(listing_name)
    candidates = {normalized} if normalized else set()
    for suffix in _DISPLAY_SUFFIXES:
        normalized_suffix = canonical._normalize(suffix)
        if normalized and normalized_suffix and normalized.endswith(f" {normalized_suffix}"):
            base = normalized[: -(len(normalized_suffix) + 1)].strip()
            if base:
                candidates.add(base)
    return candidates


def _card_name_compatible(listing_name: str, card: Mapping[str, Any]) -> bool:
    candidate_name = canonical._normalize(card.get("name"))
    return bool(candidate_name and candidate_name in _name_candidates(listing_name))


def _validate_reference_for_alias(reference: str, alias: ExactSetAlias) -> bool:
    left, right = canonical._canonical_number_parts(reference)
    if not left:
        return False
    if alias.required_reference_suffix:
        if _norm_number(right) != _norm_number(alias.required_reference_suffix):
            return False
    if alias.require_numeric_denominator:
        if not right.isdigit() or int(right) != alias.tcgdex_official_count:
            return False
    elif right.isdigit() and alias.tcgdex_official_count > 0:
        if int(right) != alias.tcgdex_official_count:
            return False
    return True


def _canonical_from_coordinate(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    expected_set_id: str,
    expected_count: Optional[int],
    allow_localized_name_mismatch: bool,
) -> Optional[canonical.CanonicalCard]:
    identity = watcher.extract_card_identity(lot)
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    card_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    set_payload = card.get("set")
    if not card_id or not local_id or not isinstance(set_payload, Mapping):
        return None

    set_id = str(set_payload.get("id") or "").strip()
    if set_id != expected_set_id or not _same_local_id(local_id, reference):
        return None

    _, denominator = canonical._canonical_number_parts(reference)
    if denominator.isdigit() and not canonical._denominator_matches(card, denominator):
        return None
    if expected_count is not None and not _set_count_matches(set_payload, expected_count):
        return None

    if not allow_localized_name_mismatch and not _card_name_compatible(listing_name, card):
        return None

    returned_name = str(card.get("name") or "").strip()
    canonical_name = listing_name if allow_localized_name_mismatch else returned_name
    return canonical.CanonicalCard(
        status="EXACT",
        card_id=card_id,
        set_id=set_id,
        # Preserve the GCC commercial label for downstream market matching.
        set_name=listing_set,
        local_id=local_id,
        full_number=reference,
        # Japanese aliases preserve the GCC/romanized name because TCGdex ja may
        # have only a localized name or, for some coordinates, no ja name at all.
        name=canonical_name,
        language_code=language_code,
        pricing=card.get("pricing") if isinstance(card.get("pricing"), Mapping) else {},
        variants=card.get("variants") if isinstance(card.get("variants"), Mapping) else {},
        # Keep the canonical deterministic reason-code already accepted by all
        # downstream gates. This is exact set + localId proof, not fuzzy proof.
        reason="TCGDEX_EXACT_SET_LOCALID",
        unique_name_number=False,
    )


def _fetch_coordinate(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    set_id: str,
    expected_count: Optional[int],
    allow_localized_name_mismatch: bool,
) -> canonical.CanonicalCard | None:
    identity = watcher.extract_card_identity(lot)
    reference = str(lot.card_number or identity.get("ref") or "").strip()
    for local_id in _reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets/{set_id}/{local_id}",
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return canonical.CanonicalCard(
                "ERROR",
                reason=f"TCGdex generalized coordinate {type(error).__name__}",
            )
        if status == 404:
            continue
        if status != 200:
            if _transient_status(status):
                return canonical.CanonicalCard(
                    "ERROR",
                    reason=f"TCGdex generalized coordinate transient HTTP {status}",
                )
            return None
        card = canonical._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            return canonical.CanonicalCard(
                "ERROR",
                reason="TCGdex generalized coordinate invalid payload",
            )
        return _canonical_from_coordinate(
            lot,
            card,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            expected_set_id=set_id,
            expected_count=expected_count,
            allow_localized_name_mismatch=allow_localized_name_mismatch,
        )
    return None


def _recover_from_set_alias(lot: watcher.Lot) -> canonical.CanonicalCard | None:
    language_code, listing_set, reference, listing_name, _, _ = _lot_components(lot)
    alias = _SET_ALIASES_BY_KEY.get(_alias_key(language_code, listing_set))
    if alias is None or not listing_name or not _validate_reference_for_alias(reference, alias):
        return None
    return _fetch_coordinate(
        lot,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        set_id=alias.tcgdex_set_id,
        expected_count=alias.tcgdex_official_count,
        allow_localized_name_mismatch=alias.allow_localized_name_mismatch,
    )


def _recover_from_exact_set_name(lot: watcher.Lot) -> canonical.CanonicalCard | None:
    """Recover a card when only a trailing display/finish token broke the name.

    This path never guesses a set. The localized GCC set label must resolve to
    exactly one TCGdex set, the exact printed localId must exist in that set, any
    numeric denominator must match, and the TCGdex card name must equal the GCC
    base name after removing only a bounded trailing display token.
    """

    language_code, listing_set, reference, listing_name, _, _ = _lot_components(lot)
    if not (language_code and listing_set and reference and listing_name):
        return None
    # Do not duplicate network work for names that have no reviewed display
    # suffix. The normal resolver already handled ordinary exact-set matching.
    normalized_name = canonical._normalize(listing_name)
    if len(_name_candidates(listing_name)) <= 1:
        return None

    try:
        status, payload, _ = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets",
            params={"name": f"eq:{listing_set}"},
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        return canonical.CanonicalCard(
            "ERROR", reason=f"TCGdex exact-set display recovery {type(error).__name__}"
        )
    if status != 200:
        if _transient_status(status):
            return canonical.CanonicalCard(
                "ERROR",
                reason=f"TCGdex exact-set display recovery transient HTTP {status}",
            )
        return None

    sets = canonical._extract_list_payload(payload)
    if len(sets) != 1:
        return None
    set_id = str(sets[0].get("id") or "").strip()
    if not set_id:
        return canonical.CanonicalCard(
            "ERROR", reason="TCGdex exact-set display recovery malformed set"
        )

    # expected_count=None here because the exact fetched card payload will still
    # enforce any numeric denominator from the printed GCC reference.
    return _fetch_coordinate(
        lot,
        language_code=language_code,
        listing_set=listing_set,
        listing_name=listing_name,
        set_id=set_id,
        expected_count=None,
        allow_localized_name_mismatch=False,
    )


def _reclassify_original_no_match(result: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    if result.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif result.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _resolve_with_generalized_coordinate_recovery(
    lot: watcher.Lot,
) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    _, _, _, _, _, key = _lot_components(lot)

    cached = _RECOVERY_CACHE.get(key)
    if cached is not None:
        canonical._DIAGNOSTICS.tcgdex_exact += 1
        return cached
    if key in _RECOVERY_NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "NO_MATCH":
        return original

    recovered = _recover_from_set_alias(lot)
    if recovered is None:
        recovered = _recover_from_exact_set_name(lot)
    if recovered is None:
        _RECOVERY_NEGATIVE_CACHE.add(key)
        return original

    if recovered.status in {"EXACT", "ERROR"}:
        _reclassify_original_no_match(recovered)
    if recovered.status == "EXACT":
        _RECOVERY_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RECOVERY_CACHE.clear()
    _RECOVERY_NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_generalized_coordinate_recovery() -> None:
    """Install a deterministic post-NO_MATCH set/localId recovery layer.

    It adds only two bounded proofs:
    1. reviewed exact GCC set/namespace aliases -> exact TCGdex set ID + localId;
    2. exact localized set name + exact localId when only trailing Holo/Gold
       display text prevents an otherwise exact same-language card-name match.

    No fuzzy set/card matching, translation guessing, denominator bypass or
    microvariant relaxation is introduced.
    """

    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_generalized_coordinate_recovery", False):
        return
    _ORIGINAL_RESOLVER = current
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    _resolve_with_generalized_coordinate_recovery._v4_generalized_coordinate_recovery = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_generalized_coordinate_recovery
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
