from __future__ import annotations

import io
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from .poketrace_identity import _normalize_card_number


_CARD_NUMBER_PATTERN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{0,4}\s*\d{1,4}[A-Z]{0,3})\s*/\s*"
    r"([A-Z]{0,4}\s*\d{1,4}[A-Z]{0,3})(?![A-Z0-9])",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CardNumberOCRConfig:
    enabled: bool = False
    minimum_votes: int = 2
    override_minimum_votes: int = 3
    timeout_seconds: float = 4.0

    @classmethod
    def from_env(cls) -> "CardNumberOCRConfig":
        return cls(
            enabled=os.getenv("V5_CARD_NUMBER_OCR_ENABLED", "false").strip().casefold()
            == "true",
            minimum_votes=max(
                2, int(os.getenv("V5_CARD_NUMBER_OCR_MIN_VOTES", "2"))
            ),
            override_minimum_votes=max(
                3, int(os.getenv("V5_CARD_NUMBER_OCR_OVERRIDE_MIN_VOTES", "3"))
            ),
            timeout_seconds=max(
                1.0, float(os.getenv("V5_CARD_NUMBER_OCR_TIMEOUT_SECONDS", "4"))
            ),
        )


@dataclass
class CardNumberOCRCounters:
    attempted: int = 0
    ocr_calls: int = 0
    ocr_failures: int = 0
    candidate_tokens_seen: int = 0
    consensus_found: int = 0
    rejected_no_consensus: int = 0
    rejected_candidate_ambiguous: int = 0
    rescued: int = 0
    structured_number_overrides: int = 0


@dataclass(frozen=True)
class CardNumberOCRResult:
    matched: bool = False
    normalized_number: Optional[str] = None
    votes: int = 0
    candidate: Optional[Mapping[str, object]] = None
    overrides_structured_number: bool = False


def extract_card_number_tokens(text: str) -> Tuple[str, ...]:
    """Return only slash-style collector numbers from OCR text.

    We intentionally ignore bare integers and promo-style identifiers in this
    first local OCR pass. Slash collector numbers are much less likely to be
    confused with HP, attack damage, years, or card text.
    """

    values = []
    for match in _CARD_NUMBER_PATTERN.finditer(text or ""):
        numerator = re.sub(r"\s+", "", match.group(1)).upper()
        denominator = re.sub(r"\s+", "", match.group(2)).upper()
        normalized = _normalize_card_number(f"{numerator}/{denominator}")
        if normalized and normalized.count("/") == 1:
            values.append(normalized)
    return tuple(dict.fromkeys(values))


class LocalCardNumberOCR:
    """Targeted, local collector-number OCR constrained by catalogue candidates.

    Tesseract receives only in-memory PNG bytes through stdin and writes text to
    stdout. No image or OCR text is persisted. A token can be accepted only if
    it exactly matches the normalized cardNumber of a PokeTrace visual
    candidate already selected by name/set/variant metadata.
    """

    def __init__(
        self,
        config: Optional[CardNumberOCRConfig] = None,
        *,
        runner: Optional[Callable[[bytes, int, float], Optional[str]]] = None,
    ) -> None:
        self.config = config or CardNumberOCRConfig.from_env()
        self.runner = runner or self._run_tesseract
        self.counters = CardNumberOCRCounters()

    def resolve(
        self,
        image_bytes: Sequence[bytes],
        candidates: Sequence[Mapping[str, object]],
        structured_number: Optional[str],
    ) -> CardNumberOCRResult:
        if not self.config.enabled or not image_bytes or not candidates:
            return CardNumberOCRResult()

        candidate_by_number: dict[str, list[Mapping[str, object]]] = {}
        for candidate in candidates:
            normalized = _normalize_card_number(candidate.get("cardNumber"))
            if normalized:
                candidate_by_number.setdefault(normalized, []).append(candidate)
        if not candidate_by_number:
            return CardNumberOCRResult()

        self.counters.attempted += 1
        votes: Counter[str] = Counter()
        for raw_image in image_bytes:
            for png_bytes, psm in _ocr_inputs(raw_image):
                self.counters.ocr_calls += 1
                try:
                    text = self.runner(png_bytes, psm, self.config.timeout_seconds)
                except Exception:
                    self.counters.ocr_failures += 1
                    continue
                if text is None:
                    self.counters.ocr_failures += 1
                    continue
                # One OCR pass contributes at most one vote per normalized token.
                tokens = set(extract_card_number_tokens(text))
                accepted_tokens = tokens & candidate_by_number.keys()
                self.counters.candidate_tokens_seen += len(accepted_tokens)
                votes.update(accepted_tokens)

        if not votes:
            self.counters.rejected_no_consensus += 1
            return CardNumberOCRResult()

        ordered = votes.most_common()
        best_number, best_votes = ordered[0]
        second_votes = ordered[1][1] if len(ordered) > 1 else 0
        structured = _normalize_card_number(structured_number)
        overrides = bool(structured and best_number != structured)
        minimum = (
            self.config.override_minimum_votes
            if overrides
            else self.config.minimum_votes
        )
        if best_votes < minimum or best_votes <= second_votes:
            self.counters.rejected_no_consensus += 1
            return CardNumberOCRResult(
                normalized_number=best_number,
                votes=best_votes,
                overrides_structured_number=overrides,
            )

        matching_candidates = candidate_by_number.get(best_number, [])
        if len(matching_candidates) != 1:
            self.counters.rejected_candidate_ambiguous += 1
            return CardNumberOCRResult(
                normalized_number=best_number,
                votes=best_votes,
                overrides_structured_number=overrides,
            )

        self.counters.consensus_found += 1
        self.counters.rescued += 1
        if overrides:
            self.counters.structured_number_overrides += 1
        return CardNumberOCRResult(
            matched=True,
            normalized_number=best_number,
            votes=best_votes,
            candidate=matching_candidates[0],
            overrides_structured_number=overrides,
        )

    @staticmethod
    def _run_tesseract(
        png_bytes: bytes, psm: int, timeout_seconds: float
    ) -> Optional[str]:
        command = (
            "tesseract",
            "stdin",
            "stdout",
            "--psm",
            str(psm),
            "-l",
            "eng",
            "-c",
            "tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789/#",
        )
        try:
            completed = subprocess.run(
                command,
                input=png_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.decode("utf-8", errors="ignore")


def render_card_number_ocr_counters(ocr: LocalCardNumberOCR) -> str:
    counters = ocr.counters
    return "\n".join(
        (
            "=== V5 LOCAL CARD-NUMBER OCR ===",
            f"enabled: {str(ocr.config.enabled).lower()}",
            "scope: visual-rescue failures only",
            "input: lower card strips; in-memory Tesseract stdin/stdout",
            "accepted token class: slash collector numbers only",
            "candidate constraint: exact number must exist in visual PokeTrace pool",
            f"attempted: {counters.attempted}",
            f"OCR calls: {counters.ocr_calls}",
            f"OCR failures: {counters.ocr_failures}",
            f"candidate-matching tokens seen: {counters.candidate_tokens_seen}",
            f"consensus found: {counters.consensus_found}",
            f"rejected no consensus: {counters.rejected_no_consensus}",
            f"rejected duplicate candidate number: {counters.rejected_candidate_ambiguous}",
            f"OCR identities rescued: {counters.rescued}",
            f"structured card-number overrides: {counters.structured_number_overrides}",
            "persisted images/OCR text: 0",
        )
    )


def _ocr_inputs(image_bytes: bytes) -> Tuple[Tuple[bytes, int], ...]:
    """Build four independent OCR passes from lower-card contact sheets."""

    with Image.open(io.BytesIO(image_bytes)) as opened:
        base = ImageOps.exif_transpose(opened).convert("RGB")
        if min(base.size) < 48:
            return ()
        base.thumbnail((1200, 1200))
        strips = []
        for angle in (0, 90, 180, 270):
            rotated = base.rotate(angle, expand=True) if angle else base
            width, height = rotated.size
            top = int(height * 0.68)
            lower = rotated.crop((0, top, width, height))
            strips.extend(
                (
                    lower,
                    lower.crop((0, 0, max(1, int(lower.width * 0.62)), lower.height)),
                    lower.crop(
                        (max(0, int(lower.width * 0.38)), 0, lower.width, lower.height)
                    ),
                )
            )

        gray_sheet = _contact_sheet(strips, threshold=None)
        threshold_sheet = _contact_sheet(strips, threshold=170)
        return (
            (_png_bytes(gray_sheet), 6),
            (_png_bytes(gray_sheet), 11),
            (_png_bytes(threshold_sheet), 6),
            (_png_bytes(threshold_sheet), 11),
        )


def _contact_sheet(
    images: Sequence[Image.Image], threshold: Optional[int]
) -> Image.Image:
    processed = []
    target_width = 1200
    for image in images:
        gray = ImageOps.autocontrast(ImageOps.grayscale(image))
        if threshold is not None:
            gray = gray.point(lambda value: 255 if value >= threshold else 0, mode="1").convert("L")
        ratio = target_width / max(1, gray.width)
        resized = gray.resize(
            (target_width, max(40, int(gray.height * ratio))),
            Image.Resampling.LANCZOS,
        )
        processed.append(resized)

    separator = 12
    total_height = sum(image.height for image in processed) + separator * (len(processed) - 1)
    sheet = Image.new("L", (target_width, max(1, total_height)), 255)
    y = 0
    for image in processed:
        sheet.paste(image, (0, y))
        y += image.height + separator
    return sheet


def _png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=False)
    return buffer.getvalue()
