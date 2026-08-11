from __future__ import annotations

import io
import os
from dataclasses import dataclass, replace
from typing import Callable, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlparse

from PIL import Image, ImageFilter, ImageOps, ImageStat

from .card_number_ocr import LocalCardNumberOCR
from .models import CardIdentity
from .poketrace_identity import (
    REQUEST_OK,
    PokeTraceIdentityResolver,
    _normalize,
    _normalize_card_number,
    _resolved_identity,
    _set_similarity,
    _variant_family,
)
from .poketrace_matching import _normalize_card_name


MAX_VISUAL_IMAGE_BYTES = 8 * 1024 * 1024


@dataclass
class VisualIdentityCounters:
    attempted: int = 0
    api_searches: int = 0
    api_unavailable: int = 0
    no_ebay_image: int = 0
    no_candidates: int = 0
    candidates_considered: int = 0
    candidate_images_downloaded: int = 0
    candidate_image_failures: int = 0
    ebay_images_downloaded: int = 0
    ebay_image_failures: int = 0
    low_confidence: int = 0
    close_second: int = 0
    rescued: int = 0
    card_number_overrides: int = 0
    ambiguities_cleared: int = 0
    market_snapshots_primed: int = 0
    ocr_rescued: int = 0
    ocr_market_snapshots_primed: int = 0


@dataclass(frozen=True)
class VisualIdentityResolution:
    identity: CardIdentity
    matched: bool = False
    card_id: Optional[str] = None
    score: float = 0.0
    margin: float = 0.0


@dataclass(frozen=True)
class _ImageSignature:
    average_hash: Tuple[bool, ...]
    edge_hash: Tuple[bool, ...]
    center_hash: Tuple[bool, ...]
    color_histogram: Tuple[float, ...]


@dataclass(frozen=True)
class _VisualCandidate:
    payload: Mapping[str, object]
    metadata_score: float
    image_url: str


class LocalVisualIdentityResolver:
    """Resolve ambiguous/incomplete identities from the actual eBay card image.

    This is intentionally a second-line resolver. It never scans every listing
    and never replaces a clean structured identity. It asks PokeTrace for a
    small candidate set, downloads the canonical scan URLs returned by the API,
    and compares them locally with the eBay image using perceptual/edge/color
    signatures. If that image matcher cannot separate the candidates, an
    optional local OCR pass reads only lower-card strips and may select a
    collector number that already exists in the same PokeTrace candidate pool.

    No model API, image persistence, bid or purchase is involved.
    """

    def __init__(
        self,
        poketrace_identity: PokeTraceIdentityResolver,
        *,
        ebay_image_fetcher: Callable[[str], Optional[bytes]],
        candidate_image_fetcher: Optional[Callable[[str], Optional[bytes]]] = None,
        enabled: Optional[bool] = None,
        max_candidates: Optional[int] = None,
        max_ebay_images: Optional[int] = None,
        minimum_score: Optional[float] = None,
        minimum_margin: Optional[float] = None,
        override_number_minimum_score: Optional[float] = None,
        override_number_minimum_margin: Optional[float] = None,
        card_number_ocr: Optional[LocalCardNumberOCR] = None,
    ) -> None:
        self.poketrace_identity = poketrace_identity
        self.provider = poketrace_identity.provider
        self.ebay_image_fetcher = ebay_image_fetcher
        self.candidate_image_fetcher = (
            candidate_image_fetcher or self._fetch_poketrace_image
        )
        self.enabled = (
            enabled
            if enabled is not None
            else os.getenv("V5_VISUAL_IDENTITY_ENABLED", "false").strip().casefold()
            == "true"
        )
        self.max_candidates = max(
            1,
            min(
                12,
                max_candidates
                if max_candidates is not None
                else int(os.getenv("V5_VISUAL_IDENTITY_MAX_CANDIDATES", "8")),
            ),
        )
        self.max_ebay_images = max(
            1,
            min(
                4,
                max_ebay_images
                if max_ebay_images is not None
                else int(os.getenv("V5_VISUAL_IDENTITY_MAX_EBAY_IMAGES", "3")),
            ),
        )
        self.minimum_score = (
            minimum_score
            if minimum_score is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_MIN_SCORE", "0.74"))
        )
        self.minimum_margin = (
            minimum_margin
            if minimum_margin is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_MIN_MARGIN", "0.08"))
        )
        self.override_number_minimum_score = (
            override_number_minimum_score
            if override_number_minimum_score is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_OVERRIDE_NUMBER_MIN_SCORE", "0.82"))
        )
        self.override_number_minimum_margin = (
            override_number_minimum_margin
            if override_number_minimum_margin is not None
            else float(os.getenv("V5_VISUAL_IDENTITY_OVERRIDE_NUMBER_MIN_MARGIN", "0.12"))
        )
        self.card_number_ocr = card_number_ocr or LocalCardNumberOCR()
        self.counters = VisualIdentityCounters()
        self._scan_signature_cache: dict[str, Tuple[_ImageSignature, ...]] = {}

    def resolve_identity(
        self,
        identity: CardIdentity,
        image_urls: Sequence[str],
    ) -> VisualIdentityResolution:
        if (
            not self.enabled
            or not self.provider.config.enabled
            or not self.provider.config.api_key
        ):
            return VisualIdentityResolution(identity)

        usable_image_urls = tuple(
            dict.fromkeys(str(value).strip() for value in image_urls if str(value).strip())
        )[: self.max_ebay_images]
        if not usable_image_urls:
            self.counters.no_ebay_image += 1
            return VisualIdentityResolution(identity)

        search_text = self._visual_search_text(identity)
        if not search_text:
            return VisualIdentityResolution(identity)

        self.counters.attempted += 1
        self.counters.api_searches += 1
        payload, status = self.poketrace_identity._request(identity, search_text)
        if status != REQUEST_OK or payload is None:
            self.counters.api_unavailable += 1
            return VisualIdentityResolution(identity)

        data = payload.get("data")
        raw_candidates = (
            tuple(item for item in data if isinstance(item, Mapping))
            if isinstance(data, Sequence) and not isinstance(data, (str, bytes))
            else ()
        )
        candidates = self._candidate_pool(identity, raw_candidates)
        if not candidates:
            self.counters.no_candidates += 1
            return VisualIdentityResolution(identity)

        ebay_signatures = []
        ebay_image_bytes = []
        for image_url in usable_image_urls:
            image_bytes = self.ebay_image_fetcher(image_url)
            if image_bytes is None:
                self.counters.ebay_image_failures += 1
                continue
            try:
                signatures = _image_signatures(image_bytes)
            except (OSError, TypeError, ValueError):
                self.counters.ebay_image_failures += 1
                continue
            if signatures:
                self.counters.ebay_images_downloaded += 1
                ebay_signatures.extend(signatures)
                ebay_image_bytes.append(image_bytes)

        if not ebay_signatures:
            self.counters.no_ebay_image += 1
            return VisualIdentityResolution(identity)

        scored: list[tuple[float, float, _VisualCandidate]] = []
        for candidate in candidates:
            canonical_signatures = self._canonical_signatures(candidate.image_url)
            if not canonical_signatures:
                continue
            visual_score = max(
                _signature_similarity(left, right)
                for left in ebay_signatures
                for right in canonical_signatures
            )
            scored.append((visual_score, candidate.metadata_score, candidate))

        if not scored:
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(identity, candidates, ebay_image_bytes)
            return ocr or VisualIdentityResolution(identity)

        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        best_score, _metadata_score, best = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        margin = best_score - second_score

        expected_number = _normalize_card_number(identity.card_number)
        candidate_number = _normalize_card_number(best.payload.get("cardNumber"))
        overrides_number = bool(
            expected_number and candidate_number and expected_number != candidate_number
        )
        score_floor = (
            self.override_number_minimum_score
            if overrides_number
            else self.minimum_score
        )
        margin_floor = (
            self.override_number_minimum_margin
            if overrides_number
            else self.minimum_margin
        )

        if best_score < score_floor:
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(identity, candidates, ebay_image_bytes)
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)
        if len(scored) > 1 and margin < margin_floor:
            self.counters.close_second += 1
            ocr = self._try_ocr_rescue(identity, candidates, ebay_image_bytes)
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)

        resolved = replace(
            _resolved_identity(identity, best.payload),
            ambiguities=(),
        )
        if not (resolved.card_name and resolved.set and resolved.card_number):
            self.counters.low_confidence += 1
            ocr = self._try_ocr_rescue(identity, candidates, ebay_image_bytes)
            if ocr is not None:
                return ocr
            return VisualIdentityResolution(identity, score=best_score, margin=margin)

        if overrides_number:
            self.counters.card_number_overrides += 1
        if identity.ambiguities:
            self.counters.ambiguities_cleared += 1

        self.poketrace_identity._prime_market_snapshot(identity, resolved, best.payload)
        self.counters.market_snapshots_primed += 1
        self.counters.rescued += 1
        self.provider.counters.us_matches += 1
        return VisualIdentityResolution(
            resolved,
            matched=True,
            card_id=str(best.payload.get("id") or "").strip() or None,
            score=best_score,
            margin=margin,
        )

    def _try_ocr_rescue(
        self,
        identity: CardIdentity,
        candidates: Sequence[_VisualCandidate],
        ebay_image_bytes: Sequence[bytes],
    ) -> Optional[VisualIdentityResolution]:
        result = self.card_number_ocr.resolve(
            ebay_image_bytes,
            tuple(candidate.payload for candidate in candidates),
            identity.card_number,
        )
        if not result.matched or result.candidate is None:
            return None

        retained_ambiguities = tuple(
            value
            for value in identity.ambiguities
            if not (
                value.startswith("card_number:")
                or value.startswith("card_name: resolution set+number ambigue")
                or value == "catalog_identity_ambiguous"
            )
        )
        resolved = replace(
            _resolved_identity(identity, result.candidate),
            ambiguities=retained_ambiguities,
        )
        if (
            not (resolved.card_name and resolved.set and resolved.card_number)
            or resolved.ambiguities
        ):
            return None

        self.poketrace_identity._prime_market_snapshot(
            identity, resolved, result.candidate
        )
        self.counters.ocr_rescued += 1
        self.counters.ocr_market_snapshots_primed += 1
        self.provider.counters.us_matches += 1
        return VisualIdentityResolution(
            resolved,
            matched=True,
            card_id=str(result.candidate.get("id") or "").strip() or None,
        )

    @staticmethod
    def _visual_search_text(identity: CardIdentity) -> str:
        # The card number is intentionally not used as the primary visual search
        # discriminator: live runs show that this is the field most often
        # conflicting with otherwise plausible PokeTrace candidates.
        parts = [
            str(value).strip()
            for value in (identity.card_name, identity.set)
            if value and str(value).strip()
        ]
        if not parts and identity.card_number:
            parts.append(str(identity.card_number).strip())
        return " ".join(parts)

    def _candidate_pool(
        self,
        identity: CardIdentity,
        candidates: Sequence[Mapping[str, object]],
    ) -> Tuple[_VisualCandidate, ...]:
        unique: dict[tuple[str, str, str, str], _VisualCandidate] = {}
        expected_name = _normalize_card_name(identity.card_name)
        expected_number = _normalize_card_number(identity.card_number)
        expected_variant = _variant_family(identity.variant)

        for candidate in candidates:
            product_type = _normalize(candidate.get("productType"))
            if product_type and product_type != "single":
                continue
            image_url = str(candidate.get("image") or "").strip()
            if not image_url:
                continue
            candidate_name = _normalize_card_name(candidate.get("name"))
            if expected_name and candidate_name != expected_name:
                continue
            set_payload = candidate.get("set")
            set_name = (
                set_payload.get("name") if isinstance(set_payload, Mapping) else None
            )
            set_slug = (
                set_payload.get("slug") if isinstance(set_payload, Mapping) else None
            )
            set_similarity = _set_similarity(identity.set, set_name, set_slug)
            if identity.set and set_similarity < 0.66:
                continue
            candidate_variant = _variant_family(candidate.get("variant"))
            if (
                expected_variant
                and candidate_variant
                and expected_variant != candidate_variant
            ):
                continue

            candidate_number = _normalize_card_number(candidate.get("cardNumber"))
            metadata_score = 0.0
            metadata_score += 4.0 if expected_name and candidate_name == expected_name else 0.0
            metadata_score += 3.0 * set_similarity if identity.set else 0.0
            metadata_score += (
                3.0
                if expected_number and candidate_number == expected_number
                else 0.0
            )
            metadata_score += (
                1.0
                if expected_variant and candidate_variant == expected_variant
                else 0.0
            )
            key = (
                str(candidate.get("id") or "").strip(),
                candidate_name,
                candidate_number,
                _normalize(set_name),
            )
            previous = unique.get(key)
            value = _VisualCandidate(candidate, metadata_score, image_url)
            if previous is None or value.metadata_score > previous.metadata_score:
                unique[key] = value

        ordered = sorted(
            unique.values(), key=lambda value: value.metadata_score, reverse=True
        )[: self.max_candidates]
        self.counters.candidates_considered += len(ordered)
        return tuple(ordered)

    def _canonical_signatures(self, image_url: str) -> Tuple[_ImageSignature, ...]:
        cached = self._scan_signature_cache.get(image_url)
        if cached is not None:
            return cached
        image_bytes = self.candidate_image_fetcher(image_url)
        if image_bytes is None:
            self.counters.candidate_image_failures += 1
            self._scan_signature_cache[image_url] = ()
            return ()
        try:
            signatures = _image_signatures(image_bytes)
        except (OSError, TypeError, ValueError):
            self.counters.candidate_image_failures += 1
            signatures = ()
        if signatures:
            self.counters.candidate_images_downloaded += 1
        self._scan_signature_cache[image_url] = signatures
        return signatures

    def _fetch_poketrace_image(self, image_url: str) -> Optional[bytes]:
        parsed = urlparse(image_url)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme != "https" or not (
            hostname == "poketrace.com" or hostname.endswith(".poketrace.com")
        ):
            return None
        try:
            response = self.provider.session.get(
                image_url,
                headers={"Accept": "image/*"},
                timeout=self.provider.config.timeout_seconds,
                stream=True,
            )
        except Exception:
            return None
        try:
            if getattr(response, "status_code", None) != 200:
                return None
            raw_length = getattr(response, "headers", {}).get("Content-Length")
            if raw_length and int(raw_length) > MAX_VISUAL_IMAGE_BYTES:
                return None
            content = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                content.extend(chunk)
                if len(content) > MAX_VISUAL_IMAGE_BYTES:
                    return None
            return bytes(content) if content else None
        except (AttributeError, TypeError, ValueError):
            return None
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()


def render_visual_identity_counters(resolver: LocalVisualIdentityResolver) -> str:
    counters = resolver.counters
    ocr = resolver.card_number_ocr.counters
    return "\n".join(
        (
            "=== V5 LOCAL VISUAL IDENTITY RESCUE ===",
            f"enabled: {str(resolver.enabled).lower()}",
            "scope: ambiguous/insufficient RAW listings only",
            "method: local perceptual + edge + color scan matching",
            "model API calls: 0",
            f"attempted: {counters.attempted}",
            f"PokeTrace candidate searches: {counters.api_searches}",
            f"candidate searches unavailable: {counters.api_unavailable}",
            f"no visual candidates after metadata filter: {counters.no_candidates}",
            f"no usable eBay image after fetch: {counters.no_ebay_image}",
            f"candidate scans considered: {counters.candidates_considered}",
            f"candidate scans downloaded: {counters.candidate_images_downloaded}",
            f"candidate image failures: {counters.candidate_image_failures}",
            f"eBay images downloaded: {counters.ebay_images_downloaded}",
            f"eBay image failures: {counters.ebay_image_failures}",
            f"low-confidence rejects: {counters.low_confidence}",
            f"close-second/ambiguous rejects: {counters.close_second}",
            f"visual identities rescued: {counters.rescued}",
            f"visual structured card-number overrides: {counters.card_number_overrides}",
            f"ambiguities cleared by visual evidence: {counters.ambiguities_cleared}",
            f"market snapshots primed from visual match: {counters.market_snapshots_primed}",
            "--- targeted local card-number OCR fallback ---",
            f"OCR enabled: {str(resolver.card_number_ocr.config.enabled).lower()}",
            f"OCR attempted: {ocr.attempted}",
            f"OCR calls: {ocr.ocr_calls}",
            f"OCR failures: {ocr.ocr_failures}",
            f"OCR candidate-matching tokens seen: {ocr.candidate_tokens_seen}",
            f"OCR consensus found: {ocr.consensus_found}",
            f"OCR rejected no consensus: {ocr.rejected_no_consensus}",
            f"OCR rejected duplicate candidate number: {ocr.rejected_candidate_ambiguous}",
            f"OCR identities rescued: {counters.ocr_rescued}",
            f"OCR structured card-number overrides: {ocr.structured_number_overrides}",
            f"market snapshots primed from OCR match: {counters.ocr_market_snapshots_primed}",
            "persisted images/OCR text: 0",
            "persisted eBay identifiers: 0",
        )
    )


def _image_signatures(image_bytes: bytes) -> Tuple[_ImageSignature, ...]:
    with Image.open(io.BytesIO(image_bytes)) as opened:
        base = ImageOps.exif_transpose(opened).convert("RGB")
        if min(base.size) < 32:
            raise ValueError("image too small")
        base.thumbnail((900, 900))
        candidates = [base]
        cropped = _subject_crop(base)
        if cropped is not None:
            candidates.append(cropped)

        signatures = []
        for candidate in candidates:
            for angle in (0, 90, 180, 270):
                rotated = candidate.rotate(angle, expand=True) if angle else candidate
                normalized = ImageOps.fit(rotated, (256, 356), method=Image.Resampling.LANCZOS)
                signatures.append(_signature(normalized))
        return tuple(signatures)


def _subject_crop(image: Image.Image) -> Optional[Image.Image]:
    sample = image.copy()
    sample.thumbnail((420, 420))
    width, height = sample.size
    if width < 40 or height < 40:
        return None

    patch = max(3, min(width, height) // 20)
    corner_boxes = (
        (0, 0, patch, patch),
        (width - patch, 0, width, patch),
        (0, height - patch, patch, height),
        (width - patch, height - patch, width, height),
    )
    corner_means = [ImageStat.Stat(sample.crop(box)).mean[:3] for box in corner_boxes]
    background = tuple(
        sorted(values)[len(values) // 2]
        for values in zip(*corner_means)
    )

    pixels = sample.load()
    xs = []
    ys = []
    threshold_sq = 38.0 * 38.0
    for y in range(height):
        for x in range(width):
            red, green, blue = pixels[x, y]
            distance_sq = (
                (red - background[0]) ** 2
                + (green - background[1]) ** 2
                + (blue - background[2]) ** 2
            )
            if distance_sq >= threshold_sq:
                xs.append(x)
                ys.append(y)
    if len(xs) < width * height * 0.18:
        return None

    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    box_width = right - left + 1
    box_height = bottom - top + 1
    if box_width * box_height < width * height * 0.24:
        return None
    padding_x = max(2, int(box_width * 0.025))
    padding_y = max(2, int(box_height * 0.025))
    left = max(0, left - padding_x)
    right = min(width, right + padding_x + 1)
    top = max(0, top - padding_y)
    bottom = min(height, bottom + padding_y + 1)

    scale_x = image.width / width
    scale_y = image.height / height
    original_box = (
        int(left * scale_x),
        int(top * scale_y),
        int(right * scale_x),
        int(bottom * scale_y),
    )
    cropped = image.crop(original_box)
    ratio = min(cropped.size) / max(cropped.size)
    if ratio < 0.45:
        return None
    return cropped


def _signature(image: Image.Image) -> _ImageSignature:
    gray = ImageOps.grayscale(image)
    center = gray.crop((20, 52, 236, 300))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    return _ImageSignature(
        average_hash=_average_hash(gray, 16),
        edge_hash=_difference_hash(edges, 16),
        center_hash=_average_hash(center, 16),
        color_histogram=_color_histogram(image, bins=8),
    )


def _average_hash(image: Image.Image, size: int) -> Tuple[bool, ...]:
    resized = image.resize((size, size), Image.Resampling.LANCZOS)
    values = tuple(resized.getdata())
    mean = sum(values) / len(values)
    return tuple(value >= mean for value in values)


def _difference_hash(image: Image.Image, size: int) -> Tuple[bool, ...]:
    resized = image.resize((size + 1, size), Image.Resampling.LANCZOS)
    values = tuple(resized.getdata())
    bits = []
    for y in range(size):
        offset = y * (size + 1)
        for x in range(size):
            bits.append(values[offset + x] >= values[offset + x + 1])
    return tuple(bits)


def _color_histogram(image: Image.Image, bins: int) -> Tuple[float, ...]:
    resized = image.resize((96, 128), Image.Resampling.BILINEAR)
    histogram = resized.histogram()
    channel_size = 256
    bin_width = channel_size // bins
    pixels = resized.width * resized.height
    result = []
    for channel in range(3):
        values = histogram[channel * channel_size : (channel + 1) * channel_size]
        for index in range(bins):
            start = index * bin_width
            end = channel_size if index == bins - 1 else (index + 1) * bin_width
            result.append(sum(values[start:end]) / pixels)
    return tuple(result)


def _bit_similarity(left: Tuple[bool, ...], right: Tuple[bool, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    equal = sum(a == b for a, b in zip(left, right))
    return equal / len(left)


def _histogram_similarity(left: Tuple[float, ...], right: Tuple[float, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    return sum(min(a, b) for a, b in zip(left, right)) / 3.0


def _signature_similarity(left: _ImageSignature, right: _ImageSignature) -> float:
    return (
        0.30 * _bit_similarity(left.average_hash, right.average_hash)
        + 0.35 * _bit_similarity(left.edge_hash, right.edge_hash)
        + 0.25 * _bit_similarity(left.center_hash, right.center_hash)
        + 0.10 * _histogram_similarity(left.color_histogram, right.color_histogram)
    )
