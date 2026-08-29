#!/usr/bin/env python3
"""Read-only exact Fanatics Collect PAID Sales History harvest.

This module is deliberately *not* a Robot KB writer.  It is the first semantic
layer after the anonymous Sales History schema probe.

Live schema proof (2026-08-29) showed an important provider quirk: the public
Sales History API can return rows with ``isComplete=true`` while
``paymentStatus=Unpaid``.  Therefore page/API membership and ``isComplete`` are
never sufficient to prove a sale.  This harvest requires explicit PAID status.

Phase-1 scope:
- public anonymous Fanatics Sales History API only;
- Pokémon individual graded cards only (sealed/wax/boxes/packs/lots blocked);
- explicit ``paymentStatus=PAID`` and ``isComplete=true``;
- PSA grades 8 / 8.5 / 9 / 10 only, because the existing production Fanatics
  native-v3 exact identity resolver is PSA-specific;
- existing Fanatics native-v3 -> exact V4 TCGdex resolver is reused;
- TCGdex ``variants_detailed`` must yield one exact compatible microvariant;
- source ID, provider purchase price and exact sold timestamp are retained;
- currency is intentionally left UNPROVEN because the observed API row has no
  currency field.  A dollar glyph in the UI is not enough to persist USD;
- no SALE_TRANSACTION, no Robot KB mutation, no V4 economic use, no
  notification, no purchase/bid/checkout/payment capability.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

import requests


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import v4_canonical_multimarket as multimarket  # noqa: E402
import v4_global_economic_confirmation as confirmed  # noqa: E402
import v4_global_marketplace_fanatics_native_v3 as fanatics_v3  # noqa: E402
import v4_tcgdex_detailed_variants as detailed_variants  # noqa: E402


API_URL = "https://sales-history-api.services.fanaticscollect.com/api/v1/pub/sales"
DEFAULT_QUERIES = (
    "Pokemon English PSA 10",
    "Pokemon Japanese PSA 10",
)
DEFAULT_PAGES_PER_QUERY = 1
MAX_PAGES_PER_QUERY = 5
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 30.0
MAX_RECORDS = 200
SUPPORTED_GRADES = frozenset({"8", "8.5", "9", "10"})
_POKEMON_RE = re.compile(r"\bPok[eé]mon\b", re.I)
_BLOCKED_PRODUCT_RE = re.compile(
    r"\b(?:booster\s+(?:box|pack)|sealed|wax|factory\s+sealed|"
    r"display\s+box|case\s+of|lot\s+of|complete\s+set|deck\s+box|"
    r"elite\s+trainer\s+box|collection\s+box|tin\b)",
    re.I,
)
_CERT_RE = re.compile(r"^\d{6,14}$")
_SOLD_DATE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,6}))?\s+(?P<zone>PST|PDT)$"
)
_ZONE_OFFSETS = {"PST": -8, "PDT": -7}


class FanaticsPaidSoldError(RuntimeError):
    pass


@dataclass(frozen=True)
class PaidSaleRow:
    source_native_record_id: str
    listing_uuid: str
    title: str
    purchase_price_minor: int
    purchase_price_raw: str
    sold_at_utc: str
    sold_at_raw: str
    auction_type: str
    payment_status: str
    is_complete: bool
    grader: str
    grade: str
    serial: str
    year: int
    category: str
    marketplace_source: str


@dataclass(frozen=True)
class ExactSaleRecord:
    source_native_record_id: str
    source_url: str
    listing_uuid: str
    title: str
    purchase_price_minor: int
    purchase_price_raw: str
    currency: str
    currency_proven: bool
    sold_at_utc: str
    sold_at_raw: str
    auction_type: str
    payment_status: str
    is_complete: bool
    grader: str
    grade: str
    serial: str
    year: int
    category: str
    marketplace_source: str
    identity_status: str
    identity_reason: str
    card_name: str
    set_name: str
    collector_number: str
    language: str
    edition: str
    finish: str
    variant: str
    tcgdex_card_id: str
    microvariant_status: str
    microvariant_reason: str
    paid_sale_status_proven: bool
    provider_purchase_price_proven: bool
    robot_kb_sale_ready: bool


def _norm_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def normalize_grade(value: object) -> str:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return ""
    if parsed <= 0:
        return ""
    integral = parsed.to_integral_value()
    if parsed == integral:
        return str(int(integral))
    return format(parsed.normalize(), "f")


def purchase_price_minor(value: object) -> int:
    try:
        parsed = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise FanaticsPaidSoldError("purchasePrice is not a valid decimal") from exc
    if parsed <= 0:
        raise FanaticsPaidSoldError("purchasePrice must be positive")
    cents = (parsed * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def parse_sold_at(value: object) -> str:
    raw = _norm_text(value)
    match = _SOLD_DATE_RE.fullmatch(raw)
    if match is None:
        raise FanaticsPaidSoldError("soldDate must use the proven PST/PDT schema")
    fraction = (match.group("fraction") or "").ljust(6, "0")[:6]
    try:
        naive = datetime.strptime(
            f"{match.group('date')}T{match.group('time')}.{fraction}",
            "%Y-%m-%dT%H:%M:%S.%f",
        )
    except ValueError as exc:
        raise FanaticsPaidSoldError("soldDate contains an invalid calendar timestamp") from exc
    offset = timezone(timedelta(hours=_ZONE_OFFSETS[match.group("zone")]))
    return naive.replace(tzinfo=offset).astimezone(timezone.utc).isoformat()


def _is_individual_card(row: Mapping[str, Any]) -> bool:
    title = _norm_text(row.get("title"))
    category = _norm_text(row.get("category"))
    if not _POKEMON_RE.search(title):
        return False
    if "wax" in category.casefold() or _BLOCKED_PRODUCT_RE.search(title):
        return False
    # Phase 1 is deliberately slab-only.  Requiring a grader, grade and serial
    # blocks raw/sealed/lots without guessing from category labels.
    grader = _norm_text(row.get("gradingService")).upper()
    grade = normalize_grade(row.get("grade"))
    serial = re.sub(r"\s+", "", str(row.get("serial") or ""))
    return grader == "PSA" and grade in SUPPORTED_GRADES and bool(_CERT_RE.fullmatch(serial))


def precheck_row(row: Mapping[str, Any]) -> tuple[Optional[PaidSaleRow], str]:
    if not isinstance(row, Mapping):
        return None, "ROW_NOT_OBJECT"
    source_id = _norm_text(row.get("id"))
    if not source_id:
        return None, "SOURCE_ID_MISSING"
    if _norm_text(row.get("paymentStatus")).casefold() != "paid":
        return None, "PAYMENT_NOT_PAID"
    if row.get("isComplete") is not True:
        return None, "SALE_NOT_COMPLETE"
    if not _is_individual_card(row):
        return None, "NOT_SUPPORTED_INDIVIDUAL_PSA_CARD"

    title = _norm_text(row.get("title"))
    grader = _norm_text(row.get("gradingService")).upper()
    grade = normalize_grade(row.get("grade"))
    serial = re.sub(r"\s+", "", str(row.get("serial") or ""))
    try:
        price_minor = purchase_price_minor(row.get("purchasePrice"))
        sold_at_utc = parse_sold_at(row.get("soldDate"))
    except FanaticsPaidSoldError as exc:
        return None, f"ROW_SEMANTICS_INVALID:{exc}"
    try:
        year = int(row.get("year"))
    except (TypeError, ValueError):
        return None, "YEAR_INVALID"
    if not 1996 <= year <= 2100:
        return None, "YEAR_INVALID"

    return (
        PaidSaleRow(
            source_native_record_id=source_id,
            listing_uuid=_norm_text(row.get("listingUuid")),
            title=title,
            purchase_price_minor=price_minor,
            purchase_price_raw=_norm_text(row.get("purchasePrice")),
            sold_at_utc=sold_at_utc,
            sold_at_raw=_norm_text(row.get("soldDate")),
            auction_type=_norm_text(row.get("auctionType")).upper(),
            payment_status="PAID",
            is_complete=True,
            grader=grader,
            grade=grade,
            serial=serial,
            year=year,
            category=_norm_text(row.get("category")),
            marketplace_source=_norm_text(row.get("marketplaceSource")),
        ),
        "PAID_COMPLETE_INDIVIDUAL_CARD",
    )


def _microvariant_proof(
    identity: Any,
) -> tuple[bool, str, str, str]:
    _lot, canonical = confirmed.resolve_global_canonical(identity)
    if canonical.status != "EXACT":
        return False, canonical.status or "NO_MATCH", canonical.reason or "TCGDEX_NOT_EXACT", ""
    expected = detailed_variants._expected_from_global_identity(identity)
    decision = detailed_variants.detailed_variant_decision(canonical, expected)
    if not decision.compatible or decision.status != "EXACT":
        return False, decision.status, decision.reason, canonical.card_id or ""
    return True, decision.status, decision.reason, canonical.card_id or ""


def resolve_exact_sale(
    row: PaidSaleRow,
    *,
    identity_resolver: Callable[..., Any] = fanatics_v3.resolve_fanatics_native_identity_v3,
    microvariant_checker: Callable[[Any], tuple[bool, str, str, str]] = _microvariant_proof,
) -> tuple[Optional[ExactSaleRecord], str]:
    resolution = identity_resolver(row.title, proof_text=row.title)
    identity = getattr(resolution, "identity", None)
    coordinate = getattr(resolution, "coordinate", None)
    if getattr(resolution, "status", "") != "EXACT" or identity is None or coordinate is None:
        return None, f"IDENTITY_{getattr(resolution, 'reason', None) or getattr(resolution, 'status', None) or 'UNPROVEN'}"

    if _norm_text(getattr(identity, "grader", "")).upper() != row.grader:
        return None, "IDENTITY_GRADER_CONFLICT"
    if normalize_grade(getattr(identity, "grade", "")) != row.grade:
        return None, "IDENTITY_GRADE_CONFLICT"
    coordinate_year = int(getattr(coordinate, "year", 0) or 0)
    if coordinate_year and coordinate_year != row.year:
        return None, "IDENTITY_YEAR_CONFLICT"

    micro_ok, micro_status, micro_reason, tcgdex_card_id = microvariant_checker(identity)
    if not micro_ok:
        return None, f"MICROVARIANT_{micro_status or 'UNPROVEN'}:{micro_reason or 'unproven'}"

    # Currency remains deliberately unproven: the API row has no currency field.
    # Therefore even an exact paid sale cannot yet be persisted as a transaction.
    return (
        ExactSaleRecord(
            source_native_record_id=row.source_native_record_id,
            source_url=f"https://sales-history-api.services.fanaticscollect.com/api/v1/pub/sales/item/{row.source_native_record_id}",
            listing_uuid=row.listing_uuid,
            title=row.title,
            purchase_price_minor=row.purchase_price_minor,
            purchase_price_raw=row.purchase_price_raw,
            currency="",
            currency_proven=False,
            sold_at_utc=row.sold_at_utc,
            sold_at_raw=row.sold_at_raw,
            auction_type=row.auction_type,
            payment_status=row.payment_status,
            is_complete=row.is_complete,
            grader=row.grader,
            grade=row.grade,
            serial=row.serial,
            year=row.year,
            category=row.category,
            marketplace_source=row.marketplace_source,
            identity_status="EXACT",
            identity_reason=_norm_text(getattr(resolution, "reason", "")),
            card_name=_norm_text(getattr(identity, "name", "")),
            set_name=_norm_text(getattr(identity, "set_name", "")),
            collector_number=_norm_text(getattr(identity, "number", "")),
            language=_norm_text(getattr(identity, "language", "")),
            edition=_norm_text(getattr(identity, "edition", "")),
            finish=_norm_text(getattr(identity, "finish", "")),
            variant=_norm_text(getattr(identity, "variant", "")),
            tcgdex_card_id=tcgdex_card_id,
            microvariant_status=micro_status,
            microvariant_reason=micro_reason,
            paid_sale_status_proven=True,
            provider_purchase_price_proven=True,
            robot_kb_sale_ready=False,
        ),
        "EXACT_PAID_SALE_CURRENCY_UNPROVEN",
    )


def _embedded_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    embedded = payload.get("_embedded")
    if not isinstance(embedded, Mapping):
        return []
    rows = embedded.get("SalesRecords")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, Mapping)]


def _page_meta(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    page = payload.get("page")
    return page if isinstance(page, Mapping) else {}


def fetch_page(
    *,
    query: str,
    page: int,
    size: int,
    timeout_seconds: float,
    get: Callable[..., Any] = requests.get,
) -> Mapping[str, Any]:
    response = get(
        API_URL,
        params={
            "title": query,
            "sort": "purchasePrice,desc",
            "marketplaceSource": "bo",
            "page": page,
            "size": size,
        },
        headers={
            "Accept": "application/json",
            "User-Agent": "RobotPokemonKB-FanaticsPaidSoldReadOnly/1.0",
        },
        timeout=timeout_seconds,
    )
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        raise FanaticsPaidSoldError(f"Fanatics Sales History HTTP {status or 'ERROR'}")
    try:
        payload = response.json()
    except Exception as exc:
        raise FanaticsPaidSoldError("Fanatics Sales History response is not JSON") from exc
    if not isinstance(payload, Mapping):
        raise FanaticsPaidSoldError("Fanatics Sales History payload is not an object")
    return payload


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_FANATICS_PAID_SOLD_HARVEST",
        "public_anonymous_api": True,
        "credentials_used": False,
        "payment_status_required": "PAID",
        "complete_required": True,
        "individual_cards_only": True,
        "phase1_grader": "PSA",
        "currency_semantics_proven": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_harvest(
    *,
    queries: Sequence[str],
    pages_per_query: int,
    page_size: int,
    timeout_seconds: float,
    fetcher: Callable[..., Mapping[str, Any]] = fetch_page,
) -> Mapping[str, Any]:
    confirmed.install_global_external_market_stack()
    detailed_variants.install_v4_tcgdex_detailed_variants()

    summary = safe_summary()
    rejects: Counter[str] = Counter()
    records: list[Mapping[str, Any]] = []
    seen_ids: set[str] = set()
    pages_fetched = 0
    rows_seen = 0
    paid_complete_individual = 0
    exact_identity = 0

    for raw_query in queries:
        query = _norm_text(raw_query)
        if len(query) < 2:
            continue
        for page_number in range(pages_per_query):
            payload = fetcher(
                query=query,
                page=page_number,
                size=page_size,
                timeout_seconds=timeout_seconds,
            )
            pages_fetched += 1
            rows = _embedded_rows(payload)
            rows_seen += len(rows)
            for raw in rows:
                source_id = _norm_text(raw.get("id"))
                if source_id and source_id in seen_ids:
                    rejects["DUPLICATE_SOURCE_ID"] += 1
                    continue
                if source_id:
                    seen_ids.add(source_id)
                row, reason = precheck_row(raw)
                if row is None:
                    rejects[reason] += 1
                    continue
                paid_complete_individual += 1
                exact, exact_reason = resolve_exact_sale(row)
                if exact is None:
                    rejects[exact_reason] += 1
                    continue
                exact_identity += 1
                records.append(asdict(exact))
                if len(records) >= MAX_RECORDS:
                    break
            if len(records) >= MAX_RECORDS:
                break
            meta = _page_meta(payload)
            try:
                total_pages = int(meta.get("totalPages"))
            except (TypeError, ValueError):
                total_pages = page_number + 1
            if not rows or page_number + 1 >= total_pages:
                break
        if len(records) >= MAX_RECORDS:
            break

    summary.update(
        {
            "queries": list(queries),
            "pages_fetched": pages_fetched,
            "rows_seen": rows_seen,
            "paid_complete_individual": paid_complete_individual,
            "exact_identity_microvariant": exact_identity,
            "records_emitted": len(records),
            "robot_kb_sale_ready": 0,
            "blocked": dict(sorted(rejects.items())),
            "records": records,
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only fail-closed Fanatics PAID item-level SOLD harvest"
    )
    parser.add_argument("--query", action="append", dest="queries")
    parser.add_argument("--pages-per-query", type=int, default=DEFAULT_PAGES_PER_QUERY)
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    if not 1 <= args.pages_per_query <= MAX_PAGES_PER_QUERY:
        parser.error(f"--pages-per-query must be between 1 and {MAX_PAGES_PER_QUERY}")
    if not 1 <= args.page_size <= MAX_PAGE_SIZE:
        parser.error(f"--page-size must be between 1 and {MAX_PAGE_SIZE}")
    if not 1.0 <= args.timeout_seconds <= MAX_TIMEOUT_SECONDS:
        parser.error(f"--timeout-seconds must be between 1 and {MAX_TIMEOUT_SECONDS}")
    queries = tuple(args.queries or DEFAULT_QUERIES)

    try:
        payload = run_harvest(
            queries=queries,
            pages_per_query=args.pages_per_query,
            page_size=args.page_size,
            timeout_seconds=args.timeout_seconds,
        )
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        payload = safe_summary()
        payload["error"] = f"{type(exc).__name__}: {exc}"
        try:
            args.output.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except Exception:
            pass
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
