#!/usr/bin/env python3
"""Manual-only importer for independently corroborated eBay completed sales.

This module is deliberately narrow:
- no network calls;
- one explicit eBay item id per invocation;
- default mode validates only;
- write mode requires an already PROVEN GCC -> canonical-card link in Robot KB;
- the RapidAPI candidate is reclassified against the reviewed corroboration file;
- Best Offer, date/price mismatch, identity ambiguity, or missing canonical link fail closed;
- only CORROBORATED_SOLD may become a Robot KB SALE_TRANSACTION;
- nothing here feeds V4 economics or performs a commercial transaction.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from robot_kb_ebay_exact_benchmark import (  # noqa: E402
    BenchmarkTarget,
    CorroborationRecord,
    classify_with_corroboration,
    load_corroboration_file,
    normalized,
)


SOURCE_CODE = "ebay_corroborated_sale"
SOURCE_NAME = "eBay sale corroborated by independent reviewed evidence"
SOURCE_ROLE = "PROVIDER"
IMPORT_SCHEMA_VERSION = 1
_ITEM_ID_RE = re.compile(r"^\d{8,20}$")
_GCC_ITEM_RE = re.compile(
    r"^/item/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.I,
)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CorroboratedImportError(RuntimeError):
    pass


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorroboratedImportError(
            f"cannot read {label} JSON: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise CorroboratedImportError(f"{label} JSON must be an object")
    return payload


def gcc_listing_id(gcc_url: str) -> str:
    try:
        parsed = urlparse(gcc_url)
    except ValueError as exc:
        raise CorroboratedImportError("invalid GCC target URL") from exc
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or host not in {
        "gradedcardcenter.com",
        "www.gradedcardcenter.com",
    }:
        raise CorroboratedImportError("GCC target URL is not a canonical HTTPS GCC URL")
    match = _GCC_ITEM_RE.fullmatch(parsed.path)
    if match is None:
        raise CorroboratedImportError("GCC target URL does not contain a canonical item UUID")
    return match.group(1).lower()


def _target_from_mapping(raw: object) -> BenchmarkTarget:
    if not isinstance(raw, Mapping):
        raise CorroboratedImportError("benchmark target must be an object")
    year = raw.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise CorroboratedImportError("benchmark target year must be integer or null")
    values = {}
    for field in (
        "gcc_url",
        "title",
        "card_set",
        "collector_number",
        "language",
        "grader",
        "grade",
    ):
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            raise CorroboratedImportError(f"benchmark target {field} is required")
        values[field] = value.strip()
    target = BenchmarkTarget(year=year, **values)
    gcc_listing_id(target.gcc_url)
    return target


def _candidate_from_mapping(raw: object) -> SimpleNamespace:
    if not isinstance(raw, Mapping):
        raise CorroboratedImportError("benchmark candidate must be an object")
    item_id = raw.get("item_id")
    title = raw.get("title")
    date_sold = raw.get("date_sold")
    sale_price_minor = raw.get("sale_price_minor")
    currency = raw.get("currency")
    buying_format = raw.get("buying_format")
    accepted_offer_ambiguous = raw.get("accepted_offer_ambiguous")
    if not isinstance(item_id, str) or _ITEM_ID_RE.fullmatch(item_id) is None:
        raise CorroboratedImportError("candidate item_id is invalid")
    if not isinstance(title, str) or not title.strip():
        raise CorroboratedImportError("candidate title is required")
    if not isinstance(date_sold, str) or _DATE_RE.fullmatch(date_sold) is None:
        raise CorroboratedImportError("candidate date_sold must be YYYY-MM-DD")
    if (
        not isinstance(sale_price_minor, int)
        or isinstance(sale_price_minor, bool)
        or sale_price_minor <= 0
    ):
        raise CorroboratedImportError("candidate sale_price_minor must be positive integer")
    if not isinstance(currency, str) or currency.strip().upper() != "USD":
        raise CorroboratedImportError("phase-1 corroborated importer requires USD")
    if not isinstance(buying_format, str) or not buying_format.strip():
        raise CorroboratedImportError("candidate buying_format is required")
    if not isinstance(accepted_offer_ambiguous, bool):
        raise CorroboratedImportError("candidate accepted_offer_ambiguous must be boolean")
    return SimpleNamespace(
        item_id=item_id,
        title=title.strip(),
        date_sold=date_sold,
        sale_price_minor=sale_price_minor,
        currency="USD",
        buying_format=buying_format.strip(),
        accepted_offer_ambiguous=accepted_offer_ambiguous,
    )


def select_corroborated_item(
    report: Mapping[str, Any],
    corroborations: Mapping[str, CorroborationRecord],
    item_id: str,
) -> tuple[BenchmarkTarget, SimpleNamespace, CorroborationRecord]:
    if report.get("mode") != "READ_ONLY_GCC_EBAY_EXACT_BENCHMARK":
        raise CorroboratedImportError("benchmark report mode is not trusted")
    if report.get("robot_kb_write") is not False or report.get("v4_economic_use") is not False:
        raise CorroboratedImportError("benchmark report safety flags are not fail-closed")
    if _ITEM_ID_RE.fullmatch(item_id) is None:
        raise CorroboratedImportError("requested item id is invalid")
    record = corroborations.get(item_id)
    if record is None:
        raise CorroboratedImportError("requested item has no reviewed corroboration record")

    matches: list[tuple[BenchmarkTarget, SimpleNamespace]] = []
    targets = report.get("targets")
    if not isinstance(targets, list):
        raise CorroboratedImportError("benchmark report targets must be a list")
    for raw_target_result in targets:
        if not isinstance(raw_target_result, Mapping):
            raise CorroboratedImportError("benchmark target result must be an object")
        target = _target_from_mapping(raw_target_result.get("target"))
        reviewed = raw_target_result.get("manual_review")
        if not isinstance(reviewed, list):
            raise CorroboratedImportError("benchmark manual_review must be a list")
        for raw_candidate in reviewed:
            if not isinstance(raw_candidate, Mapping) or raw_candidate.get("item_id") != item_id:
                continue
            candidate = _candidate_from_mapping(raw_candidate)
            classification, _reasons, used = classify_with_corroboration(
                target,
                candidate,
                {item_id: record},
            )
            if classification == "CORROBORATED_SOLD" and used is record:
                matches.append((target, candidate))

    if len(matches) != 1:
        raise CorroboratedImportError(
            f"requested item must resolve to exactly one CORROBORATED_SOLD target; got {len(matches)}"
        )
    target, candidate = matches[0]
    return target, candidate, record


def resolve_gcc_canonical_card(kb: Any, gcc_url: str) -> str:
    listing_id = gcc_listing_id(gcc_url)
    rows = kb.connection.execute(
        """
        SELECT DISTINCT link.canonical_card_id
        FROM external_identifier AS identifier
        JOIN external_object AS object ON object.id = identifier.external_object_id
        JOIN source_system AS source ON source.id = object.source_system_id
        JOIN identifier_link AS link ON link.external_identifier_id = identifier.id
        WHERE source.code = 'gcc'
          AND identifier.namespace = 'GCC_LISTING_ID'
          AND identifier.identifier_value = ?
          AND link.resolution_state = 'PROVEN'
          AND link.canonical_card_id IS NOT NULL
        ORDER BY link.canonical_card_id
        """,
        (listing_id,),
    ).fetchall()
    cards = [row["canonical_card_id"] for row in rows]
    if len(cards) != 1:
        raise CorroboratedImportError(
            f"GCC target must have exactly one PROVEN canonical-card link; got {len(cards)}"
        )
    return cards[0]


def _runtime():
    from robot_kb.domain import (
        Directness,
        EvidenceMethod,
        InclusionState,
        ObservationType,
        ResolutionState,
        SourceKind,
    )
    from robot_kb.repository import PriceComponent
    from robot_kb.sidecar.models import (
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
    )
    from robot_kb.sidecar.persistence import ShadowKnowledgePersistence

    return (
        Directness,
        EvidenceMethod,
        InclusionState,
        ObservationType,
        ResolutionState,
        SourceKind,
        PriceComponent,
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
        ShadowKnowledgePersistence,
    )


def _manual_claim(IdentityClaim: Any, SourceKind: Any, EvidenceMethod: Any, Directness: Any, ResolutionState: Any, field: str, value: object):
    return IdentityClaim(
        field,
        value,
        SourceKind.HUMAN,
        evidence_method=EvidenceMethod.MANUAL,
        directness=Directness.DIRECT_ASSERTION,
        resolution_state=ResolutionState.PROVEN,
    )


def _sale_event_at(date_sold: str) -> str:
    if _DATE_RE.fullmatch(date_sold) is None:
        raise CorroboratedImportError("sale date is not canonical YYYY-MM-DD")
    return f"{date_sold}T00:00:00+00:00"


def _retained_payload(
    target: BenchmarkTarget,
    candidate: SimpleNamespace,
    record: CorroborationRecord,
) -> Mapping[str, Any]:
    return {
        "schema_version": IMPORT_SCHEMA_VERSION,
        "market": "eBay",
        "gcc_target": asdict(target),
        "provider_candidate": {
            "item_id": candidate.item_id,
            "title": candidate.title,
            "date_sold": candidate.date_sold,
            "sale_price_minor": candidate.sale_price_minor,
            "currency": candidate.currency,
            "buying_format": candidate.buying_format,
            "accepted_offer_ambiguous": candidate.accepted_offer_ambiguous,
            "listing_url": f"https://www.ebay.com/itm/{candidate.item_id}",
        },
        "independent_corroboration": asdict(record),
    }


def persist_corroborated_sale(
    kb: Any,
    target: BenchmarkTarget,
    candidate: SimpleNamespace,
    record: CorroborationRecord,
) -> Mapping[str, Any]:
    classification, reasons, used = classify_with_corroboration(
        target,
        candidate,
        {record.item_id: record},
    )
    if classification != "CORROBORATED_SOLD" or used is not record:
        raise CorroboratedImportError(
            "sale failed CORROBORATED_SOLD revalidation: " + "; ".join(reasons)
        )

    canonical_card_id = resolve_gcc_canonical_card(kb, target.gcc_url)
    (
        Directness,
        EvidenceMethod,
        InclusionState,
        ObservationType,
        ResolutionState,
        SourceKind,
        PriceComponent,
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
        ShadowKnowledgePersistence,
    ) = _runtime()

    event_at = _sale_event_at(record.date_sold)
    buying_format = normalized(candidate.buying_format)
    component_type = "HAMMER_PRICE" if "auction" in buying_format else "ITEM_PRICE"
    claims = (
        IdentityClaim("ebay_item_id", candidate.item_id, SourceKind.PROVIDER),
        IdentityClaim("provider_title_raw", candidate.title, SourceKind.PROVIDER),
        IdentityClaim("buying_format", candidate.buying_format, SourceKind.PROVIDER),
        IdentityClaim(
            "listing_url",
            f"https://www.ebay.com/itm/{candidate.item_id}",
            SourceKind.PROVIDER,
        ),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "card_name", record.title),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "set", record.card_set),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "collector_number", record.collector_number),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "language", record.language),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "grader", record.grader),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "grade", record.grade),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "year", record.year),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "microvariant_compatible", True),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "independent_sale_source", record.source),
        _manual_claim(IdentityClaim, SourceKind, EvidenceMethod, Directness, ResolutionState, "independent_sale_url", record.source_url),
    )
    observation = NormalizedObservation(
        observation_type=ObservationType.SALE_TRANSACTION,
        source_native_record_id=candidate.item_id,
        observed_at=record.verified_at,
        fact={
            "listing_started_at": None,
            "sale_occurred_at": event_at,
            "transaction_status": "COMPLETED",
        },
        event_at=event_at,
        event_time_precision="DAY",
        prices=(
            PriceComponent(
                component_type,
                record.sale_price_minor,
                record.currency,
                inclusion_state=InclusionState.UNKNOWN,
            ),
        ),
        identity_subject_type="EBAY_CORROBORATED_SALE",
        identity_subject_label=f"eBay corroborated sale {candidate.item_id}",
        identity_namespace="EBAY_ITEM_ID",
        identity_identifier_value=candidate.item_id,
        unresolved_dimensions=(),
        claims=claims,
        exact_identity_eligible=True,
        genuine_sale_evidence=True,
    )
    raw = RawSourceRecord(
        source_code=SOURCE_CODE,
        source_name=SOURCE_NAME,
        source_role=SOURCE_ROLE,
        source_native_record_id=candidate.item_id,
        payload=_retained_payload(target, candidate, record),
        retrieved_at=record.verified_at,
        object_type="SALE_EVENT",
        external_native_id=candidate.item_id,
    )
    diagnostics = ShadowDiagnostics()

    # Pre-linking EBAY_ITEM_ID to the already-PROVEN GCC canonical card lets the
    # pinned P3 persistence seal the SALE_TRANSACTION with a canonical_card_id.
    # The outer transaction keeps identifier mapping + sale ingestion atomic.
    with kb._transaction():
        source_id = kb.create_source_system(SOURCE_CODE, SOURCE_NAME, SOURCE_ROLE)
        object_id = kb.create_external_object(
            source_id,
            "SALE_EVENT",
            candidate.item_id,
        )
        identifier_id = kb.add_external_identifier(
            object_id,
            "EBAY_ITEM_ID",
            candidate.item_id,
        )
        kb.link_identifier(
            identifier_id,
            ResolutionState.PROVEN,
            canonical_card_id=canonical_card_id,
        )
        ShadowKnowledgePersistence(kb).ingest(raw, (observation,), diagnostics)

    return {
        "canonical_card_id": canonical_card_id,
        "sale_transactions_stored": diagnostics.sale_transactions_stored,
        "duplicate_sale_replays": diagnostics.duplicate_sale_replays,
        "observations_replayed": diagnostics.observations_replayed,
    }


def validate_database_target(kb: Any, target: BenchmarkTarget) -> str:
    return resolve_gcc_canonical_card(kb, target.gcc_url)


def safe_summary(*, mode: str, item_id: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "item_id": item_id,
        "corroborated_sold": False,
        "canonical_card_resolved": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate or manually import one independently corroborated eBay sale"
    )
    parser.add_argument("mode", choices=("validate", "write"))
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--corroboration-file", type=Path, required=True)
    parser.add_argument("--item-id", required=True)
    args = parser.parse_args(argv)

    summary = safe_summary(mode=args.mode, item_id=args.item_id)
    try:
        report = _load_json(args.benchmark_file, "benchmark")
        corroborations = load_corroboration_file(args.corroboration_file)
        target, candidate, record = select_corroborated_item(
            report,
            corroborations,
            args.item_id,
        )
        summary["corroborated_sold"] = True
        database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
        if not database:
            raise CorroboratedImportError("ROBOT_KB_DATABASE_URL is required")

        from robot_kb.repository import KnowledgeBase

        with KnowledgeBase.open(database) as kb:
            card_id = validate_database_target(kb, target)
            summary["canonical_card_resolved"] = True
            summary["canonical_card_id"] = card_id
            if args.mode == "write":
                result = persist_corroborated_sale(kb, target, candidate, record)
                summary.update(result)
                summary["robot_kb_write"] = True
                summary["sale_transaction_stored"] = bool(
                    result["sale_transactions_stored"]
                )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    except (CorroboratedImportError, ValueError) as exc:
        summary["error"] = str(exc)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        # Fail visibly without echoing environment variables, secrets, or raw payloads.
        summary["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
