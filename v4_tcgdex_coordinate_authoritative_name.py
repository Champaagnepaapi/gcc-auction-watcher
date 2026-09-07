from __future__ import annotations

"""Recover harmless card-name omissions only after exact TCGdex coordinate proof.

This layer makes the printed coordinate authoritative for the *macro card* when
language + exact set + localId already identify one TCGdex card. It is not a
fuzzy/global resolver:

- the set must resolve to exactly one TCGdex set id via the existing exact-set
  resolver;
- the printed localId must resolve through that exact set endpoint;
- any supplied denominator must still match the returned card;
- the Pokemon/base name must remain the same (the already-reviewed #260 typo /
  possessive bridge is reused only after coordinate proof);
- an omitted structural form such as GX/V/ex is allowed, but two explicitly
  different forms are a hard conflict;
- trailing marketplace descriptors (Holo/Reverse/Rainbow/Full Art/FA/etc.) are
  not card-name identity when the coordinate is already exact;
- material variants still have to be uniquely compatible. If the same coordinate
  exposes multiple finishes and the listing does not discriminate them, recovery
  remains blocked.

Edition is deliberately not made globally mandatory here. Existing catalogue /
commercial gates remain responsible for First Edition/Unlimited only where that
axis is actually applicable.
"""

from dataclasses import replace
from typing import Any, Mapping

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_detailed_variants as detailed
import v4_tcgdex_generalized_coordinate_recovery as generalized
import v4_tcgdex_name_filtered_coordinate_recovery as name_filtered
import v4_tcgdex_two_of_three_backport as two_of_three


_ORIGINAL_RESOLVER = None
_ORIGINAL_CLEAR_CACHE = None
_INSTALLED = False
_RESULT_CACHE: dict[tuple[str, str, str, str, int], canonical.CanonicalCard] = {}
_NEGATIVE_CACHE: set[tuple[str, str, str, str, int]] = set()

_TARGET_AMBIGUOUS_REASONS = {
    "TCGdex unique-coordinate printed number/denominator is not unique",
}

# Structural suffixes are intrinsic card forms, not finishes. Omission on one
# side is tolerable after exact coordinate proof; two different explicit forms
# are not.
_CARD_FORM_SUFFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("lv", "x"), "lv_x"),
    (("vmax",), "vmax"),
    (("vstar",), "vstar"),
    (("break",), "break"),
    (("gx",), "gx"),
    (("ex",), "ex"),
    (("v",), "v"),
)

# These are accepted only as *trailing presentation descriptors* after exact
# set/localId proof. Finish/special-finish claims that are represented by the
# commercial parser are still checked independently below against TCGdex.
_DISPLAY_SUFFIXES: tuple[tuple[str, ...], ...] = (
    ("rainbow", "rare"),
    ("reverse", "holo"),
    ("secret", "rare"),
    ("full", "art"),
    ("rainbow",),
    ("reverse",),
    ("holo",),
    ("fa",),
)


def _strip_display_suffixes(tokens: tuple[str, ...]) -> tuple[str, ...]:
    current = tokens
    while current:
        removed = False
        for suffix in _DISPLAY_SUFFIXES:
            if len(current) > len(suffix) and current[-len(suffix) :] == suffix:
                current = current[: -len(suffix)]
                removed = True
                break
        if not removed:
            break
    return current


def _split_card_form(tokens: tuple[str, ...]) -> tuple[tuple[str, ...], str]:
    for suffix, form in _CARD_FORM_SUFFIXES:
        if len(tokens) > len(suffix) and tokens[-len(suffix) :] == suffix:
            return tokens[: -len(suffix)], form
    return tokens, ""


def _coordinate_name_compatible(listing_name: object, provider_name: object) -> bool:
    """Compare names after exact coordinate proof, preserving explicit conflicts."""
    listing_tokens = _strip_display_suffixes(
        name_filtered._relaxed_name_tokens(listing_name)
    )
    provider_tokens = _strip_display_suffixes(
        name_filtered._relaxed_name_tokens(provider_name)
    )
    if not listing_tokens or not provider_tokens:
        return False

    listing_base, listing_form = _split_card_form(listing_tokens)
    provider_base, provider_form = _split_card_form(provider_tokens)
    if listing_form and provider_form and listing_form != provider_form:
        return False
    if not listing_base or not provider_base:
        return False

    return name_filtered._approximate_name_equivalent(
        " ".join(listing_base), " ".join(provider_base)
    )


def _attach_detailed_variants(
    result: canonical.CanonicalCard,
    card: Mapping[str, Any],
    *,
    language_code: str,
) -> canonical.CanonicalCard:
    if "variants_detailed" not in card:
        return result
    state, entries = detailed.sanitize_variants_detailed(
        card.get("variants_detailed"), language_code=language_code
    )
    variants = dict(result.variants) if isinstance(result.variants, Mapping) else {}
    variants[detailed.DETAILED_SCHEMA_KEY] = detailed.DETAILED_SCHEMA_VERSION
    variants[detailed.DETAILED_STATE_KEY] = state
    variants[detailed.DETAILED_ENTRIES_KEY] = entries
    return replace(result, variants=variants)


def _legacy_finish_choices(card: canonical.CanonicalCard) -> set[str]:
    variants = card.variants if isinstance(card.variants, Mapping) else {}
    return {
        finish
        for finish, key in (
            ("non_holo", "normal"),
            ("holo", "holo"),
            ("reverse", "reverse"),
        )
        if variants.get(key) is True
    }


def _material_identity_is_resolved(
    lot: watcher.Lot,
    result: canonical.CanonicalCard,
) -> bool:
    """Block recovery when the same coordinate still has material ambiguity."""
    expected = detailed._expected_from_lot(lot)
    state = str(
        (result.variants or {}).get(detailed.DETAILED_STATE_KEY) or "ABSENT"
    )

    if state not in {"ABSENT", "EMPTY"}:
        decision = detailed.detailed_variant_decision(result, expected)
        return bool(decision.compatible and decision.status == "EXACT")

    # Legacy fallback for cards without structured variants_detailed.
    finishes = _legacy_finish_choices(result)
    expected_finish = str(expected.get("finish") or "")
    expected_special = str(expected.get("special_finish") or "")

    # A special foil (Rainbow/Master Ball/etc.) needs structured proof; never
    # manufacture it from an ordinary holo boolean.
    if expected_special:
        return False
    if expected_finish:
        return not finishes or expected_finish in finishes
    if len(finishes) > 1:
        return False
    return True


def _catalog_full_number(card: Mapping[str, Any], reference: str) -> str:
    left, right = canonical._canonical_number_parts(reference)
    if right:
        return reference
    local_id = str(card.get("localId") or left or "").strip()
    set_payload = card.get("set")
    if not local_id or not isinstance(set_payload, Mapping):
        return reference
    counts = set_payload.get("cardCount")
    if not isinstance(counts, Mapping):
        return reference
    official = str(counts.get("official") or "").strip()
    if official.isdigit() and int(official) > 0:
        return f"{local_id}/{int(official)}"
    return reference


def _recover_exact_set_coordinate(lot: watcher.Lot) -> canonical.CanonicalCard | None:
    (
        language_code,
        listing_set,
        reference,
        listing_name,
        _,
        _,
    ) = generalized._lot_components(lot)
    if not (language_code and listing_set and reference and listing_name):
        return None

    set_ids = two_of_three._exact_set_ids(language_code, listing_set)
    if isinstance(set_ids, canonical.CanonicalCard):
        return set_ids if set_ids.status == "ERROR" else None
    if len(set_ids) != 1:
        return None
    set_id = set_ids[0]

    for local_id in generalized._reference_candidates(reference):
        try:
            status, payload, _ = canonical._json_get(
                f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets/{set_id}/{local_id}",
                timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
            )
        except Exception as error:
            return canonical.CanonicalCard(
                "ERROR",
                reason=f"TCGdex coordinate-authoritative {type(error).__name__}",
            )
        if status == 404:
            continue
        if status != 200:
            if generalized._transient_status(status):
                return canonical.CanonicalCard(
                    "ERROR",
                    reason=f"TCGdex coordinate-authoritative transient HTTP {status}",
                )
            return None

        card = canonical._extract_single_payload(payload)
        if not isinstance(card, Mapping):
            return canonical.CanonicalCard(
                "ERROR", reason="TCGdex coordinate-authoritative invalid payload"
            )
        provider_name = str(card.get("name") or "").strip()
        if not provider_name or not _coordinate_name_compatible(
            listing_name, provider_name
        ):
            return None

        # Build through the already-reviewed exact coordinate validator using the
        # canonical provider name. This repeats set/localId/denominator checks.
        result = generalized._canonical_from_coordinate(
            lot,
            card,
            language_code=language_code,
            listing_set=listing_set,
            listing_name=provider_name,
            expected_set_id=set_id,
            expected_count=None,
            allow_localized_name_mismatch=False,
        )
        if result is None:
            return None

        result = replace(
            result,
            name=provider_name,
            full_number=_catalog_full_number(card, reference),
        )
        result = _attach_detailed_variants(
            result, card, language_code=language_code
        )
        if not _material_identity_is_resolved(lot, result):
            return None
        return result
    return None


def _reclassify(original: canonical.CanonicalCard, recovered: canonical.CanonicalCard) -> None:
    diagnostics = canonical._DIAGNOSTICS
    if original.status == "NO_MATCH" and diagnostics.tcgdex_no_match > 0:
        diagnostics.tcgdex_no_match -= 1
    elif original.status == "AMBIGUOUS" and diagnostics.tcgdex_ambiguous > 0:
        diagnostics.tcgdex_ambiguous -= 1

    if recovered.status == "EXACT":
        diagnostics.tcgdex_exact += 1
    elif recovered.status == "ERROR":
        diagnostics.tcgdex_error += 1


def _resolve_with_coordinate_authority(lot: watcher.Lot) -> canonical.CanonicalCard:
    assert _ORIGINAL_RESOLVER is not None
    _, _, _, _, _, key = generalized._lot_components(lot)

    cached = _RESULT_CACHE.get(key)
    if cached is not None:
        canonical._DIAGNOSTICS.tcgdex_exact += 1
        return cached
    if key in _NEGATIVE_CACHE:
        return _ORIGINAL_RESOLVER(lot)

    original = _ORIGINAL_RESOLVER(lot)
    if original.status == "AMBIGUOUS" and original.reason not in _TARGET_AMBIGUOUS_REASONS:
        return original
    if original.status not in {"NO_MATCH", "AMBIGUOUS"}:
        return original

    recovered = _recover_exact_set_coordinate(lot)
    if recovered is None:
        _NEGATIVE_CACHE.add(key)
        return original
    if recovered.status == "ERROR":
        _reclassify(original, recovered)
        return recovered
    if recovered.status != "EXACT":
        return original

    _reclassify(original, recovered)
    _RESULT_CACHE[key] = recovered
    return recovered


def _clear_all_tcgdex_caches() -> None:
    _RESULT_CACHE.clear()
    _NEGATIVE_CACHE.clear()
    assert _ORIGINAL_CLEAR_CACHE is not None
    _ORIGINAL_CLEAR_CACHE()


def install_v4_tcgdex_coordinate_authoritative_name() -> None:
    """Install after detailed/Rainbow support so microvariant ambiguity still blocks."""
    global _ORIGINAL_RESOLVER, _ORIGINAL_CLEAR_CACHE, _INSTALLED
    if _INSTALLED:
        return
    _ORIGINAL_RESOLVER = canonical.resolve_tcgdex_card
    _ORIGINAL_CLEAR_CACHE = canonical.clear_tcgdex_cache
    canonical.resolve_tcgdex_card = _resolve_with_coordinate_authority
    canonical.clear_tcgdex_cache = _clear_all_tcgdex_caches
    _INSTALLED = True
