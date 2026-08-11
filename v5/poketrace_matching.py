from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Optional

from .models import CardIdentity
from .poketrace_set_bridge import SET_BRIDGE_EXACT, SetBridgeDecision
from .variant_semantics import (
    FINISH_HOLO,
    FINISH_REVERSE,
    FINISH_STANDARD,
    semantics_from_text,
    variant_compatibility,
)


REJECT_PRODUCT_TYPE = "product_type"
REJECT_CARD_NUMBER = "card_number"
REJECT_CARD_NAME = "card_name"
REJECT_SET = "set"
REJECT_VARIANT = "variant"
REJECT_INSUFFICIENT = "insufficient"

SET_DIFF_EXACT_NORMALIZED = "exact_after_safe_normalization"
SET_DIFF_POKEMON_TCG_WRAPPER = "pokemon_tcg_wrapper"
SET_DIFF_PUNCTUATION_SPACING = "punctuation_or_spacing_only"
SET_DIFF_LANGUAGE_LOCALIZATION = "language_or_localization"
SET_DIFF_PARENT_SUBSET = "parent_set_vs_subset"
SET_DIFF_DANGEROUS_CONTAINMENT = "dangerous_distinct_containment"
SET_DIFF_SIGNIFICANT_EXTRA_TOKENS = "significant_extra_tokens"
SET_DIFF_NO_RELATION = "no_deterministic_relation"

NUMBER_DIFF_LEADING_ZERO = "leading_zero_only"
NUMBER_DIFF_DENOMINATOR_MISSING = "same_numerator_denominator_missing"
NUMBER_DIFF_CANDIDATE_NUMERATOR_ONLY = "candidate_numerator_only"
NUMBER_DIFF_LISTING_NUMERATOR_ONLY = "listing_numerator_only"
NUMBER_DIFF_DENOMINATOR_CONFLICT = "same_numerator_denominator_conflict"
NUMBER_DIFF_PREFIX_FAMILY = "tg_gg_sv_or_other_prefix"
NUMBER_DIFF_ALPHANUMERIC_CASE = "alphanumeric_case_only"
NUMBER_DIFF_CONTRADICTORY_AFFIX = "contradictory_prefix_or_suffix"
NUMBER_DIFF_OTHER = "other"

NAME_DIFF_CASE = "case_only"
NAME_DIFF_PUNCTUATION_ACCENTS = "punctuation_or_accents"
NAME_DIFF_GENDER = "gender_symbol"
NAME_DIFF_MECHANIC_SUFFIX = "ex_gx_v_vmax_vstar_or_other_suffix"
NAME_DIFF_SIGNIFICANT_PREFIX = "dark_rocket_or_other_significant_prefix"
NAME_DIFF_LOCALIZATION = "translation_or_localization"
NAME_DIFF_SIGNIFICANT = "significant_difference"


@dataclass(frozen=True)
class CandidateMatchEvidence:
    name_supplied: bool
    set_supplied: bool
    card_number_supplied: bool
    name_matched: bool
    set_matched: bool
    set_matched_before_bridge: bool
    card_number_matched: bool
    number_exact: bool
    number_partial: bool
    set_similarity: float
    failed_core_fields: tuple[str, ...]
    score: Optional[float]
    rejection: Optional[str]
    variant_compatible: bool = True
    variant_exact: bool = False
    variant_reason: Optional[str] = None
    variant_finish_match: bool = False
    variant_edition_match: bool = False
    variant_promo_match: bool = False
    variant_metadata_missing: bool = False
    name_difference: str = NAME_DIFF_SIGNIFICANT
    set_difference: str = SET_DIFF_NO_RELATION
    card_number_difference: str = NUMBER_DIFF_OTHER
    set_bridged: bool = False
    set_bridge_status: Optional[str] = None
    set_bridge_reason: Optional[str] = None


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


_MEANINGFUL_SUFFIX = re.compile(
    r"(?<![A-Za-z0-9])(?:VSTAR|VMAX|V-UNION|V|GX|EX|ex|LV\.?\s*X|BREAK|PRIME|LEGEND)\s*$"
)


def _normalize_card_name(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    # Gender symbols are part of the printed Pokemon name. Treating both as
    # punctuation would make Nidoran♀, Nidoran♂ and Nidoran indistinguishable.
    gender_aware = raw.replace("♀", " gender female ").replace(
        "♂", " gender male "
    )
    normalized = _normalize(gender_aware)
    if not normalized:
        return ""
    match = _MEANINGFUL_SUFFIX.search(raw)
    if match is None:
        return normalized
    suffix = re.sub(r"[^A-Za-z0-9]+", "", match.group(0))
    # EX and ex are different mechanics. The other suffixes are conventionally
    # uppercase and may be normalized without erasing a real identity conflict.
    semantic_suffix = suffix if suffix in {"EX", "ex"} else suffix.upper()
    return f"{normalized}|suffix:{semantic_suffix}"


_CARD_NUMBER_LABEL_PREFIX = re.compile(
    r"^(?:#\s*|no(?:\.|\s+)\s*|n[°º]\s*|number\s+)",
    flags=re.IGNORECASE,
)


def _normalize_card_number(value: object) -> str:
    compact = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = _CARD_NUMBER_LABEL_PREFIX.sub("", compact)
    compact = re.sub(r"\s+", "", compact).lstrip("#")
    parts = compact.split("/", 1)

    def canonical(part: str) -> str:
        match = re.fullmatch(r"([A-Za-z]*)(0*\d+)([A-Za-z-]*)", part)
        if not match:
            return _normalize(part).replace(" ", "")
        prefix, digits, suffix = match.groups()
        return f"{prefix.casefold()}{int(digits)}{suffix.casefold()}"

    return "/".join(canonical(part) for part in parts)


def _card_number_parts(value: object) -> tuple[str, Optional[str]]:
    normalized = _normalize_card_number(value)
    if not normalized:
        return "", None
    if "/" not in normalized:
        return normalized, None
    numerator, denominator = normalized.split("/", 1)
    return numerator, denominator or None


def _partial_card_number_equivalent(
    expected: object,
    candidate: object,
    *,
    exact_name: bool,
    set_similarity: float,
) -> bool:
    expected_number = _normalize_card_number(expected)
    candidate_number = _normalize_card_number(candidate)
    if not expected_number or not candidate_number or expected_number == candidate_number:
        return False

    expected_numerator, expected_denominator = _card_number_parts(expected)
    candidate_numerator, candidate_denominator = _card_number_parts(candidate)
    if not expected_numerator or expected_numerator != candidate_numerator:
        return False
    if (expected_denominator is None) == (candidate_denominator is None):
        return False
    return exact_name and set_similarity >= 0.86


def _numeric_tokens(value: object) -> frozenset[str]:
    return frozenset(re.findall(r"\d+(?:\.\d+)?", _normalize(value)))


def _surface(value: object) -> str:
    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).strip().split()
    )


def _number_surface(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = _CARD_NUMBER_LABEL_PREFIX.sub("", text)
    return re.sub(r"\s+", "", text).lstrip("#")


def _number_shape(value: object) -> tuple[tuple[str, int, str], ...]:
    parts = _number_surface(value).split("/", 1)
    result = []
    for part in parts:
        match = re.fullmatch(r"([A-Za-z]*)(\d+)([A-Za-z-]*)", part)
        if match is None:
            return ()
        prefix, digits, suffix = match.groups()
        result.append((prefix.casefold(), int(digits), suffix.casefold()))
    return tuple(result)


def _card_number_difference(expected: object, candidate: object) -> str:
    expected_surface = _number_surface(expected)
    candidate_surface = _number_surface(candidate)
    expected_normalized = _normalize_card_number(expected)
    candidate_normalized = _normalize_card_number(candidate)

    if expected_normalized and expected_normalized == candidate_normalized:
        expected_shape = _number_shape(expected)
        candidate_shape = _number_shape(candidate)
        if (
            expected_shape
            and expected_shape == candidate_shape
            and expected_surface.casefold() != candidate_surface.casefold()
        ):
            return NUMBER_DIFF_LEADING_ZERO
        if expected_surface != candidate_surface:
            return NUMBER_DIFF_ALPHANUMERIC_CASE
        return NUMBER_DIFF_OTHER

    expected_numerator, expected_denominator = _card_number_parts(expected)
    candidate_numerator, candidate_denominator = _card_number_parts(candidate)
    if expected_numerator and expected_numerator == candidate_numerator:
        if expected_denominator is None and candidate_denominator is not None:
            return NUMBER_DIFF_LISTING_NUMERATOR_ONLY
        if candidate_denominator is None and expected_denominator is not None:
            return NUMBER_DIFF_CANDIDATE_NUMERATOR_ONLY
        if (
            expected_denominator
            and candidate_denominator
            and expected_denominator != candidate_denominator
        ):
            return NUMBER_DIFF_DENOMINATOR_CONFLICT

    expected_shape = _number_shape(expected)
    candidate_shape = _number_shape(candidate)
    if expected_shape and candidate_shape:
        expected_first = expected_shape[0]
        candidate_first = candidate_shape[0]
        if expected_first[1] == candidate_first[1]:
            expected_has_prefix = bool(expected_first[0])
            candidate_has_prefix = bool(candidate_first[0])
            if expected_has_prefix or candidate_has_prefix:
                return NUMBER_DIFF_PREFIX_FAMILY
            if expected_first != candidate_first:
                return NUMBER_DIFF_CONTRADICTORY_AFFIX
    return NUMBER_DIFF_OTHER


def _canonical_set_label(value: object) -> str:
    normalized = _normalize(value)
    for prefix in ("pokemon trading card game ", "pokemon tcg "):
        if normalized.startswith(prefix):
            return normalized[len(prefix):].strip()
    return normalized


def _set_wrapper_removed(value: object) -> bool:
    normalized = _normalize(value)
    return any(
        normalized.startswith(prefix)
        for prefix in ("pokemon trading card game ", "pokemon tcg ")
    )


def _has_non_latin_script(value: object) -> bool:
    return any(
        ("\u3040" <= character <= "\u30ff")
        or ("\u3400" <= character <= "\u9fff")
        or ("\uac00" <= character <= "\ud7af")
        or ("\u0400" <= character <= "\u04ff")
        for character in str(value or "")
    )


_LANGUAGE_MARKERS = frozenset(
    {
        "english",
        "french",
        "francais",
        "german",
        "deutsch",
        "italian",
        "italiano",
        "spanish",
        "espanol",
        "japanese",
        "japonais",
        "korean",
        "chinese",
    }
)


def _looks_localized(left: object, right: object) -> bool:
    if _has_non_latin_script(left) != _has_non_latin_script(right):
        return True
    left_markers = set(_normalize(left).split()) & _LANGUAGE_MARKERS
    right_markers = set(_normalize(right).split()) & _LANGUAGE_MARKERS
    return left_markers != right_markers and bool(left_markers or right_markers)


_SUBSET_MARKERS = frozenset(
    {
        "gallery",
        "subset",
        "vault",
        "trainer",
        "galarian",
        "classic",
    }
)


def _single_set_difference(expected: object, candidate: object) -> str:
    if not str(expected or "").strip() or not str(candidate or "").strip():
        return SET_DIFF_NO_RELATION
    if _looks_localized(expected, candidate):
        return SET_DIFF_LANGUAGE_LOCALIZATION
    expected_norm = _canonical_set_label(expected)
    candidate_norm = _canonical_set_label(candidate)
    if not expected_norm or not candidate_norm:
        return SET_DIFF_NO_RELATION
    if expected_norm == candidate_norm:
        if _set_wrapper_removed(expected) != _set_wrapper_removed(candidate):
            return SET_DIFF_POKEMON_TCG_WRAPPER
        expected_surface = _surface(expected).casefold()
        candidate_surface = _surface(candidate).casefold()
        if expected_surface == candidate_surface:
            return SET_DIFF_EXACT_NORMALIZED
        return SET_DIFF_PUNCTUATION_SPACING
    expected_tokens = expected_norm.split()
    candidate_tokens = candidate_norm.split()
    short, long = (
        (expected_norm, candidate_norm)
        if len(expected_norm) <= len(candidate_norm)
        else (candidate_norm, expected_norm)
    )
    if short and re.search(rf"(?:^| ){re.escape(short)}(?: |$)", long):
        longer_raw = str(candidate if long == candidate_norm else expected)
        extra_tokens = set(long.split()) - set(short.split())
        if (
            re.search(r"\s(?:[-:–—/]|\()\s*", longer_raw)
            or extra_tokens & _SUBSET_MARKERS
        ):
            return SET_DIFF_PARENT_SUBSET
        return SET_DIFF_DANGEROUS_CONTAINMENT
    expected_token_set = set(expected_tokens)
    candidate_token_set = set(candidate_tokens)
    if (
        expected_token_set <= candidate_token_set
        or candidate_token_set <= expected_token_set
        or len(expected_token_set & candidate_token_set) >= 2
    ):
        return SET_DIFF_SIGNIFICANT_EXTRA_TOKENS
    return SET_DIFF_NO_RELATION


def _set_difference(
    expected: object, candidate_name: object, candidate_slug: object = None
) -> str:
    named_category = _single_set_difference(expected, candidate_name)
    if named_category != SET_DIFF_NO_RELATION or not candidate_slug:
        return named_category
    return _single_set_difference(expected, candidate_slug)


def _semantic_name_suffix(value: object) -> tuple[str, Optional[str]]:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    match = _MEANINGFUL_SUFFIX.search(raw)
    if match is None:
        return _normalize(raw), None
    suffix = re.sub(r"[^A-Za-z0-9]+", "", match.group(0))
    semantic_suffix = suffix if suffix in {"EX", "ex"} else suffix.upper()
    return _normalize(raw[: match.start()]), semantic_suffix


_SIGNIFICANT_NAME_PREFIXES = (
    "team rocket s ",
    "rocket s ",
    "dark ",
    "light ",
    "shining ",
    "radiant ",
    "mega ",
    "primal ",
    "alolan ",
    "galarian ",
    "hisuian ",
    "paldean ",
)


def _card_name_difference(
    expected: object, candidate: object, language: object = None
) -> str:
    expected_raw = unicodedata.normalize("NFKC", str(expected or "")).strip()
    candidate_raw = unicodedata.normalize("NFKC", str(candidate or "")).strip()
    expected_gender = frozenset(re.findall(r"[♀♂]", expected_raw))
    candidate_gender = frozenset(re.findall(r"[♀♂]", candidate_raw))
    if expected_gender != candidate_gender and (expected_gender or candidate_gender):
        return NAME_DIFF_GENDER

    expected_base, expected_suffix = _semantic_name_suffix(expected_raw)
    candidate_base, candidate_suffix = _semantic_name_suffix(candidate_raw)
    if expected_base == candidate_base and expected_suffix != candidate_suffix:
        return NAME_DIFF_MECHANIC_SUFFIX
    if expected_raw.casefold() == candidate_raw.casefold():
        return NAME_DIFF_CASE

    expected_norm = _normalize_card_name(expected_raw)
    candidate_norm = _normalize_card_name(candidate_raw)
    if expected_norm and expected_norm == candidate_norm:
        return NAME_DIFF_PUNCTUATION_ACCENTS

    for prefix in _SIGNIFICANT_NAME_PREFIXES:
        if (
            expected_norm.startswith(prefix)
            and expected_norm[len(prefix) :] == candidate_norm
        ) or (
            candidate_norm.startswith(prefix)
            and candidate_norm[len(prefix) :] == expected_norm
        ):
            return NAME_DIFF_SIGNIFICANT_PREFIX

    normalized_language = _normalize(language)
    non_english_language = normalized_language not in {
        "",
        "en",
        "english",
        "anglais",
    }
    if _has_non_latin_script(expected_raw) != _has_non_latin_script(candidate_raw):
        return NAME_DIFF_LOCALIZATION
    if non_english_language and expected_norm and candidate_norm:
        return NAME_DIFF_LOCALIZATION
    return NAME_DIFF_SIGNIFICANT


def _single_set_similarity(expected: object, candidate: object) -> float:
    expected_norm = _canonical_set_label(expected)
    candidate_norm = _canonical_set_label(candidate)
    if not expected_norm or not candidate_norm:
        return 0.0
    if expected_norm == candidate_norm:
        return 1.0

    expected_numbers = _numeric_tokens(expected)
    candidate_numbers = _numeric_tokens(candidate)
    if expected_numbers != candidate_numbers and (expected_numbers or candidate_numbers):
        return 0.0

    expected_tokens = set(expected_norm.split())
    candidate_tokens = set(candidate_norm.split())
    intersection = len(expected_tokens & candidate_tokens)
    union = len(expected_tokens | candidate_tokens)
    jaccard = intersection / union if union else 0.0
    # Similarity below the acceptance threshold remains useful for diagnostics,
    # but containment alone is not an alias: Team Rocket and Team Rocket
    # Returns are different sets. Only exact labels after a known wrapper is
    # removed may reach the matching threshold.
    return min(jaccard, 0.65)


def _set_similarity(
    expected: object, candidate_name: object, candidate_slug: object = None
) -> float:
    if not _normalize(expected):
        return 1.0
    return max(
        _single_set_similarity(expected, candidate_name),
        _single_set_similarity(expected, candidate_slug),
    )


def _variant_family(value: object) -> str:
    """Compatibility shim for older callers.

    New identity matching uses structured variant semantics. This function only
    exposes the broad finish family for visual filtering/tests that still import
    it. Edition/promo semantics must use ``variant_compatibility`` instead.
    """

    semantics = semantics_from_text(value)
    if semantics.special_finish:
        return semantics.special_finish
    if semantics.finish == FINISH_HOLO:
        return "holofoil"
    if semantics.finish == FINISH_REVERSE:
        return "reverse holofoil"
    if semantics.finish == FINISH_STANDARD:
        return "standard"
    return _normalize(value)


def _candidate_evidence(
    identity: CardIdentity,
    candidate: Mapping[str, object],
    *,
    set_bridge: Optional[SetBridgeDecision] = None,
) -> CandidateMatchEvidence:
    product_type = _normalize(candidate.get("productType"))

    expected_name = _normalize_card_name(identity.card_name)
    candidate_name = _normalize_card_name(candidate.get("name"))
    name_supplied = bool(expected_name)
    name_matched = bool(name_supplied and candidate_name == expected_name)
    name_difference = _card_name_difference(
        identity.card_name,
        candidate.get("name"),
        identity.language,
    )

    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    set_slug = set_payload.get("slug") if isinstance(set_payload, Mapping) else None
    set_supplied = bool(_normalize(identity.set))
    set_similarity = _set_similarity(identity.set, set_name, set_slug)
    set_matched_before_bridge = bool(set_supplied and set_similarity >= 0.66)
    set_matched = set_matched_before_bridge
    set_difference = _set_difference(identity.set, set_name, set_slug)

    expected_number = _normalize_card_number(identity.card_number)
    candidate_number = _normalize_card_number(candidate.get("cardNumber"))
    card_number_supplied = bool(expected_number)
    number_exact = bool(card_number_supplied and candidate_number == expected_number)
    card_number_difference = _card_number_difference(
        identity.card_number, candidate.get("cardNumber")
    )
    number_partial = _partial_card_number_equivalent(
        identity.card_number,
        candidate.get("cardNumber"),
        exact_name=name_matched,
        set_similarity=set_similarity,
    )
    card_number_matched = bool(
        card_number_supplied and (number_exact or number_partial)
    )

    # A set bridge is never a substitute for another core field.  Even a
    # registry bug or a misused decision cannot bridge a candidate unless name
    # and collector number are independently exact.
    set_bridged = bool(
        set_bridge is not None
        and set_bridge.status == SET_BRIDGE_EXACT
        and name_matched
        and number_exact
    )
    if set_bridged:
        set_matched = True
        set_similarity = 1.0

    failed_core_fields = tuple(
        field_name
        for field_name, supplied, matched in (
            ("name", name_supplied, name_matched),
            ("set", set_supplied, set_matched),
            ("card_number", card_number_supplied, card_number_matched),
        )
        if supplied and not matched
    )

    variant = variant_compatibility(identity, candidate)

    rejection = None
    if product_type and product_type != "single":
        rejection = REJECT_PRODUCT_TYPE
    elif name_supplied and not name_matched:
        rejection = REJECT_CARD_NAME
    elif set_supplied and not set_matched:
        rejection = REJECT_SET
    elif card_number_supplied and not card_number_matched:
        rejection = REJECT_CARD_NUMBER
    elif not variant.compatible:
        rejection = REJECT_VARIANT

    supplied_core = sum((name_supplied, set_supplied, card_number_supplied))
    if rejection is None and supplied_core < 2:
        rejection = REJECT_INSUFFICIENT
    if (
        rejection is None
        and not name_supplied
        and (not card_number_supplied or set_similarity < 0.86)
    ):
        rejection = REJECT_INSUFFICIENT
    if (
        rejection is None
        and not card_number_supplied
        and (not name_supplied or not set_supplied or set_similarity < 0.86)
    ):
        rejection = REJECT_INSUFFICIENT

    score = None
    if rejection is None:
        score = 4.0 if name_matched else 0.0
        if number_exact:
            score += 4.0
        elif number_partial:
            score += 3.0
        score += set_similarity * 3.0
        # Variant evidence is deliberately a tie-breaker, never a substitute
        # for exact core identity fields.
        score += 0.35 * sum(
            (
                variant.finish_match,
                variant.edition_match,
                variant.promo_match,
            )
        )
        if variant.exact:
            score += 0.25
        score += 0.5 * supplied_core

    return CandidateMatchEvidence(
        name_supplied=name_supplied,
        set_supplied=set_supplied,
        card_number_supplied=card_number_supplied,
        name_matched=name_matched,
        set_matched=set_matched,
        set_matched_before_bridge=set_matched_before_bridge,
        card_number_matched=card_number_matched,
        number_exact=number_exact,
        number_partial=number_partial,
        set_similarity=set_similarity,
        failed_core_fields=failed_core_fields,
        score=score,
        rejection=rejection,
        variant_compatible=variant.compatible,
        variant_exact=variant.exact,
        variant_reason=variant.reason,
        variant_finish_match=variant.finish_match,
        variant_edition_match=variant.edition_match,
        variant_promo_match=variant.promo_match,
        variant_metadata_missing=variant.metadata_missing,
        name_difference=name_difference,
        set_difference=set_difference,
        card_number_difference=card_number_difference,
        set_bridged=set_bridged,
        set_bridge_status=(set_bridge.status if set_bridge is not None else None),
        set_bridge_reason=(set_bridge.reason if set_bridge is not None else None),
    )


def _candidate_score_and_rejection(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> tuple[Optional[float], Optional[str]]:
    evidence = _candidate_evidence(identity, candidate)
    return evidence.score, evidence.rejection
