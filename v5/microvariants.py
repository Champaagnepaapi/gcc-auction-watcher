"""Conservative, local-only validation of value-critical card printings.

The normal visual matcher may prove the card artwork (macro identity).  It is
not evidence for a tiny edition stamp, a finish, or another commercial
microvariant.  This module keeps those two questions separate and deliberately
returns UNKNOWN when the dedicated region/reference evidence is incomplete.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .models import CardIdentity
from .variant_semantics import (
    EDITION_FIRST,
    EDITION_SHADOWLESS,
    EDITION_UNLIMITED,
    semantics_from_identity,
    semantics_from_poketrace_candidate,
)


MICROVARIANT_APPLICABLE = "MICROVARIANT_APPLICABLE"
MICROVARIANT_NOT_APPLICABLE = "MICROVARIANT_NOT_APPLICABLE"
MICROVARIANT_APPLICABILITY_UNKNOWN = "MICROVARIANT_APPLICABILITY_UNKNOWN"

FIRST_EDITION_CONFIRMED = "FIRST_EDITION_CONFIRMED"
UNLIMITED_CONFIRMED = "UNLIMITED_CONFIRMED"
EDITION_UNKNOWN = "EDITION_UNKNOWN"
EDITION_CONFLICT = "EDITION_CONFLICT"
OTHER_VARIANT_CONFIRMED = "OTHER_VARIANT_CONFIRMED"
MICROVARIANT_NOT_REQUIRED = "MICROVARIANT_NOT_REQUIRED"


@dataclass(frozen=True)
class MicrovariantApplicability:
    """Whether one exact card family is known to have edition alternatives."""

    status: str = MICROVARIANT_APPLICABILITY_UNKNOWN
    source: str = "UNAVAILABLE"


@dataclass(frozen=True)
class EditionRegionEvidence:
    """Evidence produced by a future local, layout-aware image implementation.

    ``stamp_region_visible`` means that the expected edition-marker region was
    found with sufficient quality and coverage.  Marker absence alone never
    proves Unlimited: ``unlimited_reference_match`` must independently match a
    deterministic Unlimited reference for the exact layout.
    """

    stamp_region_visible: bool = False
    first_edition_marker: bool = False
    unlimited_reference_match: bool = False
    conflicting_markers: bool = False
    dimension: Optional[str] = None
    confirmed_value: Optional[str] = None
    matches_winning_candidate: bool = True
    reference_pair_available: bool = False
    card_normalized: bool = False
    alignment_succeeded: bool = False
    discriminative_region_usable: bool = False
    other_variant_confirmed: bool = False
    method: str = "NO_DEDICATED_EVIDENCE"


@dataclass(frozen=True)
class MicrovariantResolution:
    applicability: str = MICROVARIANT_APPLICABILITY_UNKNOWN
    edition_status: str = EDITION_UNKNOWN
    blocks_economics: bool = False
    visual_attempted: bool = False
    visual_confirmed: bool = False
    premium_candidate_not_inherited: bool = False
    blocker_dimension: Optional[str] = None
    reference_pair_available: bool = False
    card_normalized: bool = False
    alignment_succeeded: bool = False
    discriminative_region_usable: bool = False
    other_variant_confirmed: bool = False
    confirmed_value: Optional[str] = None


def tcgdex_microvariant_applicability(
    card: Mapping[str, object],
) -> MicrovariantApplicability:
    """Read exact-family edition availability without inferring a listing edition."""

    variants = card.get("variants")
    if not isinstance(variants, Mapping):
        return MicrovariantApplicability()
    first_edition = variants.get("firstEdition")
    if first_edition is True:
        return MicrovariantApplicability(MICROVARIANT_APPLICABLE, "TCGDEX_EXACT")
    if first_edition is False:
        return MicrovariantApplicability(
            MICROVARIANT_NOT_APPLICABLE, "TCGDEX_EXACT"
        )
    return MicrovariantApplicability()


def _candidate_adds_material_microvariant(
    identity: CardIdentity,
    candidate: Optional[Mapping[str, object]],
) -> bool:
    if candidate is None:
        return False
    listing, listing_conflict = semantics_from_identity(identity)
    provider = semantics_from_poketrace_candidate(candidate)
    if listing_conflict:
        return True
    return bool(
        (provider.edition and provider.edition != listing.edition)
        or (provider.finish and provider.finish != listing.finish)
        or (provider.special_finish and provider.special_finish != listing.special_finish)
        or (provider.promo is True and listing.promo is not True)
    )


def _material_difference_dimension(
    identity: CardIdentity,
    candidate: Optional[Mapping[str, object]],
) -> Optional[str]:
    if candidate is None:
        return None
    listing, conflict = semantics_from_identity(identity)
    provider = semantics_from_poketrace_candidate(candidate)
    dimensions = []
    if conflict or (provider.edition and provider.edition != listing.edition):
        dimensions.append("edition")
    if provider.finish and provider.finish != listing.finish:
        dimensions.append("finish")
    if provider.promo is True and listing.promo is not True:
        dimensions.append("promo")
    if provider.special_finish and provider.special_finish != listing.special_finish:
        dimensions.append("special_finish")
    if not dimensions:
        return None
    return dimensions[0] if len(dimensions) == 1 else "multiple"


class LocalMicrovariantValidator:
    """Resolve edition evidence after, and never as part of, macro matching."""

    def resolve(
        self,
        identity: CardIdentity,
        applicability: MicrovariantApplicability = MicrovariantApplicability(),
        *,
        candidate: Optional[Mapping[str, object]] = None,
        evidence: Optional[EditionRegionEvidence] = None,
        visual_attempted: bool = False,
    ) -> MicrovariantResolution:
        listing, listing_conflict = semantics_from_identity(identity)
        provider = (
            semantics_from_poketrace_candidate(candidate)
            if candidate is not None
            else None
        )
        premium_not_inherited = _candidate_adds_material_microvariant(
            identity, candidate
        )
        blocker_dimension = (
            evidence.dimension
            if evidence is not None and evidence.dimension
            else _material_difference_dimension(identity, candidate)
        )

        evidence_fields = dict(
            blocker_dimension=blocker_dimension,
            reference_pair_available=bool(
                evidence is not None and evidence.reference_pair_available
            ),
            card_normalized=bool(evidence is not None and evidence.card_normalized),
            alignment_succeeded=bool(
                evidence is not None and evidence.alignment_succeeded
            ),
            discriminative_region_usable=bool(
                evidence is not None and evidence.discriminative_region_usable
            ),
            other_variant_confirmed=bool(
                evidence is not None and evidence.other_variant_confirmed
            ),
            confirmed_value=(evidence.confirmed_value if evidence is not None else None),
        )

        provider_conflict = bool(
            provider is not None
            and (
                (listing.edition and provider.edition and listing.edition != provider.edition)
                or (listing.finish and provider.finish and listing.finish != provider.finish)
                or (
                    listing.special_finish
                    and provider.special_finish
                    and listing.special_finish != provider.special_finish
                )
                or (
                    listing.promo is not None
                    and provider.promo is not None
                    and listing.promo != provider.promo
                )
            )
        )
        if (
            listing_conflict
            or provider_conflict
            or (evidence is not None and evidence.conflicting_markers)
        ):
            return MicrovariantResolution(
                applicability.status,
                EDITION_CONFLICT,
                blocks_economics=True,
                visual_attempted=visual_attempted,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        if applicability.status == MICROVARIANT_NOT_APPLICABLE:
            if premium_not_inherited or listing.edition in {
                EDITION_FIRST,
                EDITION_UNLIMITED,
                EDITION_SHADOWLESS,
            }:
                return MicrovariantResolution(
                    applicability.status,
                    EDITION_CONFLICT,
                    blocks_economics=True,
                    visual_attempted=visual_attempted,
                    premium_candidate_not_inherited=premium_not_inherited,
                    **evidence_fields,
                )
            return MicrovariantResolution(
                applicability.status,
                MICROVARIANT_NOT_REQUIRED,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        if evidence is not None and (
            evidence.other_variant_confirmed or evidence.confirmed_value
        ) and not evidence.matches_winning_candidate:
            return MicrovariantResolution(
                applicability.status,
                EDITION_CONFLICT,
                blocks_economics=True,
                visual_attempted=visual_attempted,
                visual_confirmed=True,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        # A deterministic listing aspect is direct commercial evidence.  It is
        # retained from the listing; it never comes from the provider candidate.
        if listing.edition == EDITION_FIRST:
            return MicrovariantResolution(
                applicability.status,
                FIRST_EDITION_CONFIRMED,
                visual_attempted=visual_attempted,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )
        if listing.edition == EDITION_UNLIMITED:
            return MicrovariantResolution(
                applicability.status,
                UNLIMITED_CONFIRMED,
                visual_attempted=visual_attempted,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )
        if listing.edition == EDITION_SHADOWLESS:
            # Shadowless remains a separately proven premium semantic.  It must
            # not be collapsed into either First Edition or Unlimited counters.
            return MicrovariantResolution(
                applicability.status,
                MICROVARIANT_NOT_REQUIRED,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        if evidence is not None and evidence.first_edition_marker:
            if not evidence.stamp_region_visible:
                return MicrovariantResolution(
                    applicability.status,
                    EDITION_UNKNOWN,
                    blocks_economics=True,
                    visual_attempted=visual_attempted,
                    premium_candidate_not_inherited=premium_not_inherited,
                    **evidence_fields,
                )
            return MicrovariantResolution(
                applicability.status,
                FIRST_EDITION_CONFIRMED,
                visual_attempted=visual_attempted,
                visual_confirmed=True,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        if evidence is not None and evidence.unlimited_reference_match:
            if evidence.stamp_region_visible:
                return MicrovariantResolution(
                    applicability.status,
                    UNLIMITED_CONFIRMED,
                    visual_attempted=visual_attempted,
                    visual_confirmed=True,
                    premium_candidate_not_inherited=premium_not_inherited,
                    **evidence_fields,
                )

        if evidence is not None and evidence.other_variant_confirmed:
            return MicrovariantResolution(
                applicability.status,
                OTHER_VARIANT_CONFIRMED,
                visual_attempted=visual_attempted,
                visual_confirmed=True,
                premium_candidate_not_inherited=premium_not_inherited,
                **evidence_fields,
            )

        material_unknown = bool(
            applicability.status == MICROVARIANT_APPLICABLE
            or premium_not_inherited
        )
        return MicrovariantResolution(
            applicability.status,
            EDITION_UNKNOWN,
            blocks_economics=material_unknown,
            visual_attempted=visual_attempted,
            premium_candidate_not_inherited=premium_not_inherited,
            **evidence_fields,
        )
