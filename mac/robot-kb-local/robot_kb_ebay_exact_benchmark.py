#!/usr/bin/env python3
"""Read-only benchmark of RapidAPI eBay completed-item candidates against exact GCC cards.

This tool is diagnostic only:
- it never writes Robot KB;
- it never feeds V4 economics;
- it never promotes a provider row to proven SOLD;
- title compatibility is not exact identity proof.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

SUPPORTED_GRADERS = frozenset({"PSA", "CGC", "BGS", "BECKETT"})
DEFAULT_LIMIT = 10
MAX_LIMIT = 20
DEFAULT_DELAY_SECONDS = 3.0
LOT_RE = re.compile(
    r"\b(?:lot(?:\s+of)?|bundle|set\s+of\s+\d+|complete\s+set|master\s+set|"
    r"play\s*set|pair|[2-9]x|10x)\b",
    re.I,
)
LANGUAGE_MARKERS = {
    "EN": ("english", "anglais", " eng "),
    "JA": ("japanese", "japonais", "japan", " jpn ", " jp "),
}


@dataclass(frozen=True)
class BenchmarkTarget:
    gcc_url: str
    title: str
    card_set: str
    collector_number: str
    language: str
    grader: str
    grade: str
    year: Optional[int] = None

    @property
    def identity_key(self) -> str:
        return "|".join(
            (
                normalized(self.title),
                normalized(self.card_set),
                normalized(self.collector_number),
                normalize_language(self.language),
                normalized(self.grader),
                normalized(self.grade),
            )
        )

    @property
    def query(self) -> str:
        language = normalize_language(self.language)
        parts = [
            "Pokemon",
            self.title,
            self.card_set,
            self.collector_number,
            "Japanese" if language == "JA" else ("English" if language == "EN" else ""),
            self.grader,
            self.grade,
            str(self.year or ""),
        ]
        return " ".join(str(part).strip() for part in parts if str(part).strip())


def normalized(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def normalize_language(value: object) -> str:
    key = normalized(value)
    if key in {"english", "anglais", "en", "eng"}:
        return "EN"
    if key in {"japanese", "japonais", "ja", "jp", "jpn", "japan"}:
        return "JA"
    return ""


def _bounded_tokens_present(needle: str, haystack: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", normalized(needle))
    if not tokens:
        return False
    pattern = r"\b" + r"[\W_]*".join(re.escape(token) for token in tokens) + r"\b"
    return re.search(pattern, haystack, re.I) is not None


def collector_number_present(reference: str, title: str) -> bool:
    parts = re.findall(r"[a-z0-9]+", normalized(reference))
    if not parts:
        return False
    raw = unicodedata.normalize("NFKD", title.casefold())
    pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(
        re.escape(part) for part in parts
    ) + r"(?![a-z0-9])"
    return re.search(pattern, raw, re.I) is not None


def grader_grade_present(grader: str, grade: str, title: str) -> bool:
    grader_key = "BGS" if normalized(grader) == "beckett" else normalized(grader).upper()
    grade_tokens = re.findall(r"\d+(?:\.\d+)?", str(grade or ""))
    if not grader_key or not grade_tokens:
        return False
    grade_value = re.escape(grade_tokens[0])
    pattern = rf"\b{re.escape(grader_key)}\b.{{0,35}}\b{grade_value}\b"
    return re.search(pattern, title, re.I) is not None


def language_status(language: str, title: str) -> str:
    target = normalize_language(language)
    padded = f" {normalized(title)} "
    has_en = any(marker in padded for marker in LANGUAGE_MARKERS["EN"])
    has_ja = any(marker in padded for marker in LANGUAGE_MARKERS["JA"])
    if target == "JA":
        if has_en and not has_ja:
            return "CONFLICT"
        return "PROVEN" if has_ja else "UNPROVEN"
    if target == "EN":
        if has_ja and not has_en:
            return "CONFLICT"
        return "PROVEN" if has_en else "UNPROVEN"
    return "UNPROVEN"


def classify_candidate(target: BenchmarkTarget, candidate: Any) -> tuple[str, list[str]]:
    title = str(getattr(candidate, "title", "") or "")
    reasons: list[str] = []

    if bool(getattr(candidate, "accepted_offer_ambiguous", False)):
        reasons.append("best-offer price semantics ambiguous")
        return "BEST_OFFER_AMBIGUOUS", reasons

    if LOT_RE.search(title):
        reasons.append("title indicates lot/multi-card product")
        return "LOT_OR_MULTI_CARD", reasons

    if not grader_grade_present(target.grader, target.grade, title):
        reasons.append("grader/grade not explicitly compatible")
        return "GRADER_GRADE_UNPROVEN", reasons

    if not collector_number_present(target.collector_number, title):
        reasons.append("collector number not explicitly compatible")
        return "COLLECTOR_NUMBER_UNPROVEN", reasons

    lang = language_status(target.language, title)
    if lang == "CONFLICT":
        reasons.append("language conflicts with GCC target")
        return "LANGUAGE_CONFLICT", reasons
    if lang != "PROVEN":
        reasons.append("language not explicit in provider title")
        return "LANGUAGE_UNPROVEN", reasons

    if not _bounded_tokens_present(target.title, title):
        reasons.append("card name not explicitly compatible")
        return "CARD_NAME_UNPROVEN", reasons

    if not _bounded_tokens_present(target.card_set, title):
        reasons.append("set name not explicitly compatible")
        return "SET_UNPROVEN", reasons

    reasons.append("title contains all benchmark identity dimensions")
    return "TITLE_COMPATIBLE_NON_OFFER", reasons


def select_targets(lots: Iterable[Any], limit: int) -> list[BenchmarkTarget]:
    eligible: list[BenchmarkTarget] = []
    seen: set[str] = set()
    for lot in lots:
        language = normalize_language(getattr(lot, "language", ""))
        grader_raw = str(getattr(lot, "grader", "") or "").strip().upper()
        grader = "BGS" if grader_raw == "BECKETT" else grader_raw
        grade = str(getattr(lot, "grade", "") or "").strip()
        target = BenchmarkTarget(
            gcc_url=str(getattr(lot, "url", "") or ""),
            title=str(getattr(lot, "title", "") or "").strip(),
            card_set=str(getattr(lot, "card_set", "") or "").strip(),
            collector_number=str(getattr(lot, "card_number", "") or "").strip(),
            language=language,
            grader=grader,
            grade=grade,
            year=getattr(lot, "year", None),
        )
        if (
            language not in {"EN", "JA"}
            or grader not in SUPPORTED_GRADERS
            or not target.title
            or not target.card_set
            or not target.collector_number
            or not target.grade
            or LOT_RE.search(target.title)
        ):
            continue
        if target.identity_key in seen:
            continue
        seen.add(target.identity_key)
        eligible.append(target)

    def priority(target: BenchmarkTarget) -> tuple[int, int, str]:
        grade_rank = 0 if target.grade in {"10", "10.0"} else (1 if target.grade in {"9", "9.0"} else 2)
        language_rank = 0 if target.language == "JA" else 1
        return grade_rank, language_rank, target.identity_key

    eligible.sort(key=priority)
    if limit <= 1:
        return eligible[:limit]

    # Preserve deterministic diversity when both languages are available.
    ja = [row for row in eligible if row.language == "JA"]
    en = [row for row in eligible if row.language == "EN"]
    output: list[BenchmarkTarget] = []
    while len(output) < limit and (ja or en):
        for bucket in (ja, en):
            if bucket and len(output) < limit:
                output.append(bucket.pop(0))
    if len(output) < limit:
        used = {row.identity_key for row in output}
        output.extend(row for row in eligible if row.identity_key not in used)
    return output[:limit]


def fetch_gcc_targets(limit: int) -> list[BenchmarkTarget]:
    from watcher import collect_fixed_lots_from_api

    lots = collect_fixed_lots_from_api(
        page_size=100,
        max_pages=2,
        min_price=None,
        max_price=None,
    )
    return select_targets(lots, limit)


def sanitized_candidate(candidate: Any, classification: str, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "item_id": str(getattr(candidate, "item_id", "") or ""),
        "title": str(getattr(candidate, "title", "") or ""),
        "date_sold": str(getattr(candidate, "date_sold", "") or ""),
        "sale_price_minor": getattr(candidate, "sale_price_minor", None),
        "currency": str(getattr(candidate, "currency", "") or ""),
        "buying_format": str(getattr(candidate, "buying_format", "") or ""),
        "accepted_offer_ambiguous": bool(
            getattr(candidate, "accepted_offer_ambiguous", False)
        ),
        "classification": classification,
        "reasons": list(reasons),
    }


def benchmark_target(key: str, target: BenchmarkTarget) -> dict[str, Any]:
    from robot_kb_ebay_rapidapi_shadow import fetch_completed_items, parse_response

    status, payload, _headers = fetch_completed_items(
        key,
        target.query,
        max_search_results=60,
        site_id="0",
    )
    row: dict[str, Any] = {
        "target": asdict(target),
        "query": target.query,
        "http_status": status,
        "provider_error": "",
        "candidate_count": 0,
        "classification_counts": {},
        "manual_review": [],
        "item_level_sold": False,
        "genuine_sale_evidence": False,
        "v4_economic_use": False,
    }
    if status != 200:
        row["provider_error"] = f"http-{status}"
        return row

    parsed = parse_response(payload, site_id="0")
    if parsed.provider_error:
        row["provider_error"] = parsed.provider_error
        return row

    counts: dict[str, int] = {}
    reviewed: list[dict[str, Any]] = []
    for candidate in parsed.candidates:
        classification, reasons = classify_candidate(target, candidate)
        counts[classification] = counts.get(classification, 0) + 1
        if classification in {
            "TITLE_COMPATIBLE_NON_OFFER",
            "BEST_OFFER_AMBIGUOUS",
            "LOT_OR_MULTI_CARD",
            "LANGUAGE_CONFLICT",
        }:
            reviewed.append(sanitized_candidate(candidate, classification, reasons))

    row["candidate_count"] = len(parsed.candidates)
    row["classification_counts"] = dict(sorted(counts.items()))
    row["manual_review"] = reviewed[:12]
    return row


def run_benchmark(key: str, limit: int, delay_seconds: float) -> tuple[int, dict[str, Any]]:
    targets = fetch_gcc_targets(limit)
    report: dict[str, Any] = {
        "mode": "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK",
        "requested_targets": limit,
        "selected_targets": len(targets),
        "attempted_targets": 0,
        "provider_http_200": 0,
        "provider_rate_limited": False,
        "classification_totals": {},
        "targets": [],
        "item_level_sold": False,
        "genuine_sale_evidence": False,
        "exact_identity_proven": False,
        "final_price_semantics_proven": False,
        "v4_economic_use": False,
        "robot_kb_write": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }
    if not targets:
        report["provider_error"] = "no-eligible-gcc-targets"
        return 1, report

    totals: dict[str, int] = {}
    exit_code = 0
    for index, target in enumerate(targets):
        result = benchmark_target(key, target)
        report["targets"].append(result)
        report["attempted_targets"] += 1
        status = result["http_status"]
        if status == 200 and not result["provider_error"]:
            report["provider_http_200"] += 1
        else:
            exit_code = 1
        if status == 429:
            report["provider_rate_limited"] = True
            break
        for name, count in result["classification_counts"].items():
            totals[name] = totals.get(name, 0) + int(count)
        if index + 1 < len(targets):
            time.sleep(max(0.0, delay_seconds))

    report["classification_totals"] = dict(sorted(totals.items()))
    return exit_code, report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only exact-title benchmark: GCC fixed cards vs eBay RapidAPI completed candidates"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= MAX_LIMIT:
        parser.error(f"--limit must be between 1 and {MAX_LIMIT}")
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")

    import os

    key = os.getenv("ROBOT_KB_EBAY_RAPIDAPI_KEY", "").strip()
    if not key:
        print(
            json.dumps(
                {
                    "provider_error": "rapidapi-key-not-configured",
                    "robot_kb_write": False,
                    "genuine_sale_evidence": False,
                    "v4_economic_use": False,
                },
                sort_keys=True,
            )
        )
        return 2

    code, report = run_benchmark(key, args.limit, args.delay_seconds)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
