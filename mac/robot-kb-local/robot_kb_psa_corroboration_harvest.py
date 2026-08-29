#!/usr/bin/env python3
"""Build reviewed-format PSA corroboration records for exact eBay candidates.

Manual/local Mac lane only. It composes existing proven pieces instead of
changing V4 economics:

- input candidates come from robot_kb_ebay_exact_benchmark.py (#192);
- retained GCC identity + serialNumber come from Robot KB;
- exact TCGdex/microvariant validation reuses #194;
- PSA cert-page parsing reuses the bounded semantics proven in #190, but only
  locally because GitHub-hosted runners receive HTTP 403;
- output is a schema-v1 corroboration JSON file consumed by #193/#195.

No Robot KB rows are written here. No sale is persisted, no notification is
sent, and no purchase/bid/checkout/payment path exists.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

import watcher  # noqa: E402
from robot_kb_ebay_corroborated_import import (  # noqa: E402
    _candidate_from_mapping,
    _target_from_mapping,
)
from robot_kb_ebay_exact_benchmark import (  # noqa: E402
    CORROBORATION_SCHEMA_VERSION,
    BenchmarkTarget,
    classify_candidate,
    normalize_language,
    normalized,
)
from robot_kb_tcgdex_canonicalize import (  # noqa: E402
    CanonicalizationError,
    GccIdentity,
    _gcc_source_record_ids,
    canonical_plan,
    gcc_listing_id,
    load_gcc_identity,
    resolve_tcgdex_exact,
)


DEFAULT_MAX_CERT_PAGES = 10
MAX_CERT_PAGES = 20
DEFAULT_DELAY_SECONDS = 1.5
CERT_URL_TEMPLATE = "https://www.psacard.com/cert/{cert}/psa"
_CERT_RE = re.compile(r"^\d{6,12}$")
_ITEM_GRADE_RE = re.compile(
    r"\bItem\s+Grade\b\s*:?\s*(?:PSA\s*)?(10|[1-9](?:[.,]5)?)\b",
    re.I,
)
_DATE_RE = re.compile(
    r"\b(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])/(\d{2}|\d{4})\b"
)
_USD_RE = re.compile(r"\$\s*(\d[\d,]*(?:\.\d{1,2})?)")
_PSA_GRADE_RE = re.compile(r"\bPSA\s*(10|[1-9](?:[.,]5)?)\b", re.I)
_ANTIBOT_MARKERS = (
    "captcha",
    "access denied",
    "verify you are human",
    "pardon our interruption",
    "too many requests",
    "just a moment...",
    "attention required",
    "cloudflare",
    "perimeterx",
    "datadome",
)


class PsaCorroborationError(RuntimeError):
    pass


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PsaCorroborationError(
            f"cannot read {label} JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(value, Mapping):
        raise PsaCorroborationError(f"{label} JSON must be an object")
    return value


def _clean_cert(value: object) -> str:
    text = str(value or "").strip()
    return text if _CERT_RE.fullmatch(text) else ""


def _norm_grade(value: object) -> str:
    text = str(value or "").strip().replace(",", ".")
    match = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    return match.group(1) if match else normalized(text)


def _target_matches_identity(target: BenchmarkTarget, identity: GccIdentity) -> bool:
    target_grader = normalized(target.grader).upper()
    identity_grader = normalized(identity.grader).upper()
    if target_grader == "BECKETT":
        target_grader = "BGS"
    if identity_grader == "BECKETT":
        identity_grader = "BGS"
    checks = (
        normalized(target.title) == normalized(identity.title),
        normalized(target.card_set) == normalized(identity.card_set),
        normalized(target.collector_number) == normalized(identity.collector_number),
        normalize_language(target.language).casefold() == identity.language_code,
        target_grader == identity_grader,
        _norm_grade(target.grade) == _norm_grade(identity.grade),
    )
    if not all(checks):
        return False
    if target.year is not None and identity.year is not None and target.year != identity.year:
        return False
    return True


def load_psa_cert_number(kb: Any, listing_id: str) -> str:
    values: set[str] = set()
    record_ids = _gcc_source_record_ids(kb, listing_id)
    if not record_ids:
        raise PsaCorroborationError("GCC listing has no retained Robot KB source record")
    for record_id in record_ids:
        payload = kb.raw_source_payload(record_id)
        if not isinstance(payload, Mapping):
            raise PsaCorroborationError("retained GCC payload is not a JSON object")
        item = payload.get("item")
        if not isinstance(item, Mapping):
            continue
        raw = item.get("serialNumber")
        if raw in (None, ""):
            continue
        cert = _clean_cert(raw)
        if not cert:
            raise PsaCorroborationError("retained GCC serialNumber is malformed")
        values.add(cert)
    if len(values) != 1:
        raise PsaCorroborationError(
            f"GCC listing must have exactly one stable PSA serialNumber; got {len(values)}"
        )
    return next(iter(values))


def _lot_from_identity(identity: GccIdentity) -> watcher.Lot:
    return watcher.Lot(
        url=identity.gcc_url,
        title=identity.title,
        current_price=None,
        source_type="ROBOT_KB_PSA_CORROBORATION",
        grader=identity.grader,
        grade=identity.grade,
        card_set=identity.card_set,
        card_number=identity.collector_number,
        language="Japanese" if identity.language_code == "ja" else "English",
        year=identity.year,
    )


def _page_grade(body: str) -> Optional[float]:
    match = _ITEM_GRADE_RE.search(body or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _iso_date(match: re.Match[str]) -> str:
    month, day, year = match.groups()
    year_i = int(year)
    if len(year) == 2:
        year_i += 2000 if year_i <= 69 else 1900
    try:
        return datetime(year_i, int(month), int(day), tzinfo=timezone.utc).date().isoformat()
    except ValueError as exc:
        raise PsaCorroborationError("PSA sale row contains invalid calendar date") from exc


def _usd_minor(value: str) -> int:
    try:
        amount = Decimal(value.replace(",", ""))
    except InvalidOperation as exc:
        raise PsaCorroborationError("PSA sale row contains invalid USD price") from exc
    if amount <= 0:
        raise PsaCorroborationError("PSA sale row price must be positive")
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sale_blocks(body: str) -> list[str]:
    if "Sales of Similar Items" not in (body or ""):
        return []
    lines = [
        re.sub(r"\s+", " ", line).strip()
        for line in (body or "").splitlines()
        if re.sub(r"\s+", " ", line).strip()
    ]
    rows: list[str] = []
    for index, line in enumerate(lines):
        if _DATE_RE.search(line) is None:
            continue
        block = "\n".join(lines[max(0, index - 4) : min(len(lines), index + 9)])
        if _USD_RE.search(block) is None or _PSA_GRADE_RE.search(block) is None:
            continue
        rows.append(block)
        if len(rows) >= 50:
            break
    return rows


def _format_family(value: str) -> str:
    key = normalized(value)
    if "auction" in key:
        return "AUCTION"
    if "buy it now" in key or "fixed" in key or "bin" in key:
        return "FIXED"
    return ""


def _candidate_sale_proof(candidate: Any, body: str, target_grade: float) -> Mapping[str, Any]:
    if bool(getattr(candidate, "accepted_offer_ambiguous", False)):
        raise PsaCorroborationError("provider candidate has ambiguous Best Offer semantics")
    provider_format = _format_family(str(getattr(candidate, "buying_format", "") or ""))
    if not provider_format:
        raise PsaCorroborationError("provider buying format is not exact enough")

    matches: list[Mapping[str, Any]] = []
    item_id = str(getattr(candidate, "item_id", "") or "")
    for block in _sale_blocks(body):
        if item_id not in block:
            continue
        if re.search(r"\bBest\s+Offer\b", block, re.I):
            continue
        date_match = _DATE_RE.search(block)
        price_match = _USD_RE.search(block)
        grades = [
            float(value.replace(",", "."))
            for value in _PSA_GRADE_RE.findall(block)
        ]
        if date_match is None or price_match is None:
            continue
        if not any(abs(value - target_grade) < 1e-9 for value in grades):
            continue
        psa_format = "AUCTION" if re.search(r"\bAuction\b", block, re.I) else (
            "FIXED"
            if re.search(r"\b(?:Buy\s+It\s+Now|Fixed\s+Price)\b", block, re.I)
            else ""
        )
        if not psa_format or psa_format != provider_format:
            continue
        matches.append(
            {
                "date_sold": _iso_date(date_match),
                "sale_price_minor": _usd_minor(price_match.group(1)),
                "currency": "USD",
                "format_family": psa_format,
            }
        )
    if len(matches) != 1:
        raise PsaCorroborationError(
            f"PSA Sales History must contain exactly one non-Best-Offer row for item {item_id}; got {len(matches)}"
        )
    proof = matches[0]
    if proof["date_sold"] != str(getattr(candidate, "date_sold", "") or ""):
        raise PsaCorroborationError("PSA/provider sale date mismatch")
    if proof["sale_price_minor"] != getattr(candidate, "sale_price_minor", None):
        raise PsaCorroborationError("PSA/provider sale price mismatch")
    if str(getattr(candidate, "currency", "") or "").upper() != "USD":
        raise PsaCorroborationError("provider candidate currency is not USD")
    return proof


def validate_psa_page(
    identity: GccIdentity,
    cert: str,
    body: str,
) -> tuple[float, str]:
    digits = re.sub(r"\D", "", body or "")
    if cert not in digits:
        raise PsaCorroborationError("PSA cert page does not expose requested certificate number")
    lot = _lot_from_identity(identity)
    target_grade = watcher._target_grade(lot)
    page_grade = _page_grade(body)
    if target_grade is None or page_grade is None or abs(float(target_grade) - page_grade) > 1e-9:
        raise PsaCorroborationError("PSA cert page grade conflicts with GCC target")
    score, reason = watcher.psa_apr_match_score(lot, body)
    if score < watcher.PSA_APR_MATCH_MIN_SCORE:
        raise PsaCorroborationError(f"PSA cert identity not exact enough: {reason}")
    return float(target_grade), reason


def candidate_groups(report: Mapping[str, Any]) -> list[tuple[BenchmarkTarget, list[Any]]]:
    if report.get("mode") != "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK":
        raise PsaCorroborationError("benchmark report mode is not trusted")
    if report.get("robot_kb_write") is not False or report.get("v4_economic_use") is not False:
        raise PsaCorroborationError("benchmark safety flags are not fail-closed")
    raw_targets = report.get("targets")
    if not isinstance(raw_targets, list):
        raise PsaCorroborationError("benchmark targets must be a list")
    groups: list[tuple[BenchmarkTarget, list[Any]]] = []
    for result in raw_targets:
        if not isinstance(result, Mapping):
            continue
        target = _target_from_mapping(result.get("target"))
        reviewed = result.get("manual_review")
        if not isinstance(reviewed, list):
            continue
        candidates = []
        for raw_candidate in reviewed:
            try:
                candidate = _candidate_from_mapping(raw_candidate)
            except Exception:
                continue
            classification, _reasons = classify_candidate(target, candidate)
            if classification == "TITLE_COMPATIBLE_NON_OFFER":
                candidates.append(candidate)
        if candidates:
            groups.append((target, candidates))
    groups.sort(key=lambda row: row[0].identity_key)
    return groups


def _fetch_psa_body(page: Any, cert: str) -> tuple[int, str]:
    url = CERT_URL_TEMPLATE.format(cert=cert)
    response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
    status = 0
    if response is not None:
        value = response.status
        value = value() if callable(value) else value
        try:
            status = int(value)
        except (TypeError, ValueError):
            status = 0
    if status >= 400:
        return status, ""
    try:
        page.wait_for_timeout(500)
    except Exception:
        pass
    body = page.locator("body").inner_text(timeout=5000)
    lower = (body or "").casefold()
    if any(marker in lower for marker in _ANTIBOT_MARKERS):
        return 403, ""
    return status or 200, body


def corroboration_record(
    target: BenchmarkTarget,
    candidate: Any,
    cert: str,
    verified_at: str,
) -> Mapping[str, Any]:
    return {
        "item_id": candidate.item_id,
        "source": "PSA Sales History",
        "source_url": CERT_URL_TEMPLATE.format(cert=cert),
        "verified_at": verified_at,
        "gcc_url": target.gcc_url,
        "title": target.title,
        "card_set": target.card_set,
        "collector_number": target.collector_number,
        "language": target.language,
        "grader": target.grader,
        "grade": target.grade,
        "year": target.year,
        "date_sold": candidate.date_sold,
        "sale_price_minor": candidate.sale_price_minor,
        "currency": candidate.currency,
        "exact_identity_proven": True,
        "microvariant_compatible_proven": True,
        "sale_status_proven": True,
        "final_price_semantics_proven": True,
        "best_offer": False,
    }


def run_harvest(
    kb: Any,
    report: Mapping[str, Any],
    page: Any,
    *,
    max_cert_pages: int,
    delay_seconds: float,
    now: Optional[datetime] = None,
) -> tuple[int, Mapping[str, Any]]:
    groups = candidate_groups(report)
    verified_at = (now or datetime.now(timezone.utc)).isoformat()
    records: dict[str, Mapping[str, Any]] = {}
    diagnostics: list[Mapping[str, Any]] = []
    pages = 0
    circuit_open = False
    unexpected = 0

    for target, candidates in groups:
        if pages >= max_cert_pages or circuit_open:
            break
        diagnostic: dict[str, Any] = {
            "gcc_url": target.gcc_url,
            "candidates": len(candidates),
            "records_emitted": 0,
            "status": "BLOCKED",
        }
        try:
            listing_id = gcc_listing_id(target.gcc_url)
            identity = load_gcc_identity(kb, listing_id)
            if (identity.grader or "").strip().upper() != "PSA":
                raise PsaCorroborationError("GCC target is not PSA")
            if not _target_matches_identity(target, identity):
                raise PsaCorroborationError("benchmark target conflicts with retained GCC identity")
            cert = load_psa_cert_number(kb, listing_id)

            # Read-only exact catalog/microvariant proof. Nothing is persisted.
            resolved = resolve_tcgdex_exact(identity)
            plan = canonical_plan(identity, resolved)
            diagnostic["tcgdex_card_id"] = plan.tcgdex_card_id
            diagnostic["microvariant_proven"] = True

            status, body = _fetch_psa_body(page, cert)
            pages += 1
            diagnostic["psa_http_status"] = status
            diagnostic["cert"] = cert
            if status in {403, 429}:
                diagnostic["status"] = "PSA_RATE_OR_ACCESS_BLOCKED"
                circuit_open = True
                diagnostics.append(diagnostic)
                break
            if status != 200:
                raise PsaCorroborationError(f"PSA cert HTTP {status}")
            target_grade, reason = validate_psa_page(identity, cert, body)
            diagnostic["psa_identity_reason"] = reason

            emitted = 0
            for candidate in candidates:
                try:
                    _candidate_sale_proof(candidate, body, target_grade)
                except PsaCorroborationError:
                    continue
                record = corroboration_record(target, candidate, cert, verified_at)
                existing = records.get(candidate.item_id)
                if existing is not None and existing != record:
                    raise PsaCorroborationError(
                        f"same eBay item id maps to conflicting corroboration: {candidate.item_id}"
                    )
                records[candidate.item_id] = record
                emitted += 1
            diagnostic["records_emitted"] = emitted
            diagnostic["status"] = "CORROBORATED" if emitted else "NO_EXACT_PSA_SALE_MATCH"
        except (PsaCorroborationError, CanonicalizationError, ValueError) as exc:
            diagnostic["error"] = str(exc)
        except Exception as exc:
            unexpected += 1
            diagnostic["error"] = f"{type(exc).__name__}: {exc}"
            diagnostic["status"] = "UNEXPECTED_ERROR"
        diagnostics.append(diagnostic)
        if pages < max_cert_pages and not circuit_open:
            time.sleep(max(0.0, delay_seconds))

    payload = {
        "schema_version": CORROBORATION_SCHEMA_VERSION,
        "generated_at": verified_at,
        "source": "PSA Sales History",
        "records": [records[key] for key in sorted(records)],
        "diagnostics": diagnostics,
        "benchmark_groups_available": len(groups),
        "cert_pages_requested": pages,
        "max_cert_pages": max_cert_pages,
        "psa_circuit_open": circuit_open,
        "unexpected_errors": unexpected,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }
    exit_code = 1 if circuit_open or unexpected else 0
    return exit_code, payload


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Local read-only PSA cert corroboration harvest for exact eBay benchmark candidates"
    )
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cert-pages", type=int, default=DEFAULT_MAX_CERT_PAGES)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_cert_pages <= MAX_CERT_PAGES:
        parser.error(f"--max-cert-pages must be between 1 and {MAX_CERT_PAGES}")
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")

    database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
    if not database:
        parser.error("ROBOT_KB_DATABASE_URL is required")

    try:
        report = _load_json(args.benchmark_file, "benchmark")
        from playwright.sync_api import sync_playwright
        from robot_kb.repository import KnowledgeBase

        with KnowledgeBase.open(database) as kb, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                code, payload = run_harvest(
                    kb,
                    report,
                    page,
                    max_cert_pages=args.max_cert_pages,
                    delay_seconds=args.delay_seconds,
                )
            finally:
                browser.close()
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return code
    except Exception as exc:
        summary = {
            "error": f"{type(exc).__name__}: {exc}",
            "robot_kb_write": False,
            "sale_transaction_stored": False,
            "v4_economic_use": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
            "automatic_payment": False,
        }
        print(json.dumps(summary, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
