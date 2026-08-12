from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Tuple

from .models import CardIdentity
from .microvariants import (
    EDITION_FIRST,
    EDITION_SHADOWLESS,
    EDITION_UNLIMITED,
    FIRST_EDITION_CONFIRMED,
    MICROVARIANT_APPLICABLE,
    MICROVARIANT_NOT_APPLICABLE,
    MicrovariantApplicability,
    MicrovariantResolution,
)
from .variant_semantics import semantics_from_identity, semantics_from_poketrace_candidate


# Stable machine-readable reason codes
MISSING_NAME = "MISSING_NAME"
MISSING_SET = "MISSING_SET"
MISSING_NUMBER = "MISSING_NUMBER"
DENOMINATOR_CONFLICT = "DENOMINATOR_CONFLICT"
MULTIPLE_CANONICAL_CANDIDATES = "MULTIPLE_CANONICAL_CANDIDATES"
TCGDEX_SEARCH_ERROR = "TCGDEX_SEARCH_ERROR"
TCGDEX_DETAIL_ERROR = "TCGDEX_DETAIL_ERROR"
POKETRACE_SET_MISMATCH = "POKETRACE_SET_MISMATCH"
POKETRACE_NUMBER_MISMATCH = "POKETRACE_NUMBER_MISMATCH"
POKETRACE_NAME_MISMATCH = "POKETRACE_NAME_MISMATCH"
VISUAL_NO_CANDIDATE = "VISUAL_NO_CANDIDATE"
VISUAL_MARGIN_TOO_SMALL = "VISUAL_MARGIN_TOO_SMALL"
VARIANT_FIRST_EDITION_UNKNOWN = "VARIANT_FIRST_EDITION_UNKNOWN"
VARIANT_FINISH_UNKNOWN = "VARIANT_FINISH_UNKNOWN"
VARIANT_MULTIPLE_COMPATIBLE = "VARIANT_MULTIPLE_COMPATIBLE"
VARIANT_UNKNOWN_FIELD_ONLY = "VARIANT_UNKNOWN_FIELD_ONLY"
VARIANT_SINGLE_COMPATIBLE = "VARIANT_SINGLE_COMPATIBLE"
COMMERCIAL_COLLISION_PROVEN = "COMMERCIAL_COLLISION_PROVEN"
NUMBER_UNPROVEN = "NUMBER_UNPROVEN"
SET_UNPROVEN = "SET_UNPROVEN"
NAME_UNPROVEN = "NAME_UNPROVEN"
LISTING_FIELD_CONFLICT = "LISTING_FIELD_CONFLICT"


def ambiguity_fields(identity: CardIdentity) -> Tuple[str, ...]:
    allowed = {
        "game", "card_name", "set", "card_number", "language", "year",
        "variant", "rarity", "finish", "edition", "illustrator",
    }
    fields = []
    for ambiguity in identity.ambiguities:
        text = str(ambiguity or "").strip()
        prefix = text.split(":", 1)[0].strip().casefold()
        if prefix in allowed:
            fields.append(prefix)
        elif "catalog_identity_ambiguous" in text.casefold():
            fields.append("catalog")
        elif "denominator" in text.casefold():
            fields.append("card_number")
        else:
            fields.append("other")
    return tuple(dict.fromkeys(fields))


def sanitize_title(title: Optional[str], max_length: int = 80) -> str:
    """Sanitize listing titles to strip control/newline characters and bound length."""
    if not title:
        return "UNKNOWN"
    # Strip newlines, tabs, control characters, and collapse consecutive whitespaces
    cleaned = re.sub(r"[\r\n\t\x00-\x1f\x7f-\x9f]+", " ", str(title)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip() + "..."
    return cleaned or "UNKNOWN"


@dataclass(frozen=True)
class CoordinateState:
    name: str = "missing"  # known, missing, conflicting
    set_name: str = "missing"
    number: str = "missing"
    denominator: str = "missing"


@dataclass(frozen=True)
class NearMatchDiff:
    candidate_id: str
    target_name: str
    target_set: str
    target_number: str
    candidate_name: str
    candidate_set: str
    candidate_number: str
    diff_kind: str  # SET_ONLY, NUMBER_ONLY, NAME_ONLY, MULTIPLE
    differences: Tuple[str, ...]


@dataclass(frozen=True)
class VariantDiagnostic:
    record: int
    item_id: Optional[str]
    macro_identity: str
    blocking_dimension: str
    possible_variant_values: Tuple[str, ...]
    commercially_distinct_candidates: int
    collision_proven: bool
    target_evidence: str
    catalog_evidence: str
    provider_evidence: str
    current_block_reason: str
    variant_block_maybe_unnecessary: bool
    variant_block_basis: str  # REAL_COLLISION, SINGLE_COMPATIBLE, UNKNOWN_FIELD_ONLY

    def format_block(self) -> str:
        lines = [
            "[V5_VARIANT_DIAG]",
            f"record={self.record}",
            f"item_id={self.item_id or 'UNKNOWN'}",
            f"macro_identity={self.macro_identity}",
            f"blocking_dimension={self.blocking_dimension}",
            f"possible_variant_values={list(self.possible_variant_values)}",
            f"commercially_distinct_candidates={self.commercially_distinct_candidates}",
            f"collision_proven={str(self.collision_proven).lower()}",
            f"target_evidence={self.target_evidence}",
            f"catalog_evidence={self.catalog_evidence}",
            f"provider_evidence={self.provider_evidence}",
            f"current_block_reason={self.current_block_reason}",
            f"variant_block_maybe_unnecessary={str(self.variant_block_maybe_unnecessary).lower()}",
            f"variant_block_basis={self.variant_block_basis}",
        ]
        return "\n".join(lines)


@dataclass(frozen=True)
class UnresolvedIdentityDiagnostic:
    record: int
    item_id: Optional[str]
    title: str
    card_name: Optional[str]
    set_name: Optional[str]
    card_number: Optional[str]
    language: Optional[str]
    final_status: str  # AMBIGUOUS, INSUFFICIENT, BLOCKED_VARIANT, ERROR
    coordinates: CoordinateState
    tcgdex_detail: str = "NO_QUERY"
    poketrace_detail: str = "NO_QUERY"
    visual_detail: str = "NOT_ATTEMPTED"
    reason_code: str = "UNKNOWN"
    explanation: str = ""
    near_matches: Tuple[NearMatchDiff, ...] = ()
    variant_diag: Optional[VariantDiagnostic] = None
    ambiguity_fields: Tuple[str, ...] = ()

    def format_block(self) -> str:
        lines = [
            "[V5_IDENTITY_DIAG]",
            f"record={self.record}",
            f"item_id={self.item_id or 'UNKNOWN'}",
            f"title={sanitize_title(self.title)}",
            f"card_name={self.card_name or 'UNKNOWN'}",
            f"set_name={self.set_name or 'UNKNOWN'}",
            f"card_number={self.card_number or 'UNKNOWN'}",
            f"language={self.language or 'UNKNOWN'}",
            f"final={self.final_status}",
            f"ambiguity_fields={list(self.ambiguity_fields)}",
            f"name_coordinate={self.coordinates.name}",
            f"set_coordinate={self.coordinates.set_name}",
            f"number_coordinate={self.coordinates.number}",
            f"denominator_coordinate={self.coordinates.denominator}",
            f"tcgdex={self.tcgdex_detail}",
            f"poketrace={self.poketrace_detail}",
            f"visual={self.visual_detail}",
            f"reason={self.reason_code}",
            f"explanation={self.explanation}",
        ]
        if self.near_matches:
            lines.append("--- POKETRACE NEAR MATCHES ---")
            for nm in self.near_matches[:3]:
                lines.append(
                    f"diff_kind={nm.diff_kind} candidate_id={nm.candidate_id} "
                    f"target=[{nm.target_name} | {nm.target_set} | {nm.target_number}] "
                    f"candidate=[{nm.candidate_name} | {nm.candidate_set} | {nm.candidate_number}] "
                    f"diffs={list(nm.differences)}"
                )
        if self.variant_diag:
            lines.append(self.variant_diag.format_block())
        return "\n".join(lines)


def analyze_coordinates(identity: CardIdentity) -> CoordinateState:
    name_state = "known" if identity.card_name else "missing"
    set_state = "known" if identity.set else "missing"
    num_val = str(identity.card_number or "").strip()
    if num_val:
        number_state = "known"
        denominator_state = "known" if "/" in num_val else "missing"
    else:
        number_state = "missing"
        denominator_state = "missing"

    if identity.ambiguities:
        for amb in identity.ambiguities:
            if "name" in amb:
                name_state = "conflicting"
            if "set" in amb:
                set_state = "conflicting"
            if "number" in amb or "denominator" in amb:
                number_state = "conflicting"
                denominator_state = "conflicting"

    return CoordinateState(
        name=name_state,
        set_name=set_state,
        number=number_state,
        denominator=denominator_state,
    )


def determine_reason_code(
    final_status: str,
    identity: CardIdentity,
    coordinates: CoordinateState,
    tcgdex_status: str = "",
    poketrace_status: str = "",
    visual_status: str = "",
    microvariant_res: Optional[MicrovariantResolution] = None,
) -> tuple[str, str]:
    """Derive stable machine-readable reason code and explanation."""
    if final_status == "BLOCKED_VARIANT" and microvariant_res is not None:
        dim = microvariant_res.blocker_dimension or "unknown"
        if dim == "edition":
            return VARIANT_FIRST_EDITION_UNKNOWN, "Edition discriminator is material but unproven on listing"
        elif dim == "finish":
            return VARIANT_FINISH_UNKNOWN, "Finish (holo/reverse) is material but unproven on listing"
        return VARIANT_UNKNOWN_FIELD_ONLY, f"Microvariant dimension {dim} is required but unproven"

    if coordinates.denominator == "conflicting":
        return DENOMINATOR_CONFLICT, "Collector number total denominator conflicts with catalog"

    if coordinates.name == "missing":
        return MISSING_NAME, "Card name is missing from structured listing evidence"
    if coordinates.set_name == "missing" and coordinates.number == "missing":
        return MISSING_SET, "Both set name and collector number are missing from listing evidence"
    if coordinates.set_name == "missing":
        if "AMBIGUOUS" in tcgdex_status or "MULTIPLE" in tcgdex_status:
            return MULTIPLE_CANONICAL_CANDIDATES, "Multiple sets contain matching card name and number"
        return SET_UNPROVEN, "Set name could not be proven by catalog uniqueness or visual matching"
    if coordinates.number == "missing":
        if "AMBIGUOUS" in tcgdex_status or "MULTIPLE" in tcgdex_status:
            return MULTIPLE_CANONICAL_CANDIDATES, "Multiple card numbers exist for this card in the set"
        return NUMBER_UNPROVEN, "Collector number could not be proven by catalog uniqueness or visual matching"

    unresolved_fields = ambiguity_fields(identity)
    if unresolved_fields:
        return (
            LISTING_FIELD_CONFLICT,
            "Unresolved listing/catalog conflict remains in: "
            + ", ".join(unresolved_fields),
        )

    if "SET_MISMATCH" in poketrace_status:
        return POKETRACE_SET_MISMATCH, "PokeTrace search candidates differed on set coordinate"
    if "NUMBER_MISMATCH" in poketrace_status:
        return POKETRACE_NUMBER_MISMATCH, "PokeTrace search candidates differed on number coordinate"
    if "NAME_MISMATCH" in poketrace_status:
        return POKETRACE_NAME_MISMATCH, "PokeTrace search candidates differed on card name"

    if "NO_CANDIDATE" in visual_status:
        return VISUAL_NO_CANDIDATE, "Visual matcher found no compatible reference image candidates"
    if "MARGIN" in visual_status or "CLOSE_SECOND" in visual_status:
        return VISUAL_MARGIN_TOO_SMALL, "Visual similarity margin between top candidates was below safety threshold"

    if final_status == "IDENTITY_AMBIGUOUS":
        return MULTIPLE_CANONICAL_CANDIDATES, "Identity is ambiguous across multiple potential cards"
    return NUMBER_UNPROVEN, "Card coordinates remain insufficient for deterministic macro resolution"


def analyze_variant_blocking(
    record: int,
    item_id: Optional[str],
    identity: CardIdentity,
    microvariant_applicability: MicrovariantApplicability,
    microvariant_resolution: MicrovariantResolution,
    card_catalog_card: Optional[Mapping[str, Any]] = None,
    poketrace_candidate: Optional[Mapping[str, Any]] = None,
) -> VariantDiagnostic:
    """Analyze why a record was blocked at the microvariant gate and whether it was a real collision.

    CRITICAL RULES:
    1. NEVER count orthogonal flags (e.g. firstEdition: True, holo: True) as 2 distinct competing variants.
       Mutually exclusive variants must be evaluated ONLY along the specific blocking dimension.
    2. Provider metadata (e.g. PokeTrace candidate finish/edition) is logged as provider_evidence ONLY.
       It must NEVER establish catalog uniqueness, listing proof, collision absence, or block bypass.
    """
    macro_id = (
        f"{identity.card_name or 'UNKNOWN'} | {identity.set or 'UNKNOWN'} | "
        f"{identity.card_number or 'UNKNOWN'} | {identity.language or 'UNKNOWN'}"
    )
    dim = microvariant_resolution.blocker_dimension or "finish"
    listing, _conflict = semantics_from_identity(identity)
    provider = semantics_from_poketrace_candidate(poketrace_candidate) if poketrace_candidate else None

    target_evidence = f"edition={listing.edition or 'None'}, finish={listing.finish or 'None'}, promo={listing.promo}"
    catalog_evidence = f"status={microvariant_applicability.status}, source={microvariant_applicability.source}"
    provider_evidence = (
        f"edition={provider.edition or 'None'}, finish={provider.finish or 'None'}, special_finish={provider.special_finish or 'None'}"
        if provider
        else "None"
    )

    variants_payload: Mapping[str, Any] = {}
    if isinstance(card_catalog_card, Mapping):
        raw_variants = card_catalog_card.get("variants")
        if isinstance(raw_variants, Mapping):
            variants_payload = raw_variants

    if dim == "edition":
        # Mutually exclusive options: firstEdition vs unlimited
        if microvariant_applicability.status == MICROVARIANT_NOT_APPLICABLE or (
            variants_payload and variants_payload.get("firstEdition") is False
        ):
            possible_values = ("unlimited",)
            distinct_count = 1
            collision_proven = False
            unnecessary = True
            basis = "SINGLE_COMPATIBLE"
            current_reason = VARIANT_SINGLE_COMPATIBLE
        elif microvariant_applicability.status == MICROVARIANT_APPLICABLE or (
            variants_payload and variants_payload.get("firstEdition") is True
        ):
            possible_values = ("firstEdition", "unlimited")
            distinct_count = 2
            collision_proven = True
            unnecessary = False
            basis = "REAL_COLLISION"
            current_reason = COMMERCIAL_COLLISION_PROVEN
        else:
            possible_values = ("edition_unproven",)
            distinct_count = 1
            collision_proven = False
            unnecessary = False
            basis = "UNKNOWN_FIELD_ONLY"
            current_reason = VARIANT_FIRST_EDITION_UNKNOWN

    elif dim == "finish":
        # Mutually exclusive options: normal, holo, reverse, etc.
        finish_flags = [
            f for f in ("normal", "holo", "reverse")
            if variants_payload.get(f) is True
        ]
        if not finish_flags:
            if microvariant_applicability.finish_proven_single and microvariant_applicability.single_finish:
                finish_flags = [microvariant_applicability.single_finish]
            elif microvariant_applicability.finish_multiple_variants:
                finish_flags = ["holo", "reverse"]

        if len(finish_flags) >= 2:
            possible_values = tuple(finish_flags)
            distinct_count = len(finish_flags)
            collision_proven = True
            unnecessary = False
            basis = "REAL_COLLISION"
            current_reason = VARIANT_MULTIPLE_COMPATIBLE
        elif len(finish_flags) == 1:
            possible_values = tuple(finish_flags)
            distinct_count = 1
            collision_proven = False
            unnecessary = True
            basis = "SINGLE_COMPATIBLE"
            current_reason = VARIANT_SINGLE_COMPATIBLE
        else:
            # Catalog does not prove finish variants
            possible_values = ("finish_unproven",)
            distinct_count = 1
            collision_proven = False
            unnecessary = False
            basis = "UNKNOWN_FIELD_ONLY"
            current_reason = VARIANT_FINISH_UNKNOWN

    elif dim == "promo":
        possible_values = ("promo",)
        distinct_count = 1
        collision_proven = False
        unnecessary = False
        basis = "UNKNOWN_FIELD_ONLY"
        current_reason = VARIANT_UNKNOWN_FIELD_ONLY

    else:
        possible_values = (dim or "unknown",)
        distinct_count = 1
        collision_proven = False
        unnecessary = False
        basis = "UNKNOWN_FIELD_ONLY"
        current_reason = VARIANT_UNKNOWN_FIELD_ONLY

    return VariantDiagnostic(
        record=record,
        item_id=item_id,
        macro_identity=macro_id,
        blocking_dimension=dim,
        possible_variant_values=possible_values,
        commercially_distinct_candidates=distinct_count,
        collision_proven=collision_proven,
        target_evidence=target_evidence,
        catalog_evidence=catalog_evidence,
        provider_evidence=provider_evidence,
        current_block_reason=current_reason,
        variant_block_maybe_unnecessary=unnecessary,
        variant_block_basis=basis,
    )


def extract_near_matches(
    target_identity: CardIdentity,
    poketrace_candidates: Sequence[Mapping[str, Any]],
) -> Tuple[NearMatchDiff, ...]:
    """Breakdown PokeTrace near matches by differing coordinate."""
    diffs: list[NearMatchDiff] = []
    t_name = str(target_identity.card_name or "").strip().casefold()
    t_set = str(target_identity.set or "").strip().casefold()
    t_num = str(target_identity.card_number or "").strip().casefold()

    for cand in poketrace_candidates:
        c_id = str(cand.get("id") or cand.get("product_id") or "UNKNOWN")
        c_name = str(cand.get("name") or "").strip().casefold()
        set_obj = cand.get("set")
        c_set = (
            str(set_obj.get("name") if isinstance(set_obj, Mapping) else set_obj or "")
            .strip()
            .casefold()
        )
        c_num = str(cand.get("number") or cand.get("card_number") or "").strip().casefold()

        differing: list[str] = []
        if t_name and c_name and t_name != c_name:
            differing.append("name")
        if t_set and c_set and t_set != c_set:
            differing.append("set")
        if t_num and c_num and t_num != c_num:
            differing.append("number")

        if len(differing) == 1:
            diff_kind = f"{differing[0].upper()}_ONLY"
        elif differing:
            diff_kind = "MULTIPLE"
        else:
            diff_kind = "EXACT_CORE"

        diffs.append(
            NearMatchDiff(
                candidate_id=c_id,
                target_name=target_identity.card_name or "",
                target_set=target_identity.set or "",
                target_number=target_identity.card_number or "",
                candidate_name=cand.get("name") or "",
                candidate_set=c_set,
                candidate_number=c_num,
                diff_kind=diff_kind,
                differences=tuple(differing),
            )
        )
    return tuple(diffs)
