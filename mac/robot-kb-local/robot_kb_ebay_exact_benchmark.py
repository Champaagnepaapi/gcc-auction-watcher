#!/usr/bin/env python3
"""Read-only benchmark of RapidAPI eBay completed-item candidates against exact GCC cards.

This tool is diagnostic only:
- it never writes Robot KB;
- it never feeds V4 economics;
- it never promotes an uncorroborated provider row to proven SOLD;
- title compatibility is not exact identity proof;
- CORROBORATED_SOLD requires a separately reviewed independent evidence record.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlparse


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
CORROBORATION_SCHEMA_VERSION = 1
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


@dataclass(frozen=True)
class CorroborationRecord:
    """Separately reviewed evidence used only to upgrade a benchmark classification."""

    item_id: str
    source: str
    source_url: str
    verified_at: str
    gcc_url: str
    title: str
    card_set: str
    collector_number: str
    language: str
    grader: str
    grade: str
    year: Optional[int]
    date_sold: str
    sale_price_minor: int
    currency: str
    exact_identity_proven: bool
    microvariant_compatible_proven: bool
    sale_status_proven: bool
    final_price_semantics_proven: bool
    best_offer: bool


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

    buying_format = normalized(getattr(candidate, "buying_format", ""))
    if bool(getattr(candidate, "accepted_offer_ambiguous", False)) or "best offer" in buying_format:
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


def _valid_https_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _valid_verified_at(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def independent_source(source: str) -> bool:
    key = normalized(source)
    if not key:
        return False
    blocked_fragments = (
        "rapidapi",
        "ebay average selling price",
        "ecommet",
    )
    return not any(fragment in key for fragment in blocked_fragments)


def _normalized_grader(value: object) -> str:
    key = normalized(value).upper()
    return "BGS" if key == "BECKETT" else key


def _normalized_grade(value: object) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    return match.group(1) if match else normalized(value)


def _same_identity(target: BenchmarkTarget, record: CorroborationRecord) -> bool:
    if target.gcc_url != record.gcc_url:
        return False
    if normalized(target.title) != normalized(record.title):
        return False
    if normalized(target.card_set) != normalized(record.card_set):
        return False
    if normalized(target.collector_number) != normalized(record.collector_number):
        return False
    if normalize_language(target.language) != normalize_language(record.language):
        return False
    if _normalized_grader(target.grader) != _normalized_grader(record.grader):
        return False
    if _normalized_grade(target.grade) != _normalized_grade(record.grade):
        return False
    if target.year is not None and target.year != record.year:
        return False
    return True


def corroboration_status(
    target: BenchmarkTarget,
    candidate: Any,
    record: Optional[CorroborationRecord],
) -> tuple[bool, list[str]]:
    if record is None:
        return False, ["no independent corroboration record"]

    reasons: list[str] = []
    item_id = str(getattr(candidate, "item_id", "") or "")
    if not item_id or item_id != record.item_id:
        reasons.append("item id mismatch")
    if not independent_source(record.source):
        reasons.append("corroboration source is not independent from RapidAPI provider")
    if not _valid_https_url(record.source_url):
        reasons.append("corroboration source URL is not valid HTTPS")
    if not _valid_verified_at(record.verified_at):
        reasons.append("corroboration verification timestamp is invalid")
    if not record.exact_identity_proven or not _same_identity(target, record):
        reasons.append("exact commercial identity is not independently proven")
    if not record.microvariant_compatible_proven:
        reasons.append("microvariant compatibility is not independently proven")
    if not record.sale_status_proven:
        reasons.append("final sale status is not independently proven")
    if not record.final_price_semantics_proven:
        reasons.append("final price semantics are not independently proven")
    if record.best_offer:
        reasons.append("independent evidence marks the sale as Best Offer")

    buying_format = normalized(getattr(candidate, "buying_format", ""))
    if bool(getattr(candidate, "accepted_offer_ambiguous", False)) or "best offer" in buying_format:
        reasons.append("provider candidate is Best Offer ambiguous")

    if record.sale_price_minor <= 0:
        reasons.append("independent sale price is not strictly positive")
    if getattr(candidate, "sale_price_minor", None) != record.sale_price_minor:
        reasons.append("sale price does not match independent evidence")
    candidate_currency = str(getattr(candidate, "currency", "") or "").upper()
    if candidate_currency != record.currency.upper():
        reasons.append("currency does not match independent evidence")
    candidate_date = str(getattr(candidate, "date_sold", "") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", record.date_sold):
        reasons.append("independent sale date is not canonical YYYY-MM-DD")
    if candidate_date != record.date_sold:
        reasons.append("sale date does not match independent evidence")

    if reasons:
        return False, reasons
    return True, [
        "independent evidence proves exact identity and microvariant compatibility",
        "independent evidence matches item id, final sale status, price, currency, and date",
        "sale is explicitly non-Best-Offer",
    ]


def classify_with_corroboration(
    target: BenchmarkTarget,
    candidate: Any,
    corroborations: Mapping[str, CorroborationRecord],
) -> tuple[str, list[str], Optional[CorroborationRecord]]:
    classification, reasons = classify_candidate(target, candidate)
    if classification != "TITLE_COMPATIBLE_NON_OFFER":
        return classification, reasons, None

    item_id = str(getattr(candidate, "item_id", "") or "")
    record = corroborations.get(item_id)
    proven, corroboration_reasons = corroboration_status(target, candidate, record)
    if proven:
        return "CORROBORATED_SOLD", corroboration_reasons, record
    if record is not None:
        reasons = reasons + [
            "independent corroboration rejected: " + "; ".join(corroboration_reasons)
        ]
    return classification, reasons, record


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _required_bool(value: object, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be boolean")
    return value


def _required_int(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be integer")
    return value


def parse_corroboration_record(raw: object) -> CorroborationRecord:
    if not isinstance(raw, Mapping):
        raise ValueError("corroboration record must be an object")
    year_raw = raw.get("year")
    if year_raw is not None and (
        not isinstance(year_raw, int) or isinstance(year_raw, bool)
    ):
        raise ValueError("year must be integer or null")

    return CorroborationRecord(
        item_id=_required_text(raw.get("item_id"), "item_id"),
        source=_required_text(raw.get("source"), "source"),
        source_url=_required_text(raw.get("source_url"), "source_url"),
        verified_at=_required_text(raw.get("verified_at"), "verified_at"),
        gcc_url=_required_text(raw.get("gcc_url"), "gcc_url"),
        title=_required_text(raw.get("title"), "title"),
        card_set=_required_text(raw.get("card_set"), "card_set"),
        collector_number=_required_text(raw.get("collector_number"), "collector_number"),
        language=_required_text(raw.get("language"), "language"),
        grader=_required_text(raw.get("grader"), "grader"),
        grade=_required_text(raw.get("grade"), "grade"),
        year=year_raw,
        date_sold=_required_text(raw.get("date_sold"), "date_sold"),
        sale_price_minor=_required_int(raw.get("sale_price_minor"), "sale_price_minor"),
        currency=_required_text(raw.get("currency"), "currency").upper(),
        exact_identity_proven=_required_bool(
            raw.get("exact_identity_proven"), "exact_identity_proven"
        ),
        microvariant_compatible_proven=_required_bool(
            raw.get("microvariant_compatible_proven"),
            "microvariant_compatible_proven",
        ),
        sale_status_proven=_required_bool(
            raw.get("sale_status_proven"), "sale_status_proven"
        ),
        final_price_semantics_proven=_required_bool(
            raw.get("final_price_semantics_proven"),
            "final_price_semantics_proven",
        ),
        best_offer=_required_bool(raw.get("best_offer"), "best_offer"),
    )


def load_corroboration_file(path: Path) -> dict[str, CorroborationRecord]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read corroboration JSON: {type(exc).__name__}") from exc

    if not isinstance(payload, Mapping):
        raise ValueError("corroboration payload must be an object")
    if payload.get("schema_version") != CORROBORATION_SCHEMA_VERSION:
        raise ValueError(
            f"corroboration schema_version must be {CORROBORATION_SCHEMA_VERSION}"
        )
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("corroboration records must be a list")

    output: dict[str, CorroborationRecord] = {}
    for raw in records:
        record = parse_corroboration_record(raw)
        if record.item_id in output:
            raise ValueError(f"duplicate corroboration item_id: {record.item_id}")
        output[record.item_id] = record
    return output


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


def sanitized_candidate(
    candidate: Any,
    classification: str,
    reasons: Sequence[str],
    corroboration: Optional[CorroborationRecord] = None,
) -> dict[str, Any]:
    row = {
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
    if classification == "CORROBORATED_SOLD" and corroboration is not None:
        row["corroboration"] = {
            "source": corroboration.source,
            "source_url": corroboration.source_url,
            "verified_at": corroboration.verified_at,
            "exact_identity_proven": True,
            "microvariant_compatible_proven": True,
            "sale_status_proven": True,
            "final_price_semantics_proven": True,
        }
    return row


def benchmark_target(
    key: str,
    target: BenchmarkTarget,
    corroborations: Optional[Mapping[str, CorroborationRecord]] = None,
) -> dict[str, Any]:
    from robot_kb_ebay_rapidapi_shadow import fetch_completed_items, parse_response

    corroboration_map = corroborations or {}
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
        "corroborated_sold_count": 0,
        "manual_review": [],
        "item_level_sold": False,
        "genuine_sale_evidence": False,
        "corroborated_genuine_sale_evidence": False,
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
    corroborated_count = 0
    for candidate in parsed.candidates:
        classification, reasons, record = classify_with_corroboration(
            target, candidate, corroboration_map
        )
        counts[classification] = counts.get(classification, 0) + 1
        if classification == "CORROBORATED_SOLD":
            corroborated_count += 1
        if classification in {
            "CORROBORATED_SOLD",
            "TITLE_COMPATIBLE_NON_OFFER",
            "BEST_OFFER_AMBIGUOUS",
            "LOT_OR_MULTI_CARD",
            "LANGUAGE_CONFLICT",
        }:
            reviewed.append(
                sanitized_candidate(candidate, classification, reasons, record)
            )

    row["candidate_count"] = len(parsed.candidates)
    row["classification_counts"] = dict(sorted(counts.items()))
    row["corroborated_sold_count"] = corroborated_count
    row["corroborated_genuine_sale_evidence"] = corroborated_count > 0
    row["manual_review"] = reviewed[:12]
    return row


def run_benchmark(
    key: str,
    limit: int,
    delay_seconds: float,
    corroborations: Optional[Mapping[str, CorroborationRecord]] = None,
) -> tuple[int, dict[str, Any]]:
    targets = fetch_gcc_targets(limit)
    corroboration_map = corroborations or {}
    report: dict[str, Any] = {
        "mode": "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK",
        "requested_targets": limit,
        "selected_targets": len(targets),
        "attempted_targets": 0,
        "provider_http_200": 0,
        "provider_rate_limited": False,
        "classification_totals": {},
        "corroboration_records_loaded": len(corroboration_map),
        "corroborated_sold_count": 0,
        "corroborated_genuine_sale_evidence": False,
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
    corroborated_total = 0
    for index, target in enumerate(targets):
        result = benchmark_target(key, target, corroboration_map)
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
        corroborated_total += int(result.get("corroborated_sold_count", 0))
        if index + 1 < len(targets):
            time.sleep(max(0.0, delay_seconds))

    report["classification_totals"] = dict(sorted(totals.items()))
    report["corroborated_sold_count"] = corroborated_total
    report["corroborated_genuine_sale_evidence"] = corroborated_total > 0
    return exit_code, report


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only exact-title benchmark: GCC fixed cards vs eBay RapidAPI completed candidates"
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument(
        "--corroboration-file",
        type=Path,
        help=(
            "Optional reviewed JSON evidence file. CORROBORATED_SOLD is emitted only "
            "when an independent record exactly matches identity, item id, price/date "
            "and non-Best-Offer semantics."
        ),
    )
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

    corroborations: dict[str, CorroborationRecord] = {}
    if args.corroboration_file is not None:
        try:
            corroborations = load_corroboration_file(args.corroboration_file)
        except ValueError as exc:
            print(
                json.dumps(
                    {
                        "provider_error": f"invalid-corroboration-file:{exc}",
                        "corroborated_sold_count": 0,
                        "robot_kb_write": False,
                        "genuine_sale_evidence": False,
                        "v4_economic_use": False,
                    },
                    sort_keys=True,
                )
            )
            return 2

    code, report = run_benchmark(
        key,
        args.limit,
        args.delay_seconds,
        corroborations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
