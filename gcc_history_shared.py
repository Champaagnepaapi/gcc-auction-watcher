"""Strict, side-effect-free parsing primitives for rendered GCC sale history.

The live GCC path available to this repository exposes sales history as rendered
page text.  This module deliberately accepts grades only from explicit grading
evidence.  It performs no network I/O and is shared by the V4 extractor and the
V5 live adapter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


HISTORY_GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG", "SGC", "SFG", "SGS", "SCA", "TCC")

NON_GRADE_PRICE = "PRICE"
NON_GRADE_COUNTER = "COUNTER"
NON_GRADE_DATE = "DATE"
NON_GRADE_CHART = "CHART"
NON_GRADE_OTHER = "OTHER_NUMERIC"

_GRADER_GROUP = "|".join(re.escape(value) for value in HISTORY_GRADERS)
_GRADE_NUMBER = r"-?\d{1,3}(?:[.,]\d{1,2})?"
_VALID_GRADE_NUMBER = r"(?:10(?:[.,]0{1,2})?|[0-9](?:[.,]\d{1,2})?)"
_SPECIAL_QUALIFIERS = (
    ("OC / Off Center", r"(?:OC|OFF[ -]?CENT(?:ER|RE)(?:ED)?|HORS[ -]?CENTRAGE)"),
    ("Miscut", r"(?:MC|MIS[ -]?CUT)"),
    ("Error", r"(?:ERROR|ERREUR)"),
    ("Staining", r"(?:ST|STAIN(?:ING)?)"),
    ("Print Defect", r"(?:PD|PRINT[ -]?DEFECT)"),
    ("Out of Focus", r"(?:OF|OUT[ -]?OF[ -]?FOCUS)"),
    ("Marks", r"(?:MK|MARKS?)"),
    ("Authentic / Altered", r"(?:AUTHENTIC(?:ATED)?|AUTHENTIQUE|ALTERED|ALTEREE?)"),
)


@dataclass(frozen=True)
class HistoricalGradeEvidence:
    grader: str = ""
    grade: Optional[str] = None
    qualifier: Optional[str] = None
    ambiguous: bool = False
    grade_absent: bool = True
    rejected_numeric_kinds: tuple[str, ...] = ()
    invalid_over_ten_tokens: int = 0


@dataclass
class HistoricalParsingDiagnostics:
    transactions_received: int = 0
    transactions_with_grader: int = 0
    transactions_with_numeric_grade: int = 0
    grade_ambiguous: int = 0
    grade_absent: int = 0
    non_grade_numeric_rejected: int = 0
    invalid_over_ten_tokens: int = 0
    special_qualifiers_excluded: int = 0
    usable_comparables: int = 0

    def record(self, evidence: HistoricalGradeEvidence) -> None:
        self.transactions_received += 1
        self.transactions_with_grader += int(bool(evidence.grader))
        self.transactions_with_numeric_grade += int(evidence.grade is not None)
        self.grade_ambiguous += int(evidence.ambiguous)
        self.grade_absent += int(
            evidence.grade is None
            and evidence.qualifier is None
            and not evidence.ambiguous
        )
        self.non_grade_numeric_rejected += len(evidence.rejected_numeric_kinds)
        self.invalid_over_ten_tokens += evidence.invalid_over_ten_tokens
        self.special_qualifiers_excluded += int(evidence.qualifier is not None)

    def merge(self, other: "HistoricalParsingDiagnostics") -> None:
        for field_name in self.__dataclass_fields__:
            setattr(self, field_name, getattr(self, field_name) + getattr(other, field_name))


def _normalized_grade(raw: str) -> Optional[str]:
    try:
        value = float((raw or "").replace(",", "."))
    except ValueError:
        return None
    if value < 0 or value > 10:
        return None
    return f"{value:g}"


def _special_qualifier(text: str, grader: str) -> Optional[str]:
    for label, pattern in _SPECIAL_QUALIFIERS:
        if re.search(rf"\b(?:Grade|Note|Qualifier)?\s*:?\s*{pattern}\b", text, re.I):
            if label == "Authentic / Altered" and grader == "PCA":
                return "PCA A / Authentique"
            return label
    if grader == "PCA" and re.search(
        r"\b(?:Grade|Note)\s*:?\s*A\b|\bPCA[ \t]+A\b", text, re.I
    ):
        return "PCA A / Authentique"
    return None


def _semantic_numeric_tokens(text: str) -> tuple[tuple[str, int, int], ...]:
    """Classify numbers that are visibly attached to a non-grade field."""

    found: list[tuple[str, int, int]] = []

    def add(kind: str, match: re.Match[str]) -> None:
        span = (match.start(), match.end())
        if any(existing[1:] == span for existing in found):
            return
        found.append((kind, *span))

    for match in re.finditer(
        r"(?<!\d)\d+(?:[.,]\d{1,2})?[ \t]*(?:€|\$|EUR\b|USD\b|CHF\b)", text, re.I
    ):
        add(NON_GRADE_PRICE, match)
    for match in re.finditer(
        r"\b(?:Pop(?:ulation)?|Total|Compteur|Count|Nombre(?: de ventes?)?|Nb\.?)\s*:?\s*\d+"
        r"|\b\d+[ \t]*(?:ventes?|sales?|transactions?|r[ée]sultats?|items?)\b",
        text,
        re.I,
    ):
        add(NON_GRADE_COUNTER, match)
    for match in re.finditer(
        r"\b(?:\d{1,2}[-/.]\d{1,2}[-/.](?:19|20)\d{2}|(?:19|20)\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b",
        text,
    ):
        add(NON_GRADE_DATE, match)
    for match in re.finditer(
        r"\b(?:[ÉE]volution|Graph(?:ique)?|Chart|Variation)\s*:?\s*-?\d+(?:[.,]\d+)?[ \t]*%?"
        r"|-?\d+(?:[.,]\d+)?[ \t]*%",
        text,
        re.I,
    ):
        add(NON_GRADE_CHART, match)
    for match in re.finditer(
        rf"\b(?:{_GRADER_GROUP})[ \t]+({_GRADE_NUMBER})\b", text, re.I
    ):
        try:
            outside_grade_range = float(match.group(1).replace(",", ".")) > 10
        except ValueError:
            outside_grade_range = False
        number_span = match.span(1)
        overlaps_semantic_field = any(
            start < number_span[1] and end > number_span[0]
            for _, start, end in found
        )
        if outside_grade_range and not overlaps_semantic_field:
            found.append((NON_GRADE_OTHER, *number_span))
    return tuple(found)


def _invalid_over_ten_count(text: str) -> int:
    values: list[str] = []
    patterns = (
        rf"\b(?:Grade|Note)\s*:?\s*(?:{_GRADER_GROUP}[ \t]*)?({_GRADE_NUMBER})\b",
        rf"\b(?:{_GRADER_GROUP})[ \t]+({_GRADE_NUMBER})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            raw = match.group(1)
            try:
                if float(raw.replace(",", ".")) > 10:
                    values.append(f"{match.start()}:{raw}")
            except ValueError:
                continue
    return len(set(values))


def parse_historical_grade(text: str) -> HistoricalGradeEvidence:
    """Parse one rendered historical transaction conservatively.

    Explicit Grade/Note values win.  The compact fallback never crosses a line
    and rejects a number carrying price/date/counter/chart semantics.  Multiple
    conflicting grading values are reported as ambiguous rather than guessed.
    """

    raw = text or ""
    semantic = _semantic_numeric_tokens(raw)
    rejected_kinds = tuple(value[0] for value in semantic)
    invalid_over_ten = _invalid_over_ten_count(raw)
    lines = [line.strip() for line in raw.splitlines() if line.strip()]

    explicit_graders = {
        match.group(1).upper()
        for match in re.finditer(
            rf"\b(?:Grader|Soci[ée]t[ée](?: de gradation)?|Grading company)\s*:?\s*({_GRADER_GROUP})\b",
            raw,
            re.I,
        )
    }
    all_graders = {
        match.group(1).upper()
        for match in re.finditer(rf"\b({_GRADER_GROUP})\b", raw, re.I)
    }

    if re.search(r"\b(?:RAW|UNGRADED|NON[ -]?GRADED|SANS[ -]?(?:GRADE|GRADATION))\b", raw, re.I):
        if not explicit_graders and not all_graders:
            return HistoricalGradeEvidence(
                grader="RAW",
                grade=None,
                grade_absent=False,
                rejected_numeric_kinds=rejected_kinds,
                invalid_over_ten_tokens=invalid_over_ten,
            )

    explicit: set[tuple[str, str]] = set()
    explicit_re = re.compile(
        rf"\b(?:Grade|Note)\s*:?\s*(?:({_GRADER_GROUP})[ \t]*)?({_GRADE_NUMBER})\b",
        re.I,
    )
    for index, line in enumerate(lines):
        for match in explicit_re.finditer(line):
            grade = _normalized_grade(match.group(2))
            if grade is None:
                continue
            nearby_text = " ".join(lines[max(0, index - 2) : index + 3])
            nearby = re.search(rf"\b({_GRADER_GROUP})\b", nearby_text, re.I)
            grader = (
                match.group(1)
                or (nearby.group(1) if nearby else "")
                or (next(iter(explicit_graders)) if len(explicit_graders) == 1 else "")
            ).upper()
            if grader:
                explicit.add((grader, grade))

    if explicit:
        if len(explicit) == 1:
            grader, grade = next(iter(explicit))
            return HistoricalGradeEvidence(
                grader=grader,
                grade=grade,
                grade_absent=False,
                rejected_numeric_kinds=rejected_kinds,
                invalid_over_ten_tokens=invalid_over_ten,
            )
        return HistoricalGradeEvidence(
            ambiguous=True,
            grade_absent=False,
            rejected_numeric_kinds=rejected_kinds,
            invalid_over_ten_tokens=invalid_over_ten,
        )

    compact: set[tuple[str, str]] = set()
    compact_re = re.compile(
        rf"\b({_GRADER_GROUP})[ \t]+(?:GRADE[ \t]*)?[:#]?[ \t]*({_VALID_GRADE_NUMBER})\b",
        re.I,
    )
    for line in lines:
        for match in compact_re.finditer(line):
            suffix = line[match.end() :]
            if re.match(
                r"[ \t]*(?:€|\$|EUR\b|USD\b|CHF\b|%|[/.-]\d|ventes?\b|sales?\b|transactions?\b|items?\b)",
                suffix,
                re.I,
            ):
                continue
            grade = _normalized_grade(match.group(2))
            if grade is not None:
                compact.add((match.group(1).upper(), grade))

    if compact:
        if len(compact) == 1:
            grader, grade = next(iter(compact))
            return HistoricalGradeEvidence(
                grader=grader,
                grade=grade,
                grade_absent=False,
                rejected_numeric_kinds=rejected_kinds,
                invalid_over_ten_tokens=invalid_over_ten,
            )
        return HistoricalGradeEvidence(
            ambiguous=True,
            grade_absent=False,
            rejected_numeric_kinds=rejected_kinds,
            invalid_over_ten_tokens=invalid_over_ten,
        )

    grader = ""
    recognized = explicit_graders or all_graders
    if len(recognized) == 1:
        grader = next(iter(recognized))
    qualifier = _special_qualifier(raw, grader)
    if qualifier:
        return HistoricalGradeEvidence(
            grader=grader,
            qualifier=qualifier,
            grade_absent=False,
            rejected_numeric_kinds=rejected_kinds,
            invalid_over_ten_tokens=invalid_over_ten,
        )
    return HistoricalGradeEvidence(
        grader=grader,
        ambiguous=len(recognized) > 1,
        grade_absent=True,
        rejected_numeric_kinds=rejected_kinds,
        invalid_over_ten_tokens=invalid_over_ten,
    )
