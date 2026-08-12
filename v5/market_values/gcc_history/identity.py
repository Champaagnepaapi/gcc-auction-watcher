from __future__ import annotations

import re
import unicodedata
from typing import Optional, Tuple

from ...models import CardIdentity
from ..models import normalize_identity_text
from .models import CanonicalCollectible, GCCSale, IdentityMatch, MatchClass


_LANGUAGE_ALIASES = {
    "en": "english",
    "eng": "english",
    "anglais": "english",
    "english": "english",
    "fr": "french",
    "fra": "french",
    "francais": "french",
    "french": "french",
    "ja": "japanese",
    "jp": "japanese",
    "jpn": "japanese",
    "japonais": "japanese",
    "japanese": "japanese",
    "de": "german",
    "deu": "german",
    "allemand": "german",
    "german": "german",
    "it": "italian",
    "italien": "italian",
    "italian": "italian",
    "es": "spanish",
    "espagnol": "spanish",
    "spanish": "spanish",
}


def _ascii(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def normalize_card_number(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = _ascii(str(value)).casefold().strip()
    normalized = re.sub(r"^(?:no\.?|n°|#)\s*", "", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    normalized = re.sub(r"[^a-z0-9/]+", "", normalized)
    return normalized or None


def normalize_language(value: Optional[str]) -> Optional[str]:
    normalized = normalize_identity_text(value)
    if not normalized:
        return None
    return _LANGUAGE_ALIASES.get(normalized, normalized)


def normalize_finish(value: Optional[str]) -> Optional[str]:
    normalized = normalize_identity_text(value)
    if not normalized:
        return None
    if "reverse" in normalized:
        return "reverse_holo"
    if any(token in normalized for token in ("non holo", "nonholo", "regular")):
        return "non_holo"
    if any(token in normalized for token in ("holo", "holographic", "holographique")):
        return "holo"
    return normalized.replace(" ", "_")


def _optional_bool_from_text(value: Optional[str], positive: Tuple[str, ...]) -> Optional[bool]:
    normalized = normalize_identity_text(value)
    if not normalized:
        return None
    if any(token in normalized for token in positive):
        return True
    return None


def _first_edition(value: Optional[str]) -> Optional[bool]:
    normalized = normalize_identity_text(value)
    if not normalized:
        return None
    if any(token in normalized for token in ("1st edition", "first edition", "1ere edition", "premiere edition")):
        return True
    if "unlimited" in normalized or "illimitee" in normalized:
        return False
    return None


def canonical_from_card_identity(identity: CardIdentity) -> CanonicalCollectible:
    joined_variant_and_edition = " ".join(
        part for part in (identity.variant, identity.edition) if part
    )
    normalized_variant = normalize_identity_text(identity.variant) or None
    normalized_finish = normalize_finish(identity.finish)
    variant_finish = normalize_finish(identity.variant)
    if variant_finish not in {"holo", "reverse_holo", "non_holo"}:
        variant_finish = None
    special_print = normalized_variant
    if special_print in {
        "unlimited",
        "1st edition",
        "first edition",
        "holo",
        "reverse holo",
        "non holo",
        "promo",
        "stamped",
    }:
        special_print = None
    return CanonicalCollectible(
        card_name=normalize_identity_text(identity.card_name) or None,
        set_name=normalize_identity_text(identity.set) or None,
        card_number=normalize_card_number(identity.card_number),
        language=normalize_language(identity.language),
        variant=normalized_variant,
        first_edition=_first_edition(joined_variant_and_edition),
        finish=normalized_finish or variant_finish,
        promo=_optional_bool_from_text(
            " ".join(filter(None, (identity.set, identity.variant))), ("promo",)
        ),
        stamped=_optional_bool_from_text(
            joined_variant_and_edition, ("stamped", "stamp")
        ),
        special_print=special_print,
        year=identity.year,
        set_family=normalize_identity_text(identity.set) or None,
        category="pokemon",
    )


def canonicalize_collectible(identity: CanonicalCollectible) -> CanonicalCollectible:
    return CanonicalCollectible(
        card_name=normalize_identity_text(identity.card_name) or None,
        set_name=normalize_identity_text(identity.set_name) or None,
        card_number=normalize_card_number(identity.card_number),
        language=normalize_language(identity.language),
        variant=normalize_identity_text(identity.variant) or None,
        first_edition=identity.first_edition,
        finish=normalize_finish(identity.finish),
        promo=identity.promo,
        stamped=identity.stamped,
        special_print=normalize_identity_text(identity.special_print) or None,
        year=identity.year,
        set_family=normalize_identity_text(identity.set_family) or None,
        category=normalize_identity_text(identity.category) or None,
    )


def match_identity(
    target: CanonicalCollectible, candidate: CanonicalCollectible | GCCSale
) -> IdentityMatch:
    target = canonicalize_collectible(target)
    candidate_identity = candidate.identity if isinstance(candidate, GCCSale) else candidate
    candidate_identity = canonicalize_collectible(candidate_identity)

    matched: list[str] = []
    missing: list[str] = []
    conflicts: list[str] = []
    candidate_only_discriminators: list[str] = []
    score = 0

    required = (
        ("card_name", target.card_name, candidate_identity.card_name, 35),
        ("set_name", target.set_name, candidate_identity.set_name, 30),
        ("card_number", target.card_number, candidate_identity.card_number, 30),
    )
    discriminators = (
        ("language", target.language, candidate_identity.language),
        ("variant", target.variant, candidate_identity.variant),
        ("first_edition", target.first_edition, candidate_identity.first_edition),
        ("finish", target.finish, candidate_identity.finish),
        ("promo", target.promo, candidate_identity.promo),
        ("stamped", target.stamped, candidate_identity.stamped),
        ("special_print", target.special_print, candidate_identity.special_print),
    )

    for field_name, expected, actual, weight in required:
        if expected is None or actual is None:
            missing.append(field_name)
        elif expected == actual:
            matched.append(field_name)
            score += weight
        else:
            conflicts.append(field_name)

    for field_name, expected, actual in discriminators:
        if expected is None and actual is not None:
            candidate_only_discriminators.append(field_name)
            missing.append(f"target_{field_name}")
        elif expected is None or actual is None:
            if expected is not None:
                missing.append(field_name)
        elif expected == actual:
            matched.append(field_name)
            score += 5
        else:
            conflicts.append(field_name)

    if conflicts:
        return IdentityMatch(
            match_class=MatchClass.REJECTED,
            score=max(0, score - 20 * len(conflicts)),
            matched_fields=tuple(matched),
            missing_fields=tuple(missing),
            conflicts=tuple(conflicts),
            reason="known identity conflict: " + ", ".join(conflicts),
        )

    required_matched = {name for name, *_ in required if name in matched}
    if required_matched == {"card_name", "set_name", "card_number"}:
        if candidate_only_discriminators:
            return IdentityMatch(
                match_class=MatchClass.AMBIGUOUS,
                score=min(79, score),
                matched_fields=tuple(matched),
                missing_fields=tuple(missing),
                conflicts=(),
                reason=(
                    "exact core identity, but target lacks candidate variant evidence: "
                    + ", ".join(candidate_only_discriminators)
                ),
            )
        return IdentityMatch(
            match_class=MatchClass.EXACT_MATCH,
            score=min(100, score),
            matched_fields=tuple(matched),
            missing_fields=tuple(missing),
            conflicts=(),
            reason="card name, set and card number match with no known conflict",
        )

    discriminator_matches = [name for name in matched if name not in required_matched]
    name_and_number = {"card_name", "card_number"}.issubset(required_matched)
    name_and_set_supported = (
        {"card_name", "set_name"}.issubset(required_matched)
        and bool(discriminator_matches)
    )
    if (name_and_number or name_and_set_supported) and not candidate_only_discriminators:
        return IdentityMatch(
            match_class=MatchClass.STRONG_MATCH,
            score=min(94, score),
            matched_fields=tuple(matched),
            missing_fields=tuple(missing),
            conflicts=(),
            reason="strong partial identity with discriminating evidence and no known conflict",
        )

    return IdentityMatch(
        match_class=MatchClass.AMBIGUOUS,
        score=min(79, score),
        matched_fields=tuple(matched),
        missing_fields=tuple(missing),
        conflicts=(),
        reason="identity is incomplete; name-only comparables are never valued",
    )
