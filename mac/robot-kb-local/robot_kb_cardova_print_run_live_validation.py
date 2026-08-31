#!/usr/bin/env python3
"""Read-only live validation for Cardova exact SOLD persistence with P3 print_run.

This validator composes only already-reviewed surfaces from the stacked Cardova
work and persists canonical cards / exact sales only in an in-memory Robot KB.
The local PostgreSQL database is opened through the existing READ ONLY recovery
transaction; no schema migration or durable write is performed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402
import robot_kb_cardova_legacy_macro_finish_probe as finish_probe  # noqa: E402
import robot_kb_cardova_no_rarity_reviewed_fallback as no_rarity  # noqa: E402
import robot_kb_cardova_public_title_printing_proof as title_proof  # noqa: E402
import robot_kb_cardova_reviewed_rarity_symbol_proof as image_proof  # noqa: E402
import robot_kb_cardova_rarity_symbol_microvariant_closure as closure  # noqa: E402
import robot_kb_cardova_print_run_exact_sale_dry_run as persistence  # noqa: E402


DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_TIMEOUT_SECONDS = 4.0

# Reviewed public-title evidence from PR #204. These literals are intentionally
# source-id + certificate bound; they are not inferred from provider silence.
PUBLIC_TITLE_EVIDENCE: Mapping[str, Mapping[str, str]] = {
    "01KFFRJ8B4X9FG8YK90K4BNS1T": {
        "cert": "141683514",
        "title": "1996 Ninetales PSA 10 Holo No Rarity Original Print - Cardova Japan",
    },
    "01KQHACBX20NBMGD9VZAPA6Z64": {
        "cert": "156405344",
        "title": (
            "1996 Charizard PSA 8 Holo No Rarity Original Print "
            "Error(Strength) - Cardova Japan"
        ),
    },
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _sale_by_id(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for row in records:
        source_id = _norm(row.get("source_native_record_id"))
        if not source_id:
            continue
        if source_id in output:
            raise RuntimeError(f"duplicate Cardova source id in read-only snapshot: {source_id}")
        output[source_id] = row
    return output


def _apply_title_proof(
    rows: Sequence[Mapping[str, Any]],
    sales: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    output: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for raw in rows:
        row = dict(raw)
        source_id = _norm(row.get("source_native_record_id"))
        evidence = PUBLIC_TITLE_EVIDENCE.get(source_id)
        if evidence is None or row.get("printing_exact") is True:
            output.append(row)
            continue
        sale = sales.get(source_id)
        if sale is None:
            reasons["PUBLIC_TITLE_SALE_JOIN_MISSING"] += 1
            output.append(row)
            continue
        if _norm(sale.get("certification_number")) != evidence["cert"]:
            reasons["PUBLIC_TITLE_CERT_CONFLICT"] += 1
            output.append(row)
            continue
        page_url = _norm(sale.get("source_url"))
        proven, reason = title_proof.prove_title(
            row,
            page_url=page_url,
            page_title=evidence["title"],
        )
        reasons[reason] += 1
        output.append(dict(proven) if proven is not None else row)
    return output, reasons


def _apply_reviewed_image_proof(
    rows: Sequence[Mapping[str, Any]],
    sales: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    output: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    for raw in rows:
        row = dict(raw)
        source_id = _norm(row.get("source_native_record_id"))
        evidence = image_proof.REVIEWED_RARITY_SYMBOL_EVIDENCE.get(source_id)
        if evidence is None:
            output.append(row)
            continue
        sale = sales.get(source_id)
        if sale is None:
            reasons["REVIEWED_IMAGE_SALE_JOIN_MISSING"] += 1
            output.append(row)
            continue
        cert = _norm(sale.get("certification_number"))
        proven, reason = image_proof.apply_reviewed_front_image_proof(
            row,
            certificate_number=cert,
            image_a=evidence["image_a"],
            image_sha256=evidence["image_sha256"],
        )
        reasons[reason] += 1
        output.append(dict(proven) if proven is not None else row)
    return output, reasons


def compose_exact_identity_rows(
    sales: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    """Recreate the corrected #206 identity chain from one immutable DB snapshot."""

    source = finish_probe._cached_network_fetcher(timeout_seconds)
    registry_payload = finish_probe.bounded_macro.registry.run_records(
        sales,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
    )
    macro_payload = finish_probe.bounded_macro.compose_registry_result(registry_payload)
    macro_rows = [
        row
        for row in macro_payload.get("records", [])
        if isinstance(row, Mapping)
    ]
    finish_payload = finish_probe.run_records(
        macro_rows,
        finish_probe._stored_variant_rows(sales),
        max_records=max_records,
        source_fetcher=source,
    )

    reviewed_input = dict(finish_payload)
    reviewed_input["blocked"] = {}
    reviewed = no_rarity.apply_reviewed_fallback(reviewed_input)
    reviewed_rows = [
        row for row in reviewed.get("records", []) if isinstance(row, Mapping)
    ]

    sales_by_id = _sale_by_id(sales)
    titled_rows, title_reasons = _apply_title_proof(reviewed_rows, sales_by_id)
    evidenced_rows, image_reasons = _apply_reviewed_image_proof(titled_rows, sales_by_id)

    exact_rows: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    closed_reasons: Counter[str] = Counter()
    for row in evidenced_rows:
        # The reviewed public title proves the material Error(Strength) tail and
        # therefore must stay blocked rather than being reduced to plain No Rarity.
        if _norm(row.get("cardova_public_material_tail")):
            blocked["CARDOVA_PUBLIC_TITLE_MATERIAL_TAIL_UNRESOLVED"] += 1
            continue
        closed, reason = closure.close_record(row, source_fetcher=source)
        if closed is None:
            blocked[reason] += 1
            continue
        exact_rows.append(closed)
        closed_reasons[reason] += 1

    return {
        "macro_identity_exact_count": int(macro_payload.get("macro_identity_exact_count", 0)),
        "finish_rows": len(reviewed_rows),
        "reviewed_no_rarity_rows_proven": int(reviewed.get("reviewed_no_rarity_rows_proven", 0)),
        "title_reasons": dict(sorted(title_reasons.items())),
        "reviewed_image_reasons": dict(sorted(image_reasons.items())),
        "exact_identity_rows": len(exact_rows),
        "identity_blocked_count": sum(blocked.values()),
        "identity_blocked": dict(sorted(blocked.items())),
        "identity_reasons": dict(sorted(closed_reasons.items())),
        "records": exact_rows,
    }


def run_live_validation(
    database_url: str,
    *,
    max_records: int = DEFAULT_MAX_RECORDS,
    max_groups: int = DEFAULT_MAX_GROUPS,
    min_distinct_dexids: int = DEFAULT_MIN_DISTINCT_DEXIDS,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    observed_at: Optional[str] = None,
) -> Mapping[str, Any]:
    target = recovery.validate_local_database_url(database_url)
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    sales = [row for row in selected.get("records", []) if isinstance(row, Mapping)]
    identity = compose_exact_identity_rows(
        sales,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
    )
    result = persistence.run_memory_dry_run(
        sales,
        identity["records"],
        observed_at=observed_at or datetime.now(timezone.utc).isoformat(),
        replay=True,
    )
    return {
        **target,
        "database_read_only_transaction": True,
        "unresolved_cardova_sales_available": int(
            selected.get("unresolved_sale_transactions_available", 0)
        ),
        "selected_sales": len(sales),
        "db_read_blocked": dict(selected.get("db_read_blocked") or {}),
        **{key: value for key, value in identity.items() if key != "records"},
        **result,
    }


def safe_summary() -> Mapping[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PRINT_RUN_LIVE_VALIDATION",
        "database_read_only_transaction": True,
        "p3_runtime_required": "38288a950db8285bcbf279d91354f8a1ad3a8c2f",
        "reviewed_public_title_evidence_reused": True,
        "reviewed_front_image_sha_manifest_reused": True,
        "canonical_persistence_database": ":memory:",
        "durable_robot_kb_write": False,
        "local_postgres_write": False,
        "canonical_link_written_durably": False,
        "sale_transaction_written_durably": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only live Cardova exact-sale validation with rarity-symbol print_run"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument("--min-distinct-dexids", type=int, default=DEFAULT_MIN_DISTINCT_DEXIDS)
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.max_groups <= 50:
        parser.error("--max-groups must be between 1 and 50")
    if not 2 <= args.min_distinct_dexids <= 20:
        parser.error("--min-distinct-dexids must be between 2 and 20")
    if not 0.5 <= args.timeout_seconds <= 10.0:
        parser.error("--timeout-seconds must be between 0.5 and 10")

    payload = dict(safe_summary())
    code = 1
    try:
        payload.update(
            run_live_validation(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
                timeout_seconds=args.timeout_seconds,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
