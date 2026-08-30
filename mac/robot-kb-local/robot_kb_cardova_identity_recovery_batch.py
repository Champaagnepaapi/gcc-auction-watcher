#!/usr/bin/env python3
"""Read-only identity recovery batch for durable Cardova paid/completed SOLD rows.

The durable Cardova collector intentionally stores genuine SALE_TRANSACTION facts
before canonical identity is proven.  This diagnostic reads those unresolved
sales back from the local Robot KB, reconstructs their immutable source payloads,
and reuses already-validated identity machinery:

1. the existing V4 exact TCGdex stack and detailed-variant gate;
2. only if TCGdex macro identity is still unresolved, the existing official
   Pokemon Japan exact printed-coordinate fallback for structurally valid JP
   promo coordinates such as ``294/XY-P``.

No canonical link is written.  Macro identity and complete commercial
microvariant remain separate.  Provider failures are reported, never converted
into clean no-match evidence.  The PostgreSQL session is explicitly READ ONLY.
No V4 economic use, notification, purchase, bid, offer, checkout or payment is
possible from this module.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402
import robot_kb_cardova_pokemon_jp_official_probe as official_probe  # noqa: E402
import robot_kb_cardova_number_namespace_probe as namespace_probe  # noqa: E402
import v4_global_economic_confirmation as confirmation  # noqa: E402


DEFAULT_MAX_RECORDS = 50
HARD_MAX_RECORDS = 200
EXPECTED_DATABASE_NAME = "robot_pokemon_kb"
LOCAL_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
SOURCE_CODE = "cardova"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def validate_local_database_url(database_url: str) -> Mapping[str, Any]:
    raw = str(database_url or "").strip()
    if not raw:
        raise ValueError("ROBOT_KB_DATABASE_URL is required")
    parsed = urlsplit(raw)
    if parsed.scheme.casefold() not in {"postgres", "postgresql"}:
        raise ValueError("Cardova identity recovery requires PostgreSQL")
    host = (parsed.hostname or "").casefold()
    if host not in LOCAL_DATABASE_HOSTS:
        raise ValueError("remote/cloud Robot KB access is forbidden for this recovery")
    database_name = parsed.path.lstrip("/").split("/", 1)[0]
    if database_name != EXPECTED_DATABASE_NAME:
        raise ValueError(f"database must be exactly {EXPECTED_DATABASE_NAME!r}")
    return {
        "database_scope": "LOCAL_MAC_POSTGRES_READ_ONLY",
        "database_host_class": "LOOPBACK",
        "database_name": EXPECTED_DATABASE_NAME,
        "database_port": parsed.port,
    }


def _read_unresolved_from_kb(database_url: str, *, max_records: int) -> Mapping[str, Any]:
    """Read unresolved Cardova sales and immutable payloads in one READ ONLY tx."""

    from robot_kb.postgres import connect_postgres  # imported only on pinned P3 runtime
    from robot_kb.repository import KnowledgeBase

    connection = connect_postgres(database_url)
    records: list[Mapping[str, Any]] = []
    blocked: Counter[str] = Counter()
    available = 0
    try:
        connection.execute("BEGIN READ ONLY")
        read_only = connection.execute("SHOW transaction_read_only").fetchone()
        if read_only is None or str(read_only["transaction_read_only"]).casefold() not in {"on", "true"}:
            raise RuntimeError("PostgreSQL transaction is not read-only")
        kb = KnowledgeBase(connection)
        available = int(
            connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM market_observation AS observation
                JOIN source_system AS source ON source.id = observation.source_system_id
                WHERE source.code = ?
                  AND observation.observation_type = 'SALE_TRANSACTION'
                  AND observation.lifecycle_state = 'SEALED'
                  AND observation.canonical_card_id IS NULL
                """,
                (SOURCE_CODE,),
            ).fetchone()["n"]
        )
        rows = connection.execute(
            """
            SELECT observation.id,
                   observation.source_native_record_id,
                   observation.source_record_id,
                   observation.event_at,
                   observation.observed_at
            FROM market_observation AS observation
            JOIN source_system AS source ON source.id = observation.source_system_id
            WHERE source.code = ?
              AND observation.observation_type = 'SALE_TRANSACTION'
              AND observation.lifecycle_state = 'SEALED'
              AND observation.canonical_card_id IS NULL
            ORDER BY observation.event_at DESC, observation.id DESC
            LIMIT ?
            """,
            (SOURCE_CODE, int(max_records)),
        ).fetchall()
        seen_native: set[str] = set()
        for row in rows:
            native_id = _norm(row["source_native_record_id"])
            if not native_id or native_id in seen_native:
                blocked["DUPLICATE_OR_MISSING_NATIVE_ID"] += 1
                continue
            seen_native.add(native_id)
            source_record_id = _norm(row["source_record_id"])
            if not source_record_id:
                blocked["SOURCE_RECORD_ID_MISSING"] += 1
                continue
            payload = kb.raw_source_payload(source_record_id)
            if not isinstance(payload, Mapping):
                blocked["SOURCE_PAYLOAD_NOT_OBJECT"] += 1
                continue
            record = dict(payload)
            if _norm(record.get("source_native_record_id")) != native_id:
                blocked["SOURCE_PAYLOAD_NATIVE_ID_CONFLICT"] += 1
                continue
            eligible, reason = paid_identity._eligible_record(record)
            if not eligible:
                blocked[f"STORED_PAYLOAD_{reason}"] += 1
                continue
            record["_kb_observation_id"] = _norm(row["id"])
            record["_kb_source_record_id"] = source_record_id
            record["_kb_event_at"] = _norm(row["event_at"])
            records.append(record)
        connection.execute("ROLLBACK")
    except Exception:
        if getattr(connection, "in_transaction", False):
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()

    return {
        "unresolved_sale_transactions_available": available,
        "selected_records": len(records),
        "db_read_blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def _language_code(identity: Any) -> str:
    token = _norm(getattr(identity, "language", "")).casefold()
    return {"japanese": "ja", "ja": "ja", "jp": "ja", "english": "en", "en": "en"}.get(token, "")


def _tcgdex_recovery(
    record: Mapping[str, Any],
    *,
    resolver: Callable[[Any], tuple[Any, Any]],
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]],
) -> tuple[Optional[dict[str, Any]], str, bool]:
    """Return (row, reason, macro_exact). One resolver call maximum per record."""

    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason, False
    identity = paid_identity.identity_from_record(record)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "IDENTITY_INPUT_INCOMPLETE", False
    try:
        _lot, canonical = resolver(identity)
    except Exception as error:
        return None, f"TCGDEX_EXCEPTION:{type(error).__name__}", False

    status = _norm(getattr(canonical, "status", "")) or "UNRESOLVED"
    canonical_reason = _norm(getattr(canonical, "reason", ""))
    if status != "EXACT":
        suffix = f":{canonical_reason}" if canonical_reason else ""
        return None, f"TCGDEX_{status}{suffix}", False

    expected_language = _language_code(identity)
    if not expected_language:
        return None, "LANGUAGE_UNSUPPORTED", False
    if _norm(getattr(canonical, "language_code", "")).casefold() != expected_language:
        return None, "TCGDEX_LANGUAGE_CONFLICT", False

    micro_ok, micro_status, micro_reason, dimensions = microvariant_checker(identity, canonical)
    row = {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "card_name": identity.name,
        "collector_number": identity.number,
        "language": identity.language,
        "grader": identity.grader,
        "grade": identity.grade,
        "recovery_source": "TCGDEX",
        "macro_identity_status": "EXACT",
        "macro_identity_reason": canonical_reason,
        "tcgdex_card_id": _norm(getattr(canonical, "card_id", "")),
        "tcgdex_set_name": _norm(getattr(canonical, "set_name", "")),
        "microvariant_status": micro_status,
        "microvariant_reason": micro_reason,
        "microvariant_dimensions": dict(dimensions),
        "microvariant_exact": bool(micro_ok),
        "exact_identity_link_candidate": bool(micro_ok),
    }
    if micro_ok:
        return row, "TCGDEX_EXACT_IDENTITY_AND_MICROVARIANT", True
    suffix = f":{micro_reason}" if micro_reason else ""
    return row, f"TCGDEX_MACRO_EXACT_MICROVARIANT_{micro_status}{suffix}", True


def _official_fallback_eligible(record: Mapping[str, Any]) -> bool:
    identity = paid_identity.identity_from_record(record)
    if _language_code(identity) != "ja":
        return False
    _local_id, namespace, _status = namespace_probe.printed_number_namespace(identity.number)
    if not namespace:
        return False
    official_code, _reason = official_probe.official_set_code(namespace)
    return bool(official_code)


def recover_records(
    records: Sequence[Mapping[str, Any]],
    *,
    resolver: Callable[[Any], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
    official_catalog: Optional[official_probe.OfficialPokemonJpCatalog] = None,
    stack_installer: Callable[[], None] = paid_identity.install_tcgdex_stack_once,
) -> Mapping[str, Any]:
    stack_installer()
    catalog = official_catalog or official_probe.OfficialPokemonJpCatalog()
    output: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    tcgdex_macro_exact = 0
    tcgdex_micro_exact = 0
    official_candidates = 0
    official_macro_exact = 0

    for record in records:
        tcgdex_row, tcgdex_reason, macro_exact = _tcgdex_recovery(
            record,
            resolver=resolver,
            microvariant_checker=microvariant_checker,
        )
        if macro_exact:
            tcgdex_macro_exact += 1
            if tcgdex_row is not None and tcgdex_row.get("microvariant_exact") is True:
                tcgdex_micro_exact += 1
            else:
                blocked[tcgdex_reason] += 1
            if tcgdex_row is not None:
                output.append(tcgdex_row)
            continue

        # TCGdex failure stays visible even when an independent official source
        # can still prove macro identity.
        if not _official_fallback_eligible(record):
            blocked[tcgdex_reason] += 1
            continue
        official_candidates += 1
        official_row, official_reason = official_probe.probe_record(record, catalog=catalog)
        if official_row is None:
            blocked[tcgdex_reason] += 1
            blocked[f"OFFICIAL_FALLBACK:{official_reason}"] += 1
            continue
        official_macro_exact += 1
        row = dict(official_row)
        row["recovery_source"] = "POKEMON_JP_OFFICIAL"
        row["tcgdex_prior_status"] = tcgdex_reason
        row["exact_identity_link_candidate"] = False
        output.append(row)
        blocked["OFFICIAL_MACRO_EXACT_MICROVARIANT_UNRESOLVED"] += 1

    return {
        "records_attempted": len(records),
        "tcgdex_macro_identity_exact_count": tcgdex_macro_exact,
        "tcgdex_exact_microvariant_count": tcgdex_micro_exact,
        "official_jp_fallback_candidate_count": official_candidates,
        "official_jp_macro_identity_exact_count": official_macro_exact,
        "macro_identity_exact_total": tcgdex_macro_exact + official_macro_exact,
        "exact_identity_link_candidate_count": tcgdex_micro_exact,
        "still_unresolved_count": len(records) - tcgdex_micro_exact,
        "blocked": dict(sorted(blocked.items())),
        "records": output,
        "official_result_requests": int(getattr(catalog, "result_requests", 0)),
        "official_detail_requests": int(getattr(catalog, "detail_requests", 0)),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_LOCAL_CARDOVA_SOLD_IDENTITY_RECOVERY_BATCH",
        "database_read_only_transaction": True,
        "local_postgres_only": True,
        "remote_cloud_access_allowed": False,
        "identity_recovery_order": ["TCGDEX_EXACT", "POKEMON_JP_OFFICIAL_STRUCTURAL_PROMO_FALLBACK"],
        "new_identity_resolver_created": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "provider_variant_claim_as_exact_identity": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run(database_url: str, *, max_records: int, official_delay_seconds: float) -> Mapping[str, Any]:
    target = validate_local_database_url(database_url)
    selected = _read_unresolved_from_kb(database_url, max_records=max_records)
    catalog = official_probe.OfficialPokemonJpCatalog(delay_seconds=official_delay_seconds)
    recovered = recover_records(selected["records"], official_catalog=catalog)
    return {**target, **{k: v for k, v in selected.items() if k != "records"}, **recovered}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only recovery of unresolved Cardova SOLD identities")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--official-delay-seconds", type=float, default=0.35)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 0 <= args.official_delay_seconds <= official_probe.HARD_MAX_DELAY_SECONDS:
        parser.error("--official-delay-seconds out of bounds")

    summary = safe_summary()
    code = 1
    try:
        summary.update(
            run(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                max_records=args.max_records,
                official_delay_seconds=args.official_delay_seconds,
            )
        )
        summary["error"] = None
        code = 0
    except Exception as error:
        summary["error"] = f"{type(error).__name__}: {error}"
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
