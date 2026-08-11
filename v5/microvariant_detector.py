"""Deterministic, local-only comparison of exact microvariant references.

The detector is deliberately narrower than the macro artwork matcher.  It is
only useful after macro identity has been proved and after the caller has
assembled exact references for the same card, set, number and language.  It
never treats provider metadata as listing evidence: metadata selects the
reference pair, while seller pixels decide (or leave the result UNKNOWN).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence, Tuple

from PIL import Image, ImageChops, ImageOps, ImageStat

from .microvariants import EditionRegionEvidence, MicrovariantApplicability
from .models import CardIdentity
from .variant_semantics import (
    EDITION_FIRST,
    EDITION_UNLIMITED,
    FINISH_HOLO,
    FINISH_REVERSE,
    semantics_from_poketrace_candidate,
)


NORMALIZED_SIZE = (256, 356)
MIN_SOURCE_EDGE = 96
MIN_GLOBAL_SIMILARITY = 0.80
MIN_REFERENCE_LAYOUT_SIMILARITY = 0.78
MIN_REGION_SIMILARITY = 0.86
MIN_REGION_MARGIN = 0.055
MIN_REFERENCE_SEPARATION = 0.105
MAX_GLARE_FRACTION = 0.18


@dataclass(frozen=True)
class CanonicalMicrovariantReference:
    metadata: Mapping[str, object]
    image_bytes: bytes


@dataclass(frozen=True)
class MicrovariantEvidenceRequest:
    identity: CardIdentity
    winning_candidate: Mapping[str, object]
    ebay_image_bytes: Sequence[bytes]
    winning_reference: Optional[CanonicalMicrovariantReference]
    competing_references: Sequence[CanonicalMicrovariantReference]
    applicability: MicrovariantApplicability


@dataclass(frozen=True)
class _NormalizedCard:
    image: Image.Image
    localized: bool


class DeterministicLocalMicrovariantEvidenceProvider:
    """Compare seller pixels only where exact references demonstrably differ."""

    def __call__(
        self, request: MicrovariantEvidenceRequest
    ) -> Optional[EditionRegionEvidence]:
        return self.evaluate(request)

    def evaluate(
        self, request: MicrovariantEvidenceRequest
    ) -> Optional[EditionRegionEvidence]:
        dimension = _blocking_dimension(
            request.identity,
            request.winning_candidate,
            request.competing_references,
        )
        if dimension is None:
            return EditionRegionEvidence(method="NO_MATERIAL_REFERENCE_DIFFERENCE")

        # A static scan cannot deterministically prove reflective finish under
        # arbitrary listing lighting.  Keep the dimension observable but gated.
        if dimension == "finish":
            return EditionRegionEvidence(
                dimension=dimension,
                reference_pair_available=bool(request.competing_references),
                method="STATIC_FINISH_REFERENCE_INCONCLUSIVE",
            )

        winning = request.winning_reference
        if winning is None or not request.competing_references:
            return EditionRegionEvidence(
                dimension=dimension,
                reference_pair_available=False,
                method="EXACT_REFERENCE_PAIR_MISSING",
            )

        winning_cards = _normalized_orientations(winning.image_bytes)
        if not winning_cards:
            return EditionRegionEvidence(
                dimension=dimension,
                reference_pair_available=True,
                method="WINNING_REFERENCE_NORMALIZATION_FAILED",
            )

        seller_cards = []
        for raw in request.ebay_image_bytes:
            seller_cards.extend(_normalized_orientations(raw))
        if not seller_cards:
            return EditionRegionEvidence(
                dimension=dimension,
                reference_pair_available=True,
                method="SELLER_CARD_NORMALIZATION_FAILED",
            )

        best_evidence: Optional[EditionRegionEvidence] = None
        for competing in request.competing_references:
            competing_cards = _normalized_orientations(competing.image_bytes)
            if not competing_cards:
                continue
            evidence = _compare_reference_pair(
                dimension,
                request.winning_candidate,
                competing.metadata,
                seller_cards,
                winning_cards,
                competing_cards,
            )
            if evidence is not None:
                if evidence.first_edition_marker or evidence.unlimited_reference_match:
                    return evidence
                if evidence.other_variant_confirmed or evidence.conflicting_markers:
                    return evidence
                best_evidence = evidence

        return best_evidence or EditionRegionEvidence(
            dimension=dimension,
            reference_pair_available=True,
            card_normalized=True,
            method="EXACT_REFERENCE_PAIR_UNUSABLE",
        )


def _blocking_dimension(
    identity: CardIdentity,
    winning: Mapping[str, object],
    competing: Sequence[CanonicalMicrovariantReference],
) -> Optional[str]:
    winning_semantics = semantics_from_poketrace_candidate(winning)
    dimensions = set()
    for reference in competing:
        other = semantics_from_poketrace_candidate(reference.metadata)
        if winning_semantics.edition != other.edition and (
            winning_semantics.edition or other.edition
        ):
            dimensions.add("edition")
        if winning_semantics.finish != other.finish and (
            winning_semantics.finish or other.finish
        ):
            dimensions.add("finish")
        if winning_semantics.promo != other.promo and (
            winning_semantics.promo is not None or other.promo is not None
        ):
            dimensions.add("promo")
        if winning_semantics.special_finish != other.special_finish and (
            winning_semantics.special_finish or other.special_finish
        ):
            dimensions.add("special_finish")
    if not dimensions:
        return None
    return next(iter(dimensions)) if len(dimensions) == 1 else "multiple"


def _normalized_orientations(raw: bytes) -> Tuple[_NormalizedCard, ...]:
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            if min(image.size) < MIN_SOURCE_EDGE:
                return ()
            image.thumbnail((1200, 1200))
            crop = _localize_card(image)
            source = crop or image
            localized = crop is not None or _card_ratio_usable(image.size)
            if not localized:
                return ()
            results = []
            for angle in (0, 90, 180, 270):
                rotated = source.rotate(angle, expand=True) if angle else source
                if rotated.width > rotated.height:
                    continue
                normalized = ImageOps.fit(
                    rotated, NORMALIZED_SIZE, method=Image.Resampling.LANCZOS
                )
                if _quality_usable(normalized):
                    results.append(_NormalizedCard(normalized, localized))
            return tuple(results)
    except (OSError, TypeError, ValueError):
        return ()


def _localize_card(image: Image.Image) -> Optional[Image.Image]:
    sample = image.copy()
    sample.thumbnail((480, 480))
    width, height = sample.size
    patch = max(4, min(width, height) // 24)
    corners = (
        (0, 0, patch, patch),
        (width - patch, 0, width, patch),
        (0, height - patch, patch, height),
        (width - patch, height - patch, width, height),
    )
    means = [ImageStat.Stat(sample.crop(box)).mean[:3] for box in corners]
    background = tuple(sorted(values)[len(values) // 2] for values in zip(*means))
    pixels = sample.load()
    points = []
    threshold = 42.0 * 42.0
    for y in range(height):
        for x in range(width):
            pixel = pixels[x, y]
            if sum((pixel[i] - background[i]) ** 2 for i in range(3)) >= threshold:
                points.append((x, y))
    if len(points) < width * height * 0.18:
        return None
    left = min(point[0] for point in points)
    right = max(point[0] for point in points) + 1
    top = min(point[1] for point in points)
    bottom = max(point[1] for point in points) + 1
    if not _card_ratio_usable((right - left, bottom - top)):
        return None
    if (right - left) * (bottom - top) < width * height * 0.28:
        return None
    scale_x, scale_y = image.width / width, image.height / height
    padding_x = max(1, int((right - left) * 0.02))
    padding_y = max(1, int((bottom - top) * 0.02))
    return image.crop(
        (
            max(0, int((left - padding_x) * scale_x)),
            max(0, int((top - padding_y) * scale_y)),
            min(image.width, int((right + padding_x) * scale_x)),
            min(image.height, int((bottom + padding_y) * scale_y)),
        )
    )


def _card_ratio_usable(size: Tuple[int, int]) -> bool:
    width, height = size
    if width <= 0 or height <= 0:
        return False
    ratio = min(width, height) / max(width, height)
    return 0.58 <= ratio <= 0.82


def _quality_usable(image: Image.Image) -> bool:
    gray = ImageOps.grayscale(image)
    stats = ImageStat.Stat(gray)
    if not stats.stddev or stats.stddev[0] < 12.0:
        return False
    pixels = tuple(gray.resize((64, 89), Image.Resampling.BILINEAR).getdata())
    glare = sum(value >= 248 for value in pixels) / len(pixels)
    return glare <= MAX_GLARE_FRACTION


def _compare_reference_pair(
    dimension: str,
    winning_metadata: Mapping[str, object],
    competing_metadata: Mapping[str, object],
    seller_cards: Sequence[_NormalizedCard],
    winning_cards: Sequence[_NormalizedCard],
    competing_cards: Sequence[_NormalizedCard],
) -> Optional[EditionRegionEvidence]:
    best = None
    reference_pairs = [
        (_image_similarity(winning.image, competing.image), winning, competing)
        for winning in winning_cards
        for competing in competing_cards
    ]
    best_reference_similarity = max(
        (value[0] for value in reference_pairs), default=0.0
    )
    if best_reference_similarity < MIN_REFERENCE_LAYOUT_SIMILARITY:
        return EditionRegionEvidence(
            dimension=dimension,
            reference_pair_available=True,
            card_normalized=True,
            alignment_succeeded=False,
            discriminative_region_usable=False,
            method="REFERENCE_LAYOUT_ALIGNMENT_FAILED",
        )
    # The two exact scans must first agree on orientation/layout.  Comparing a
    # 0-degree scan with a 180-degree scan manufactures "discriminative"
    # regions across the whole artwork and is therefore never admissible.
    for reference_similarity, winning, competing in reference_pairs:
        if reference_similarity < best_reference_similarity - 0.01:
            continue
        regions = _discriminative_regions(winning.image, competing.image)
        if not regions:
            continue
        for seller in seller_cards:
            global_winning = _image_similarity(seller.image, winning.image)
            global_competing = _image_similarity(seller.image, competing.image)
            if max(global_winning, global_competing) < MIN_GLOBAL_SIMILARITY:
                continue
            winning_local = _region_similarity(seller.image, winning.image, regions)
            competing_local = _region_similarity(
                seller.image, competing.image, regions
            )
            score = max(winning_local, competing_local)
            margin = abs(winning_local - competing_local)
            value = (
                score,
                margin,
                winning_local,
                competing_local,
                reference_similarity,
            )
            if best is None or value[:2] > best[:2]:
                best = value
    if best is None:
        return EditionRegionEvidence(
            dimension=dimension,
            reference_pair_available=True,
            card_normalized=True,
            alignment_succeeded=False,
            discriminative_region_usable=False,
            method="ALIGNMENT_OR_REGION_FAILED",
        )

    score, margin, winning_local, competing_local, _reference_similarity = best
    common = dict(
        dimension=dimension,
        reference_pair_available=True,
        card_normalized=True,
        alignment_succeeded=True,
        discriminative_region_usable=True,
        stamp_region_visible=(dimension == "edition"),
        method="EXACT_REFERENCE_PAIR_DISCRIMINATIVE_REGION",
    )
    if score < MIN_REGION_SIMILARITY or margin < MIN_REGION_MARGIN:
        return EditionRegionEvidence(**common)

    matches_winner = winning_local > competing_local
    selected = winning_metadata if matches_winner else competing_metadata
    selected_semantics = semantics_from_poketrace_candidate(selected)
    if dimension == "edition":
        if selected_semantics.edition == EDITION_FIRST:
            return EditionRegionEvidence(
                first_edition_marker=True,
                confirmed_value=EDITION_FIRST,
                matches_winning_candidate=matches_winner,
                **common,
            )
        if selected_semantics.edition == EDITION_UNLIMITED:
            return EditionRegionEvidence(
                unlimited_reference_match=True,
                confirmed_value=EDITION_UNLIMITED,
                matches_winning_candidate=matches_winner,
                **common,
            )
        return EditionRegionEvidence(**common)

    confirmed = _semantic_value(selected, dimension)
    if confirmed is None:
        return EditionRegionEvidence(**common)
    return EditionRegionEvidence(
        confirmed_value=confirmed,
        matches_winning_candidate=matches_winner,
        other_variant_confirmed=True,
        **common,
    )


def _semantic_value(metadata: Mapping[str, object], dimension: str) -> Optional[str]:
    semantics = semantics_from_poketrace_candidate(metadata)
    if dimension == "promo":
        return "promo" if semantics.promo is True else "non_promo"
    if dimension == "special_finish":
        return semantics.special_finish
    if dimension == "finish":
        if semantics.finish in {FINISH_HOLO, FINISH_REVERSE}:
            return semantics.finish
        return semantics.finish
    return None


def _discriminative_regions(
    left: Image.Image, right: Image.Image
) -> Tuple[Tuple[int, int, int, int], ...]:
    gray_left = ImageOps.grayscale(left)
    gray_right = ImageOps.grayscale(right)
    tile_width, tile_height = 32, 32
    scored = []
    for top in range(0, NORMALIZED_SIZE[1], tile_height):
        for x in range(0, NORMALIZED_SIZE[0], tile_width):
            box = (
                x,
                top,
                min(x + tile_width, NORMALIZED_SIZE[0]),
                min(top + tile_height, NORMALIZED_SIZE[1]),
            )
            similarity = _image_similarity(
                gray_left.crop(box), gray_right.crop(box)
            )
            separation = 1.0 - similarity
            if separation >= MIN_REFERENCE_SEPARATION:
                scored.append((separation, box))
    scored.sort(reverse=True)
    return tuple(box for _score, box in scored[:10])


def _region_similarity(
    left: Image.Image,
    right: Image.Image,
    regions: Sequence[Tuple[int, int, int, int]],
) -> float:
    scores = [_image_similarity(left.crop(box), right.crop(box)) for box in regions]
    return sum(scores) / len(scores) if scores else 0.0


def _image_similarity(left: Image.Image, right: Image.Image) -> float:
    if left.mode != "L":
        left = ImageOps.grayscale(left)
    if right.mode != "L":
        right = ImageOps.grayscale(right)
    if left.size != right.size:
        right = right.resize(left.size, Image.Resampling.LANCZOS)
    difference = ImageChops.difference(left, right)
    mean = ImageStat.Stat(difference).mean[0]
    return max(0.0, 1.0 - mean / 255.0)
