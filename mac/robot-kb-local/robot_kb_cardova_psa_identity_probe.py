#!/usr/bin/env python3
"""Read-only Cardova paid-SOLD -> PSA cert -> exact TCGdex identity probe.

Cardova Past Auctions already proves provider-level PAID/COMPLETED evidence and
provides a PSA certificate number.  The direct Cardova set labels are not TCGdex
set names, so this diagnostic reuses the independent PSA cert page as an identity
surface instead of adding Cardova->TCGdex aliases.

Required chain:

  proven Cardova paid-SOLD row
    -> exact PSA cert page
    -> same grade + compatible subject/card number
    -> PSA Brand/Title used only as TCGdex retrieval input
    -> existing V4 deterministic TCGdex stack
    -> existing detailed microvariant gate

The PSA page does not itself become canonical identity and cannot prove a
Cardova payment timestamp.  Even a fully exact result therefore remains
``sale_transaction_ready=false``.  No Robot KB write, V4 economic use,
notification, purchase, bid, offer, checkout or payment is possible here.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import v4_canonical_multimarket as canonical  # noqa: E402
import v4_global_economic_confirmation as confirmation  # noqa: E402
import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402


DEFAULT_MAX_CERT_PAGES = 10
HARD_MAX_CERT_PAGES = 20
DEFAULT_DELAY_SECONDS = 1.5
CERT_URL_TEMPLATE = "https://www.psacard.com/cert/{cert}/psa"
_CERT_RE = re.compile(r"^\d{6,14}$")
_GRADE_RE = re.compile(r"\b(10|[1-9](?:[.,]5)?)\b")
_ITEM_LABELS = (
    "Cert Number",
    "Item Grade",
    "Year",
    "Brand/Title",
    "Subject",
    "Card Number",
    "Category",
    "Variety/Pedigree",
)
_STOP_LABELS = (
    "Set Registry",
    "PSA Population",
    "PSA Estimate",
    "Sales of Similar Items",
)
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


class PsaIdentityProbeError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _name_norm(value: object) -> str:
    return canonical._normalize(value)


def _grade(value: object) -> str:
    text = _norm(value).replace(",", ".")
    matches = _GRADE_RE.findall(text)
    if not matches:
        return ""
    raw = matches[-1].replace(",", ".")
    try:
        number = float(raw)
    except ValueError:
        return ""
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _cert(value: object) -> str:
    text = re.sub(r"\s+", "", str(value or ""))
    return text if _CERT_RE.fullmatch(text) else ""


def _psa_url(cert: str) -> str:
    return CERT_URL_TEMPLATE.format(cert=cert)


def _safe_psa_url(url: str) -> bool:
    parsed = urlsplit(str(url or ""))
    host = (parsed.hostname or "").casefold()
    return parsed.scheme.casefold() == "https" and host in {"psacard.com", "www.psacard.com"}


def extract_item_information(body: str) -> Mapping[str, str]:
    """Extract only bounded public Item Information label/value pairs."""
    lines = [_norm(line) for line in str(body or "").splitlines()]
    lines = [line for line in lines if line]
    try:
        start = next(i for i, line in enumerate(lines) if line.casefold() == "item information") + 1
    except StopIteration:
        return {}

    labels = {label.casefold(): label for label in _ITEM_LABELS}
    stop = {label.casefold() for label in _STOP_LABELS}
    out: dict[str, str] = {}
    index = start
    while index < len(lines):
        token = lines[index]
        folded = token.casefold()
        if folded in stop:
            break
        canonical_label = labels.get(folded)
        if canonical_label is None:
            index += 1
            continue
        value = ""
        look = index + 1
        while look < len(lines):
            candidate = lines[look]
            folded_candidate = candidate.casefold()
            if folded_candidate in stop or folded_candidate in labels:
                break
            value = candidate
            break
        if value:
            out[canonical_label] = value[:500]
        index += 1
    return out


def _pokemon_category(value: object) -> bool:
    token = _name_norm(value)
    return token in {"tcg cards", "pokemon", "pokemon cards"} or "pokemon" in token.split()


def _cardova_psa_surface_gate(
    record: Mapping[str, Any], item: Mapping[str, str]
) -> tuple[bool, str]:
    expected_cert = _cert(record.get("certification_number"))
    observed_cert = _cert(item.get("Cert Number"))
    if not expected_cert or observed_cert != expected_cert:
        return False, "PSA_CERT_CONFLICT"

    expected_grade = _grade(record.get("grade"))
    observed_grade = _grade(item.get("Item Grade"))
    if not expected_grade or observed_grade != expected_grade:
        return False, "PSA_GRADE_CONFLICT"

    subject = _norm(item.get("Subject"))
    if not subject or _name_norm(subject) != _name_norm(record.get("card_name")):
        return False, "PSA_SUBJECT_CONFLICT"

    card_number = _norm(item.get("Card Number"))
    if not card_number or not canonical._same_card_number(
        card_number, record.get("collector_number")
    ):
        return False, "PSA_CARD_NUMBER_CONFLICT"

    brand_title = _norm(item.get("Brand/Title"))
    if not brand_title:
        return False, "PSA_BRAND_TITLE_MISSING"
    if not _pokemon_category(item.get("Category")):
        return False, "PSA_CATEGORY_NOT_POKEMON_TCG"
    return True, "PSA_SURFACE_EXACT"


def _identity_from_psa(record: Mapping[str, Any], item: Mapping[str, str]):
    return paid_identity.CommercialIdentity(
        name=_norm(item.get("Subject")),
        set_name=_norm(item.get("Brand/Title")),
        number=_norm(item.get("Card Number")) or _norm(record.get("collector_number")),
        language=_norm(record.get("language")),
        grader="PSA",
        grade=_grade(item.get("Item Grade")),
        edition="",
        finish="",
        variant="",
    )


def resolve_item(
    record: Mapping[str, Any],
    item: Mapping[str, str],
    *,
    resolver: Callable[[Any], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason
    ok, reason = _cardova_psa_surface_gate(record, item)
    if not ok:
        return None, reason

    identity = _identity_from_psa(record, item)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "PSA_IDENTITY_INPUT_INCOMPLETE"
    try:
        _lot, resolved = resolver(identity)
    except Exception as error:
        return None, f"TCGDEX_EXCEPTION:{type(error).__name__}"

    status = _norm(getattr(resolved, "status", "")) or "UNRESOLVED"
    resolved_reason = _norm(getattr(resolved, "reason", ""))
    if status != "EXACT":
        suffix = f":{resolved_reason}" if resolved_reason else ""
        return None, f"TCGDEX_{status}{suffix}"

    expected_language = "ja" if _name_norm(record.get("language")) in {"ja", "jp", "japanese"} else "en"
    if _norm(getattr(resolved, "language_code", "")).casefold() != expected_language:
        return None, "TCGDEX_LANGUAGE_CONFLICT"

    micro_ok, micro_status, micro_reason, dimensions = microvariant_checker(identity, resolved)
    row = {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "certification_number": _cert(record.get("certification_number")),
        "cardova_card_name": _norm(record.get("card_name")),
        "cardova_set_name": _norm(record.get("set_name")),
        "cardova_collector_number": _norm(record.get("collector_number")),
        "psa_year": _norm(item.get("Year")),
        "psa_brand_title": _norm(item.get("Brand/Title")),
        "psa_subject": _norm(item.get("Subject")),
        "psa_card_number": _norm(item.get("Card Number")),
        "psa_variety_pedigree": _norm(item.get("Variety/Pedigree")),
        "psa_grade": _grade(item.get("Item Grade")),
        "psa_identity_surface": "EXACT",
        "tcgdex_status": "EXACT",
        "tcgdex_reason": resolved_reason,
        "tcgdex_card_id": _norm(getattr(resolved, "card_id", "")),
        "tcgdex_set_id": _norm(getattr(resolved, "set_id", "")),
        "tcgdex_set_name": _norm(getattr(resolved, "set_name", "")),
        "tcgdex_local_id": _norm(getattr(resolved, "local_id", "")),
        "microvariant_status": micro_status,
        "microvariant_reason": micro_reason,
        "microvariant_dimensions": dict(dimensions),
        "microvariant_exact": bool(micro_ok),
        "exact_card_sale_evidence_ready": bool(micro_ok),
        "payment_completed_at_proven": False,
        "sale_transaction_ready": False,
    }
    if not micro_ok:
        suffix = f":{micro_reason}" if micro_reason else ""
        return row, f"MICROVARIANT_{micro_status}{suffix}"
    return row, "EXACT_PSA_TCGDEX_MICROVARIANT"


def _fetch_psa_item(page: Any, cert: str) -> tuple[Optional[Mapping[str, str]], str]:
    url = _psa_url(cert)
    if not _safe_psa_url(url):
        return None, "PSA_URL_REJECTED"
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=15000)
    except Exception as error:
        return None, f"PSA_EXCEPTION:{type(error).__name__}"
    status = int(response.status) if response is not None else 0
    if status in {403, 429}:
        return None, f"PSA_HTTP_{status}"
    if status != 200:
        return None, f"PSA_HTTP_{status}"
    try:
        page.wait_for_timeout(500)
        body = page.locator("body").inner_text(timeout=5000)
    except Exception as error:
        return None, f"PSA_BODY_EXCEPTION:{type(error).__name__}"
    lower = str(body or "").casefold()
    if any(marker in lower for marker in _ANTIBOT_MARKERS):
        return None, "PSA_ACCESS_BLOCKED"
    item = extract_item_information(body)
    if not item:
        return None, "PSA_ITEM_INFORMATION_MISSING"
    return item, "PSA_ITEM_INFORMATION_READY"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PAID_SOLD_PSA_TCGDEX_IDENTITY_PROBE",
        "cardova_paid_evidence_required": True,
        "psa_cert_exact_required": True,
        "psa_grade_exact_required": True,
        "psa_subject_exact_required": True,
        "psa_card_number_compatible_required": True,
        "psa_brand_title_retrieval_only": True,
        "tcgdex_exact_required": True,
        "microvariant_exact_required": True,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "provider_alias_table_added": False,
        "payment_completed_at_proven": False,
        "robot_kb_write": False,
        "sale_transaction_ready": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    fetcher: Callable[[Mapping[str, Any]], tuple[Optional[Mapping[str, str]], str]],
    max_records: int,
    resolver: Callable[[Any], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
) -> Mapping[str, Any]:
    paid_identity.install_tcgdex_stack_once()
    selected = list(records[:max_records])
    blocked: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    psa_exact = 0
    macro_exact = 0
    micro_exact = 0
    circuit_open = False

    for record in selected:
        if circuit_open:
            blocked["PSA_CIRCUIT_OPEN"] += 1
            continue
        item, fetch_reason = fetcher(record)
        if item is None:
            blocked[fetch_reason] += 1
            if fetch_reason in {"PSA_HTTP_403", "PSA_HTTP_429", "PSA_ACCESS_BLOCKED"}:
                circuit_open = True
            continue
        surface_ok, surface_reason = _cardova_psa_surface_gate(record, item)
        if not surface_ok:
            blocked[surface_reason] += 1
            continue
        psa_exact += 1
        row, reason = resolve_item(
            record,
            item,
            resolver=resolver,
            microvariant_checker=microvariant_checker,
        )
        if row is None:
            blocked[reason] += 1
            continue
        macro_exact += 1
        if row.get("microvariant_exact") is True:
            micro_exact += 1
        else:
            blocked[reason] += 1
        rows.append(row)

    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "psa_identity_surface_exact_count": psa_exact,
        "macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": micro_exact,
        "psa_circuit_open": circuit_open,
        "blocked": dict(sorted(blocked.items())),
        "records": rows,
    }


def load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError("input JSON must contain records[]")
    records = payload["records"]
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError("records[] must contain objects only")
    return list(records)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Cardova paid SOLD identity through PSA cert pages and TCGdex")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_CERT_PAGES)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_CERT_PAGES:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_CERT_PAGES}")
    if args.delay_seconds < 0:
        parser.error("--delay-seconds must be non-negative")

    summary = safe_summary()
    try:
        records = load_records(args.input)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            def fetcher(record: Mapping[str, Any]):
                cert = _cert(record.get("certification_number"))
                if not cert:
                    return None, "PSA_CERT_MISSING"
                result = _fetch_psa_item(page, cert)
                if args.delay_seconds:
                    time.sleep(args.delay_seconds)
                return result

            summary.update(
                run_records(
                    records,
                    fetcher=fetcher,
                    max_records=args.max_records,
                )
            )
            context.close()
            browser.close()
        code = 0
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
