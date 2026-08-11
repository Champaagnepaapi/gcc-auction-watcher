from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping, Optional

from .models import CardIdentity


REJECT_PRODUCT_TYPE = "product_type"
REJECT_CARD_NUMBER = "card_number"
REJECT_CARD_NAME = "card_name"
REJECT_SET = "set"
REJECT_VARIANT = "variant"
REJECT_INSUFFICIENT = "insufficient"


@dataclass(frozen=True)
class CandidateMatchEvidence:
    name_supplied: bool
    set_supplied: bool
    card_number_supplied: bool
    name_matched: bool
    set_matched: bool
    card_number_matched: bool
    number_exact: bool
    number_partial: bool
    set_similarity: float
    failed_core_fields: tuple[str, ...]
    score: Optional[float]
    rejection: Optional[str]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


_MEANINGFUL_SUFFIX = re.compile(
    r"(?<![A-Za-z0-9])(?:VSTAR|VMAX|V-UNION|V|GX|EX|ex|LV\.?\s*X|BREAK|PRIME|LEGEND)\s*$"
)


def _normalize_card_name(value: object) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    normalized = _normalize(raw)
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


def _normalize_card_number(value: object) -> str:
    compact = re.sub(r"\s+", "", str(value or "")).lstrip("#")
    parts = compact.split("/", 1)

    def canonical(part: str) -> str:
        match = re.fullmatch(r"0*(\d+)([A-Za-z]*)", part)
        if not match:
            return _normalize(part).replace(" ", "")
        return f"{int(match.group(1))}{match.group(2).casefold()}"

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


def _single_set_similarity(expected: object, candidate: object) -> float:
    expected_norm = _normalize(expected)
    candidate_norm = _normalize(candidate)
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
    shorter, longer = sorted((expected_tokens, candidate_tokens), key=len)
    if shorter and shorter.issubset(longer) and intersection:
        return max(jaccard, 0.86)
    return jaccard


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
    normalized = _normalize(value)
    aliases = {
        "holo": "holofoil",
        "holographic": "holofoil",
        "holofoil": "holofoil",
        "reverse holo": "reverse holofoil",
        "reverse holographic": "reverse holofoil",
        "reverse holofoil": "reverse holofoil",
        "normal": "standard",
        "non holo": "standard",
        "standard": "standard",
    }
    return aliases.get(normalized, normalized)


def _candidate_evidence(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> CandidateMatchEvidence:
    product_type = _normalize(candidate.get("productType"))

    expected_name = _normalize_card_name(identity.card_name)
    candidate_name = _normalize_card_name(candidate.get("name"))
    name_supplied = bool(expected_name)
    name_matched = bool(name_supplied and candidate_name == expected_name)

    set_payload = candidate.get("set")
    set_name = set_payload.get("name") if isinstance(set_payload, Mapping) else None
    set_slug = set_payload.get("slug") if isinstance(set_payload, Mapping) else None
    set_supplied = bool(_normalize(identity.set))
    set_similarity = _set_similarity(identity.set, set_name, set_slug)
    set_matched = bool(set_supplied and set_similarity >= 0.66)

    expected_number = _normalize_card_number(identity.card_number)
    candidate_number = _normalize_card_number(candidate.get("cardNumber"))
    card_number_supplied = bool(expected_number)
    number_exact = bool(card_number_supplied and candidate_number == expected_number)
    number_partial = _partial_card_number_equivalent(
        identity.card_number,
        candidate.get("cardNumber"),
        exact_name=name_matched,
        set_similarity=set_similarity,
    )
    card_number_matched = bool(
        card_number_supplied and (number_exact or number_partial)
    )

    failed_core_fields = tuple(
        field_name
        for field_name, supplied, matched in (
            ("name", name_supplied, name_matched),
            ("set", set_supplied, set_matched),
            ("card_number", card_number_supplied, card_number_matched),
        )
        if supplied and not matched
    )

    rejection = None
    if product_type and product_type != "single":
        rejection = REJECT_PRODUCT_TYPE
    elif name_supplied and not name_matched:
        rejection = REJECT_CARD_NAME
    elif set_supplied and not set_matched:
        rejection = REJECT_SET
    elif card_number_supplied and not card_number_matched:
        rejection = REJECT_CARD_NUMBER

    expected_variant = _variant_family(identity.variant)
    candidate_variant = _variant_family(candidate.get("variant"))
    if (
        rejection is None
        and expected_variant
        and candidate_variant
        and expected_variant != candidate_variant
    ):
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
        if expected_variant and candidate_variant == expected_variant:
            score += 1.0
        score += 0.5 * supplied_core

    return CandidateMatchEvidence(
        name_supplied=name_supplied,
        set_supplied=set_supplied,
        card_number_supplied=card_number_supplied,
        name_matched=name_matched,
        set_matched=set_matched,
        card_number_matched=card_number_matched,
        number_exact=number_exact,
        number_partial=number_partial,
        set_similarity=set_similarity,
        failed_core_fields=failed_core_fields,
        score=score,
        rejection=rejection,
    )


def _candidate_score_and_rejection(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> tuple[Optional[float], Optional[str]]:
    evidence = _candidate_evidence(identity, candidate)
    return evidence.score, evidence.rejection
