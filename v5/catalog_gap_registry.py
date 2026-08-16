"""Versioned, fail-closed catalogue gaps for exact physical card identities.

This registry is deliberately tiny.  It is NOT a generic fallback for a
TCGdex no-match.  An entry may be used only when all listed deterministic
coordinates agree exactly.  Each entry carries explicit provenance and may
supply microvariant *applicability* only when that applicability has been
manually verified from independent catalogue evidence.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Optional, Tuple

from .microvariants import (
    CURATED_EXACT_CATALOG_SOURCE,
    MICROVARIANT_NOT_APPLICABLE,
    MicrovariantApplicability,
)
from .models import CardIdentity
from .variant_semantics import FINISH_HOLO


@dataclass(frozen=True)
class CuratedCatalogGapEntry:
    registry_id: str
    language_labels: Tuple[str, ...]
    card_names: Tuple[str, ...]
    card_number: str
    accepted_set_labels: Tuple[str, ...]
    canonical_set: str
    year: int
    single_finish: str
    promo: bool
    provenance_urls: Tuple[str, ...]


@dataclass(frozen=True)
class CuratedCatalogGapMatch:
    identity: CardIdentity
    applicability: MicrovariantApplicability
    registry_id: str
    provenance_urls: Tuple[str, ...]


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _normalize_card_number(value: object) -> str:
    raw = re.sub(r"\s+", "", str(value or "")).upper()
    match = re.fullmatch(r"0*(\d+)/M-P", raw)
    if match:
        return f"{int(match.group(1)):03d}/M-P"
    return raw


def _is_pokemon_tcg_game(value: object) -> bool:
    return _normalize(value) in {
        "pokemon tcg",
        "pokemon trading card game",
    }


def _remove_resolved_game_ambiguity(identity: CardIdentity) -> Tuple[str, ...]:
    """Remove only a game ambiguity once the exact curated card proves the game."""

    return tuple(
        ambiguity
        for ambiguity in identity.ambiguities
        if not str(ambiguity).strip().casefold().startswith("game:")
    )


_ENTRIES = (
    CuratedCatalogGapEntry(
        registry_id="ktcg-mp-040-magikarp-2026-v1",
        language_labels=("korean", "coreen", "ko"),
        card_names=("magikarp",),
        card_number="040/M-P",
        accepted_set_labels=(
            "promo cards",
            "m p promotional cards",
            "m p promos",
            "pokemon go",
        ),
        canonical_set="M-P Promotional cards",
        year=2026,
        single_finish=FINISH_HOLO,
        promo=True,
        provenance_urls=(
            "https://bulbapedia.bulbagarden.net/wiki/M-P_Promotional_cards_(KTCG)",
            "https://www.wikidex.net/wiki/Magikarp_(Pok%C3%A9mon_MEGA_Festa_2026_promo_KTCG)",
        ),
    ),
)


def resolve_curated_catalog_gap(identity: CardIdentity) -> Optional[CuratedCatalogGapMatch]:
    """Return an exact curated catalogue result, or ``None``.

    Required coordinates are card name + printed number + language + a bounded
    explicit set alias.  Explicit year/game contradictions fail closed.  No
    fuzzy name, set or number matching is used.
    """

    if not identity.card_name or not identity.card_number or not identity.language:
        return None
    if not identity.set:
        return None

    normalized_name = _normalize(identity.card_name)
    normalized_language = _normalize(identity.language)
    normalized_set = _normalize(identity.set)
    normalized_number = _normalize_card_number(identity.card_number)

    for entry in _ENTRIES:
        if normalized_name not in {_normalize(value) for value in entry.card_names}:
            continue
        if normalized_language not in {
            _normalize(value) for value in entry.language_labels
        }:
            continue
        if normalized_number != entry.card_number:
            continue
        if normalized_set not in set(entry.accepted_set_labels):
            continue
        if identity.year is not None and identity.year != entry.year:
            continue
        if identity.game and not _is_pokemon_tcg_game(identity.game):
            continue

        remaining_ambiguities = _remove_resolved_game_ambiguity(identity)
        if remaining_ambiguities:
            continue
        resolved = replace(
            identity,
            game="Pokémon TCG",
            set=entry.canonical_set,
            card_number=entry.card_number,
            year=identity.year or entry.year,
            ambiguities=remaining_ambiguities,
        )
        applicability = MicrovariantApplicability(
            status=MICROVARIANT_NOT_APPLICABLE,
            source=CURATED_EXACT_CATALOG_SOURCE,
            single_finish=entry.single_finish,
            finish_proven_single=True,
            finish_multiple_variants=False,
            edition_proven_single=True,
            edition_multiple_variants=False,
            single_promo=entry.promo,
            promo_proven_single=True,
        )
        return CuratedCatalogGapMatch(
            identity=resolved,
            applicability=applicability,
            registry_id=entry.registry_id,
            provenance_urls=entry.provenance_urls,
        )
    return None
