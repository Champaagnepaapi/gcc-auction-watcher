from __future__ import annotations

import io
import re
import shutil
import subprocess
import tempfile
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

import watcher
import v4_mislisted_slab_hunter as hunter


# OCR is deliberately optimized only for the three graders the user actually
# targets most often. Other graders keep their official-cert adapters, but a
# failed cert lookup does not fall through to a generic, low-precision OCR.
OCR_FOCUS_GRADERS = frozenset({"PSA", "PCA", "CCC"})
OCR_MIN_CONSENSUS = 2
OCR_TARGET_WIDTH = 1400

# Relative crop inside the slab image: (left, top, width, height).
# The overall grade is on the right side of the top label for PSA/PCA/CCC.
# These ROIs intentionally include enough label context for Tesseract while
# stopping before most subgrade rows.
OCR_LABEL_ROIS: dict[str, tuple[float, float, float, float]] = {
    "PSA": (0.38, 0.00, 0.62, 0.28),
    "PCA": (0.48, 0.00, 0.52, 0.27),
    "CCC": (0.48, 0.00, 0.52, 0.25),
}

_SUBGRADE_TOKENS = (
    "SURFACE",
    "CORNERS",
    "CORNER",
    "COINS",
    "COIN",
    "EDGES",
    "EDGE",
    "COTES",
    "CÔTÉS",
    "CENTERING",
    "CENTRAGE",
)
_GRADE_CONTEXT_TOKENS = (
    "GRADE",
    "NOTE",
    "GEM",
    "MINT",
    "NEUF",
    "PRISTINE",
    "EXCELLENT",
    "NM-MT",
    "NM MT",
    "EX-MT",
    "EX MT",
)
_GRADE_TOKEN_RE = re.compile(
    r"(?<!\d)(10(?:\.0)?|9(?:\.5|\.0)?|8(?:\.5|\.0)?|7(?:\.5|\.0)?|"
    r"6(?:\.5|\.0)?|5(?:\.5|\.0)?|4(?:\.5|\.0)?|3(?:\.5|\.0)?|"
    r"2(?:\.5|\.0)?|1(?:\.5|\.0)?)(?!\d)"
)
_INSTALLED = False


def _normalized_grader(grader: str) -> str:
    return re.sub(r"\s+", " ", (grader or "").strip().upper())


def _ocr_label_clip(box: dict, grader: str) -> Optional[dict[str, float]]:
    grader = _normalized_grader(grader)
    roi = OCR_LABEL_ROIS.get(grader)
    if roi is None or not box:
        return None
    left, top, width, height = roi
    return {
        "x": max(0.0, float(box["x"]) + float(box["width"]) * left),
        "y": max(0.0, float(box["y"]) + float(box["height"]) * top),
        "width": max(40.0, float(box["width"]) * width),
        "height": max(40.0, float(box["height"]) * height),
    }


def _relative_label_crop(image: Image.Image, grader: str) -> Optional[Image.Image]:
    roi = OCR_LABEL_ROIS.get(_normalized_grader(grader))
    if roi is None or image.width < 40 or image.height < 80:
        return None
    left, top, width, height = roi
    x0 = max(0, int(round(image.width * left)))
    y0 = max(0, int(round(image.height * top)))
    x1 = min(image.width, int(round(image.width * (left + width))))
    y1 = min(image.height, int(round(image.height * (top + height))))
    if x1 - x0 < 20 or y1 - y0 < 20:
        return None
    return image.crop((x0, y0, x1, y1))


def _upscale(image: Image.Image) -> Image.Image:
    if image.width <= 0:
        return image
    scale = max(1.0, OCR_TARGET_WIDTH / float(image.width))
    if scale <= 1.05:
        return image.copy()
    return image.resize(
        (int(round(image.width * scale)), int(round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )


def _preprocess_variants(image: Image.Image) -> list[tuple[str, Image.Image, int]]:
    """Independent OCR views; consensus must survive different preprocessing."""
    rgb = _upscale(image.convert("RGB"))
    gray = ImageOps.autocontrast(rgb.convert("L"), cutoff=1)
    sharp = gray.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2))
    high_contrast = ImageEnhance.Contrast(sharp).enhance(1.6)
    return [
        ("rgb", rgb, 6),
        ("gray", gray, 7),
        ("sharp", high_contrast, 11),
    ]


def parse_grade_from_ocr_text(raw_text: str, grader: str) -> tuple[Optional[float], str]:
    """Parse an overall slab grade while explicitly excluding subgrade lines."""
    grader = _normalized_grader(grader)
    if grader not in OCR_FOCUS_GRADERS:
        return None, hunter.IMAGE_GRADE_UNAVAILABLE

    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in (raw_text or "").splitlines()
        if line.strip()
    ]
    candidates: list[float] = []
    for line in lines[:16]:
        upper = line.upper().replace(",", ".")
        if any(token in upper for token in _SUBGRADE_TOKENS):
            continue

        matches = list(_GRADE_TOKEN_RE.finditer(upper))
        if not matches:
            continue

        # A line is eligible only if it clearly looks like the overall grade:
        # grader/grade vocabulary, or a short isolated grade token in the
        # grader-specific right-side ROI. This avoids years, cert numbers and
        # card numbers becoming grades.
        has_context = grader in upper or any(token in upper for token in _GRADE_CONTEXT_TOKENS)
        compact = re.sub(r"[^0-9.]", "", upper)
        isolated_grade = len(matches) == 1 and compact == matches[0].group(1)
        if not has_context and not isolated_grade:
            continue

        for match in matches:
            grade = hunter._numeric_grade(match.group(1))
            if grade is not None:
                candidates.append(grade)

    unique = sorted(set(candidates))
    if len(unique) == 1:
        return unique[0], "OK"
    if len(unique) > 1:
        return None, hunter.IMAGE_GRADE_AMBIGUOUS
    return None, hunter.IMAGE_GRADE_UNAVAILABLE


def _grade_consensus(votes: list[tuple[Optional[float], str]]) -> tuple[Optional[float], str]:
    counts: dict[float, int] = {}
    saw_ambiguous = False
    for grade, status in votes:
        if status == hunter.IMAGE_GRADE_AMBIGUOUS:
            saw_ambiguous = True
        if status != "OK" or grade is None:
            continue
        numeric = hunter._numeric_grade(grade)
        if numeric is not None:
            counts[numeric] = counts.get(numeric, 0) + 1

    if counts:
        winner, winner_count = max(counts.items(), key=lambda item: item[1])
        tied = sum(1 for count in counts.values() if count == winner_count) > 1
        if winner_count >= OCR_MIN_CONSENSUS and not tied:
            return winner, "OK"
        if len(counts) > 1 or saw_ambiguous:
            return None, hunter.IMAGE_GRADE_AMBIGUOUS

    # One OCR view alone is intentionally insufficient to create a mismatch.
    return None, hunter.IMAGE_GRADE_AMBIGUOUS if saw_ambiguous else hunter.IMAGE_GRADE_UNAVAILABLE


def _best_slab_image(page):
    images = page.locator("img")
    best = None
    for index in range(images.count()):
        candidate = images.nth(index)
        try:
            if not candidate.is_visible():
                continue
            box = candidate.bounding_box()
        except Exception:
            continue
        if not box or box["width"] < 120 or box["height"] < 220:
            continue
        area = float(box["width"]) * float(box["height"])
        # Prefer portrait slab/card photography over wide site artwork.
        portrait_bonus = 1.35 if float(box["height"]) >= float(box["width"]) * 1.15 else 1.0
        score = area * portrait_bonus
        if best is None or score > best[0]:
            best = (score, candidate, box)
    return None if best is None else (best[1], best[2])


def _best_slab_box(page) -> Optional[dict]:
    selected = _best_slab_image(page)
    return None if selected is None else selected[1]


def resolve_image_grade_from_page(page, grader: str) -> tuple[Optional[float], str]:
    grader = _normalized_grader(grader)
    if (
        grader not in OCR_FOCUS_GRADERS
        or not hunter._image_ocr_enabled()
        or page is None
        or not shutil.which("tesseract")
    ):
        return None, hunter.IMAGE_GRADE_UNAVAILABLE

    try:
        selected = _best_slab_image(page)
        if selected is None:
            return None, hunter.IMAGE_GRADE_UNAVAILABLE
        image_locator, _box = selected

        # Screenshot the whole slab image first, then crop in pixel space. This
        # avoids tiny CSS-coordinate clips and gives Pillow enough pixels to
        # upscale/normalize the actual label before OCR.
        slab_png = image_locator.screenshot(timeout=3000)
        with Image.open(io.BytesIO(slab_png)) as source:
            label = _relative_label_crop(source, grader)
            if label is None:
                return None, hunter.IMAGE_GRADE_UNAVAILABLE
            variants = _preprocess_variants(label)

        votes: list[tuple[Optional[float], str]] = []
        pass_timeout = max(2.0, hunter.OCR_TIMEOUT_SECONDS / max(1, len(variants)))
        for _variant_name, variant, psm in variants:
            with tempfile.NamedTemporaryFile(suffix=".png") as handle:
                variant.save(handle, format="PNG")
                handle.flush()
                try:
                    completed = subprocess.run(
                        [
                            "tesseract",
                            handle.name,
                            "stdout",
                            "--psm",
                            str(psm),
                            "-c",
                            "preserve_interword_spaces=1",
                        ],
                        capture_output=True,
                        text=True,
                        timeout=pass_timeout,
                        check=False,
                    )
                except subprocess.TimeoutExpired:
                    votes.append((None, hunter.IMAGE_GRADE_UNAVAILABLE))
                    continue
                if completed.returncode != 0:
                    votes.append((None, hunter.IMAGE_GRADE_UNAVAILABLE))
                    continue
                votes.append(parse_grade_from_ocr_text(completed.stdout, grader))
        return _grade_consensus(votes)
    except Exception as error:
        watcher.log(f"Mislisted slab: focused image OCR indisponible ({type(error).__name__})")
        return None, hunter.IMAGE_GRADE_UNAVAILABLE


def evaluate_with_mislisted_slab_guard(
    page,
    lot: watcher.Lot,
    position: int,
    state: dict,
    seen_at: str,
    run_now,
    run_diagnostics: watcher.RunDiagnostics,
):
    """Cert-first guard with non-actionable, focused image-only fallback.

    Official certificate mismatches remain authoritative. OCR is only a lead:
    positive or negative IMAGE_ONLY mismatches notify for manual review but can
    never block, rewrite or otherwise change the normal V4 valuation path.
    """
    grader = _normalized_grader(lot.grader)
    if not grader:
        return hunter._ORIGINAL_EVALUATE(
            page, lot, position, state, seen_at, run_now, run_diagnostics
        )

    inspected = lot if lot.body else watcher.inspect_item(page, lot)
    if inspected.inspection_error:
        return hunter._ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    serial = hunter._serial_from_lot(inspected)
    metadata_grade = hunter._numeric_grade(inspected.grade)
    if not serial or metadata_grade is None:
        return hunter._ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    certificate = hunter.resolve_grader_certificate(page, grader, serial)
    image_status = hunter.IMAGE_GRADE_UNAVAILABLE
    if certificate.status == "OK" and certificate.grade is not None:
        mismatch = hunter.classify_grade_mismatch(
            metadata_grade,
            certificate_grade=certificate.grade,
        )
    else:
        image_grade, image_status = resolve_image_grade_from_page(page, grader)
        mismatch = hunter.classify_grade_mismatch(metadata_grade, image_grade=image_grade)

    if mismatch is None or mismatch.status in {hunter.GRADE_MATCH, hunter.CERT_UNAVAILABLE}:
        if certificate.status != "OK" and image_status == hunter.IMAGE_GRADE_AMBIGUOUS:
            watcher.log(f"Mislisted slab: focused OCR ambigu, aucune alerte | {inspected.url}")
        return hunter._ORIGINAL_EVALUATE(
            page, inspected, position, state, seen_at, run_now, run_diagnostics
        )

    review_key = (
        f"{grader}:{serial}:{metadata_grade:g}:{mismatch.resolved_grade:g}:"
        f"{mismatch.evidence_source}"
    )
    reviewed = state.setdefault("mislisted_slab_reviews", {})
    previous_key = reviewed.get(inspected.url)
    if previous_key != review_key:
        metadata_estimate = hunter._estimate_for_grade(inspected, metadata_grade, run_now)
        resolved_estimate = hunter._estimate_for_grade(inspected, mismatch.resolved_grade, run_now)
        sent = hunter._send_mismatch_review(
            inspected,
            mismatch,
            certificate,
            metadata_estimate.central if metadata_estimate else None,
            resolved_estimate.central if resolved_estimate else None,
        )
        if sent or not watcher.NTFY_TOPIC:
            reviewed[inspected.url] = review_key

    if (
        mismatch.status == hunter.NEGATIVE_GRADE_MISMATCH
        and mismatch.evidence_source == "OFFICIAL_CERT"
    ):
        watcher.log(
            "Mislisted slab safety gate: negative OFFICIAL_CERT mismatch -> "
            "opportunité économique bloquée, revue manuelle requise"
        )
        run_diagnostics.record_valuation(inspected, watcher.REJECTION_OTHER)
        return None

    if mismatch.evidence_source == "IMAGE_OCR":
        watcher.log(
            "Mislisted slab: IMAGE_ONLY mismatch -> revue manuelle uniquement; "
            "valorisation V4 inchangée"
        )

    return hunter._ORIGINAL_EVALUATE(
        page, inspected, position, state, seen_at, run_now, run_diagnostics
    )


def install_v4_mislisted_ocr_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    # Install after v4_mislisted_cert_router so its generic parser cannot
    # overwrite the grader-specific OCR parser, and before the slab hunter
    # installs its evaluator into watcher.
    hunter.parse_grade_from_ocr_text = parse_grade_from_ocr_text
    hunter.resolve_image_grade_from_page = resolve_image_grade_from_page
    hunter.evaluate_with_mislisted_slab_guard = evaluate_with_mislisted_slab_guard
    _INSTALLED = True
