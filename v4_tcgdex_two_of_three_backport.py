from __future__ import annotations

from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_generalized_coordinate_recovery as generalized


# Backport of the deterministic catalogue-cardinality rules introduced in V5
# PR #31 and retained in the current V5 resolver. This layer is deliberately
# installed after the existing V4 exact/alias paths and before the broader
# unique-coordinate fallback from PR #122.
#
# It proves a missing macro coordinate only from TWO exact coordinates:
#   1. exact card name + complete printed number -> recover set when unique;
#   2. exact set + exact card name -> recover printed number when unique.
#
# It never proves edition/finish/stamp/promo microvariants. Existing downstream
# V4 gates remain authoritative for those dimensions.
_MAX_CANDIDATES = 12

_RESULT_CACHE: dict[
    tuple[str, str, str, str, int], canonical.CanonicalCard
] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()
_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None


def _error(reason: str) -> canonical.CanonicalCard:
    return canonical.CanonicalCard("ERROR", reason=reason)


def _ambiguous(reason: str) -> canonical.CanonicalCard:
    return canonical.CanonicalCard("AMBIGUOUS", reason=reason)


def _transient_status(status: int) -> bool:
    return status in {0, 408, 425, 429} or status >= 500


def _release_year(card: Mapping[str, Any]) -> int | None:
    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return None
    raw = str(set_payload.get("releaseDate") or "").strip()
    if len(raw) < 4 or not raw[:4].isdigit():
        return None
    return int(raw[:4])


def _year_compatible(lot: watcher.Lot, card: Mapping[str, Any]) -> bool:
    if lot.year is None:
        return True
    observed = _release_year(card)
    return observed is None or int(lot.year) == observed


def _complete_printed_number(reference: str) -> bool:
    left, right = canonical._canonical_number_parts(reference)
    return bool(left and right)


def _query_exact_name_number_briefs(
    language_code: str,
    listing_name: str,
    reference: str,
) -> tuple[Mapping[str, Any], ...] | canonical.CanonicalCard:
    candidates: dict[str, Mapping[str, Any]] = {}
    for local_id in generalized._reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/cards",
                params={
                    # Retrieval may be broader than equality provider-side.
                    # Acceptance below remains exact after safe normalization.
                    "name": listing_name,
                    "localId": f"eq:{local_id}",
                    "pagination:page": "1",
                    "pagination:itemsPerPage": str(_MAX_CANDIDATES + 1),
                },
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return _error(f"TCGdex two-of-three name+number {type(exc).__name__}")
        if status == 404:
            continue
        if status != 200:
            return _error(f"TCGdex two-of-three name+number HTTP {status}")

        rows = canonical._extract_list_payload(payload)
        if len(rows) > _MAX_CANDIDATES:
            return _ambiguous("TCGdex two-of-three name+number candidate overflow")
        expected_left, _ = canonical._canonical_number_parts(local_id)
        for brief in rows:
            if canonical._normalize(brief.get("name")) != canonical._normalize(
                listing_name
            ):
                continue
            observed_left, _ = canonical._canonical_number_parts(
                brief.get("localId")
            )
            if not expected_left or observed_left != expected_left:
                continue
            card_id = str(brief.get("id") or "").strip()
            if not card_id:
                return _error("TCGdex two-of-three malformed card brief")
            candidates[card_id] = brief
            if len(candidates) > _MAX_CANDIDATES:
                return _ambiguous(
                    "TCGdex two-of-three name+number candidate overflow"
                )
    return tuple(candidates.values())


def _recover_unique_name_number(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_name: str,
    reference: str,
) -> canonical.CanonicalCard | None:
    """Exact name + complete printed number -> unique TCGdex macro card."""
    if not (listing_name and _complete_printed_number(reference)):
        return None

    briefs = _query_exact_name_number_briefs(
        language_code, listing_name, reference
    )
    if isinstance(briefs, canonical.CanonicalCard):
        return briefs
    if not briefs:
        return None

    exact: dict[str, canonical.CanonicalCard] = {}
    for brief in briefs:
        card_id = str(brief.get("id") or "").strip()
        if not card_id:
            return _error("TCGdex two-of-three malformed candidate id")
        try:
            status, detail = canonical._fetch_tcgdex_card_detail(
                language_code, card_id
            )
        except Exception as exc:
            return _error(f"TCGdex two-of-three detail {type(exc).__name__}")
        if status != 200 or not isinstance(detail, Mapping):
            # A detail response is required to prove denominator/set/year. Never
            # convert an incomplete catalogue response into a clean negative.
            return _error(f"TCGdex two-of-three detail HTTP {status}")
        if canonical._normalize(detail.get("name")) != canonical._normalize(
            listing_name
        ):
            continue
        if not _year_compatible(lot, detail):
            continue
        resolved = canonical._validate_tcgdex_card(
            lot,
            detail,
            language_code=language_code,
            unique_name_number=True,
            reason="TCGDEX_UNIQUE_NAME_FULL_NUMBER",
        )
        if resolved is not None:
            exact[resolved.card_id] = resolved

    if len(exact) > 1:
        return _ambiguous(
            "TCGdex two-of-three name+number is not catalogue-unique"
        )
    if not exact:
        return None
    return next(iter(exact.values()))


def _exact_set_ids(
    language_code: str,
    listing_set: str,
) -> tuple[str, ...] | canonical.CanonicalCard:
    """Resolve an exact set name/id without fuzzy matching.

    Mirrors the proven V5 rule: the listing-language catalogue is primary, while
    EN/FR may expose the same official TCGdex set ID under another exact official
    name. Only the deduplicated exact set ID is accepted.
    """
    normalized = canonical._normalize(listing_set)
    if not normalized:
        return ()

    set_ids: set[str] = set()
    lookup_languages = tuple(dict.fromkeys((language_code, "en", "fr")))
    for lookup_language in lookup_languages:
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{lookup_language}/sets",
                params={"name": f"eq:{listing_set}"},
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            return _error(f"TCGdex two-of-three set lookup {type(exc).__name__}")
        if status == 404:
            continue
        if status != 200:
            return _error(f"TCGdex two-of-three set lookup HTTP {status}")
        rows = canonical._extract_list_payload(payload)
        if len(rows) > _MAX_CANDIDATES:
            return _ambiguous("TCGdex two-of-three set candidate overflow")
        for row in rows:
            set_id = str(row.get("id") or "").strip()
            set_name = str(row.get("name") or "").strip()
            if not set_id:
                return _error("TCGdex two-of-three malformed set brief")
            if (
                canonical._normalize(set_name) == normalized
                or canonical._normalize(set_id) == normalized
            ):
                set_ids.add(set_id)
                if len(set_ids) > 1:
                    return _ambiguous(
                        "TCGdex two-of-three exact set resolves to multiple ids"
                    )
    return tuple(sorted(set_ids))


def _full_number_from_card(card: Mapping[str, Any]) -> str:
    local_id = str(card.get("localId") or "").strip()
    if not local_id:
        return ""
    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return local_id
    counts = set_payload.get("cardCount")
    official = ""
    if isinstance(counts, Mapping):
        raw = counts.get("official")
        if raw is not None:
            official = str(raw).strip()
    if official and official != "0":
        return f"{local_id}/{official}"
    return local_id


def _canonical_from_recovered_set_name(
    lot: watcher.Lot,
    card: Mapping[str, Any],
    *,
    language_code: str,
    expected_set_id: str,
    listing_name: str,
) -> canonical.CanonicalCard | None:
    if canonical._normalize(card.get("name")) != canonical._normalize(listing_name):
        return None
    if not _year_compatible(lot, card):
        return None

    set_payload = card.get("set")
    if not isinstance(set_payload, Mapping):
        return None
    set_id = str(set_payload.get("id") or "").strip()
    set_name = str(set_payload.get("name") or "").strip()
    card_id = str(card.get("id") or "").strip()
    local_id = str(card.get("localId") or "").strip()
    full_number = _full_number_from_card(card)
    if not all((card_id, local_id, full_number, set_id, set_name)):
        return None
    if set_id != expected_set_id:
        return None

    return canonical.CanonicalCard(
        status="EXACT",
        card_id=card_id,
        set_id=set_id,
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=str(card.get("name") or "").strip(),
        language_code=language_code,
        pricing=(
            card.get("pricing")
            if isinstance(card.get("pricing"), Mapping)
            else {}
        ),
        variants=(
            card.get("variants")
            if isinstance(card.get("variants"), Mapping)
            else {}
        ),
        reason="TCGDEX_UNIQUE_SET_NAME_RECOVERED_NUMBER",
        unique_name_number=False,
    )


def _recover_unique_set_name(
    lot: watcher.Lot,
    *,
    language_code: str,
    listing_set: str,
    listing_name: str,
    reference: str,
) -> canonical.CanonicalCard | None:
    """Exact set + exact card name -> recover number only when unique."""
    if reference or not (listing_set and listing_name):
        return None

    set_ids = _exact_set_ids(language_code, listing_set)
    if isinstance(set_ids, canonical.CanonicalCard):
        return set_ids
    if not set_ids:
        return None
    if len(set_ids) != 1:
        return _ambiguous("TCGdex two-of-three exact set is not unique")
    set_id = set_ids[0]

    try:
        status, payload, _ = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets/{set_id}",
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        return _error(f"TCGdex two-of-three set detail {type(exc).__name__}")
    if status != 200 or not isinstance(payload, Mapping):
        return _error(f"TCGdex two-of-three set detail HTTP {status}")
    cards = payload.get("cards")
    if not isinstance(cards, list):
        return _error("TCGdex two-of-three set detail missing cards")

    matching = [
        item
        for item in cards
        if isinstance(item, Mapping)
        and canonical._normalize(item.get("name"))
        == canonical._normalize(listing_name)
    ]
    if len(matching) > 1:
        return _ambiguous(
            "TCGdex two-of-three set+name is not catalogue-unique"
        )
    if not matching:
        return None

    card_id = str(matching[0].get("id") or "").strip()
    if not card_id:
        return _error("TCGdex two-of-three set card missing id")
    try:
        detail_status, detail = canonical._fetch_tcgdex_card_detail(
            language_code, card_id
        )
    except Exception as exc:
        return _error(f"TCGdex two-of-three card detail {type(exc).__name__}")
    if detail_status != 200 or not isinstance(detail, Mapping):
        return _error(f"TCGdex two-of-three card detail HTTP {detail_status}")

    return _canonical_from_recovered_set_name(
        lot,
        detail,
        language_code=language_code,
        expected_set_id=set_id,
        listing_name=listing_name,
    )


def _recover_two_of_three(lot: watcher.Lot) -> canonical.CanonicalCard | None:
    (
        language_code,
        listing_set,
        reference,
        listing_name,
        _,
        _,
    ) = generalized._lot_components(lot)
    if not (language_code and listing_name):
        return None

    # Mirror current V5 ordering. Complete name+number can recover a missing set;
    # exact set+name can recover a missing number. A single coordinate never can.
    if not listing_set and _complete_printed_number(reference):
        return _recover_unique_name_number(
            lot,
            language_code=language_code,
            listing_name=listing_name,
            reference=reference,
        )
    if listing_set and not reference:
        return _recover_unique_set_name(
            lot,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=listing_name,
            reference=reference,
        )
    return None


def _resolve_with_two_of_three(lot: watcher.Lot) -> canonical.CanonicalCard:
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

    diagnostics = canonical._DIAGNOSTICS
    attempted_before = diagnostics.tcgdex_attempted
    no_match_before = diagnostics.tcgdex_no_match
    original = _ORIGINAL_RESOLVER(lot)
    if original.status != "NO_MATCH":
        return original

    recovered = _recover_two_of_three(lot)
    if recovered is None:
        _NEGATIVE_CACHE.add(key)
        return original

    # Some original NO_MATCH paths (e.g. missing printed number) return before
    # recording a TCGdex attempt. Count the actual catalogue work done here.
    if diagnostics.tcgdex_attempted == attempted_before:
        diagnostics.tcgdex_attempted += 1

    if diagnostics.tcgdex_no_match > no_match_before:
        diagnostics.tcgdex_no_match -= 1
    if recovered.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif recovered.status == "AMBIGUOUS":
        diagnostics.tcgdex_ambiguous += 1
    elif recovered.status == "ERROR":
        diagnostics.tcgdex_error += 1

    if recovered.status in {"EXACT", "AMBIGUOUS"}:
        _RESULT_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RESULT_CACHE.clear()
    _NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_two_of_three_backport() -> None:
    """Install the proven V5 two-of-three TCGdex uniqueness rules in V4.

    This is a history-recovery backport, not a new identity heuristic. It ports
    the deterministic catalogue-cardinality behavior from V5 PR #31/current V5
    while keeping all V4 economic and microvariant gates unchanged.
    """
    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE
    current = canonical.resolve_tcgdex_card
    if getattr(current, "_v4_tcgdex_two_of_three_backport", False):
        return
    _ORIGINAL_RESOLVER = current
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    _resolve_with_two_of_three._v4_tcgdex_two_of_three_backport = True  # type: ignore[attr-defined]
    canonical.resolve_tcgdex_card = _resolve_with_two_of_three
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
