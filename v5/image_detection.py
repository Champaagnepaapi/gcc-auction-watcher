"""Detection locale et conservatrice d'un dos de carte Pokemon.

La signature ne cherche ni a reconnaitre la carte ni a attribuer un grade.
Elle combine uniquement des indices de couleur et de position typiques du dos
international bleu. Les variantes regionales ou historiques non couvertes
restent candidates; elles ne sont jamais forcees en CONFIRMED.
"""

from __future__ import annotations

import colorsys
import io
import warnings
from dataclasses import dataclass
from typing import Iterable, Tuple


BACK_IMAGE_CONFIRMED = "BACK_IMAGE_CONFIRMED"
BACK_IMAGE_CANDIDATE = "BACK_IMAGE_CANDIDATE"
BACK_IMAGE_UNKNOWN = "BACK_IMAGE_UNKNOWN"


@dataclass(frozen=True)
class BackVisualFeatures:
    subject_aspect_ratio: float
    blue_ratio: float
    blue_border_ratio: float
    yellow_ratio: float
    center_red_ratio: float
    center_white_ratio: float
    center_dark_ratio: float


@dataclass(frozen=True)
class BackImageAssessment:
    state: str
    confidence: float
    profile: str


class LocalPokemonBackDetector:
    """Classifieur local sans modele distant, OCR ou service payant."""

    def assess_bytes(self, image_bytes: bytes) -> BackImageAssessment:
        try:
            features = extract_back_visual_features(image_bytes)
        except (ImportError, OSError, TypeError, ValueError, Warning):
            return BackImageAssessment(BACK_IMAGE_UNKNOWN, 0.0, "unreadable")
        return self.assess_features(features)

    @staticmethod
    def assess_features(features: BackVisualFeatures) -> BackImageAssessment:
        signals = {
            "portrait": 0.58 <= features.subject_aspect_ratio <= 0.82,
            "blue": features.blue_ratio >= 0.34,
            "blue_border": features.blue_border_ratio >= 0.52,
            "yellow": features.yellow_ratio >= 0.018,
            "center_red": features.center_red_ratio >= 0.018,
            "center_white": features.center_white_ratio >= 0.035,
            "center_dark": features.center_dark_ratio >= 0.012,
        }
        weights = {
            "portrait": 0.10,
            "blue": 0.20,
            "blue_border": 0.25,
            "yellow": 0.15,
            "center_red": 0.15,
            "center_white": 0.10,
            "center_dark": 0.05,
        }
        confidence = sum(weights[name] for name, present in signals.items() if present)
        international_core = all(
            signals[name]
            for name in (
                "portrait",
                "blue",
                "blue_border",
                "yellow",
                "center_red",
                "center_white",
                "center_dark",
            )
        )
        if international_core and confidence >= 0.90:
            return BackImageAssessment(
                BACK_IMAGE_CONFIRMED, confidence, "international_blue"
            )
        if confidence >= 0.50:
            profile = (
                "regional_or_era_variant"
                if signals["blue_border"] and signals["yellow"]
                else "partial_visual_match"
            )
            return BackImageAssessment(BACK_IMAGE_CANDIDATE, confidence, profile)
        return BackImageAssessment(BACK_IMAGE_UNKNOWN, confidence, "no_strong_match")


def _is_blue(hue: float, saturation: float, value: float) -> bool:
    return 0.52 <= hue <= 0.72 and saturation >= 0.34 and 0.14 <= value <= 0.95


def _is_yellow(hue: float, saturation: float, value: float) -> bool:
    return 0.10 <= hue <= 0.19 and saturation >= 0.42 and value >= 0.48


def _is_red(hue: float, saturation: float, value: float) -> bool:
    return (hue <= 0.05 or hue >= 0.95) and saturation >= 0.42 and value >= 0.30


def _ratio(matches: Iterable[bool]) -> float:
    values = tuple(matches)
    return sum(1 for value in values if value) / len(values) if values else 0.0


def extract_back_visual_features(image_bytes: bytes) -> BackVisualFeatures:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = 25_000_000
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGB")
            image.thumbnail((160, 160))
            width, height = image.size
            if width < 8 or height < 8:
                raise ValueError("image too small")
            pixels = list(image.getdata())

    hsv = [colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255) for red, green, blue in pixels]
    subject_indexes = [
        index
        for index, (_, saturation, value) in enumerate(hsv)
        if saturation >= 0.16 or value <= 0.92
    ]
    if len(subject_indexes) < max(20, int(width * height * 0.12)):
        raise ValueError("subject not found")
    xs = [index % width for index in subject_indexes]
    ys = [index // width for index in subject_indexes]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    subject_width = right - left + 1
    subject_height = bottom - top + 1
    if subject_width < 4 or subject_height < 6:
        raise ValueError("subject too small")

    border_x = max(1, int(subject_width * 0.14))
    border_y = max(1, int(subject_height * 0.14))
    center_left = left + int(subject_width * 0.24)
    center_right = right - int(subject_width * 0.24)
    center_top = top + int(subject_height * 0.28)
    center_bottom = bottom - int(subject_height * 0.28)

    subject_hsv = []
    border_hsv = []
    center_hsv = []
    for index in subject_indexes:
        x = index % width
        y = index // width
        color = hsv[index]
        subject_hsv.append(color)
        if (
            x < left + border_x
            or x > right - border_x
            or y < top + border_y
            or y > bottom - border_y
        ):
            border_hsv.append(color)
    for y in range(center_top, center_bottom + 1):
        for x in range(center_left, center_right + 1):
            center_hsv.append(hsv[y * width + x])

    return BackVisualFeatures(
        subject_aspect_ratio=subject_width / subject_height,
        blue_ratio=_ratio(_is_blue(*color) for color in subject_hsv),
        blue_border_ratio=_ratio(_is_blue(*color) for color in border_hsv),
        yellow_ratio=_ratio(_is_yellow(*color) for color in subject_hsv),
        center_red_ratio=_ratio(_is_red(*color) for color in center_hsv),
        center_white_ratio=_ratio(
            saturation <= 0.18 and value >= 0.68
            for _, saturation, value in center_hsv
        ),
        center_dark_ratio=_ratio(value <= 0.28 for _, _, value in center_hsv),
    )
