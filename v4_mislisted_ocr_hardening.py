from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from typing import Optional

import watcher
import v4_mislisted_slab_hunter as hunter


# OCR is deliberately optimized only for the three graders the user actually
# targets most often. Other graders keep their official-cert adapters, but a
# failed cert lookup does not fall through to a generic, low-precision OCR.
OCR_FOCUS_GRADERS = frozenset({"PSA", "PCA", "CCC"})
OCR_PSM_MODES = (6, 7, 11)
OCR_MIN_CONSENSUS = 2

# Relative crop inside the visible slab image: (left, top, width, height).
# All three layouts put the overall grade on the right side of the top label.
# Keeping the crop above the subgrade row is critical for CCC/PCA-style labels.
OCR_LABEL_ROIS: dict[str, tuple[float, float, float, float]] = {
    "PSA": (0.42, 0.00, 0.58, 0.23),
    "PCA": (0.56, 0.00, 0.44, 0.22),
    "CCC": (0.60, 0.00, 0.40, 0.21),
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
    for line in lines[:12]:
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

    # One OCR pass alone is intentionally insufficient to create a mismatch.
    return None, hunter.IMAGE_GRADE_AMBIGUOUS if saw_ambiguous else hunter.IMAGE_GRADE_UNAVAILABLE


def _best_slab_box(page) -> Optional[dict]:
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
        portrait_bonus = 1.25 if float(box["height"]) >= float(box["width"]) * 1.15 else 1.0
        score = area * portrait_bonus
        if best is None or score > best[0]:
            best = (score, box)
    return None if best is None else best[1]


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
        box = _best_slab_box(page)
        clip = _ocr_label_clip(box, grader) if box is not None else None
        if clip is None:
            return None, hunter.IMAGE_GRADE_UNAVAILABLE

        png_bytes = page.screenshot(clip=clip)
        votes: list[tuple[Optional[float], str]] = []
        pass_timeout = max(2.0, hunter.OCR_TIMEOUT_SECONDS / max(1, len(OCR_PSM_MODES)))
        with tempfile.NamedTemporaryFile(suffix=".png") as handle:
            handle.write(png_bytes)
            handle.flush()
            for psm in OCR_PSM_MODES:
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
