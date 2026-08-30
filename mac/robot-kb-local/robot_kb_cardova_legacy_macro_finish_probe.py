#!/usr/bin/env python3
"""Read-only finish proof for bounded exact legacy Cardova macro identities.

This diagnostic composes two already-separated evidence surfaces:

1. a Cardova row that the bounded macro probe proved EXACT at card/set/language;
2. Cardova's native variant attributes for the same paid/completed sale.

The exact immutable TCGdex source file already selected by the macro proof is
then re-fetched from the pinned catalogue commit and used only to prove the
normal/holo/reverse finish axis. Provider attributes never choose the TCGdex
coordinate and never prove a premium material variant by themselves.

The preferred local mode reads the canonical loopback Robot KB PostgreSQL in a
READ ONLY transaction, recomputes the bounded macro proof from the same stored
raw records, and reuses provider_attribute* only when those surfaces were
actually preserved in the immutable raw payload. Older rows without those fields
remain usable when the pinned TCGdex coordinate itself has one unique finish.

Even a proven finish is only a partial commercial identity. Edition, special
finish, stamp and other material axes remain unproven here, so this probe never
creates an exact microvariant, canonical link, SALE_TRANSACTION, V4 economic
input, notification or commerce action.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence

import requests


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_bounded_macro_identity_probe as bounded_macro  # noqa: E402
import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402


SOURCE_COMMIT = "af33c9ac882e2acfadffaf19e8083aa976d12983"
SOURCE_RAW_BASE = f"https://raw.githubusercontent.com/tcgdex/cards-database/{SOURCE_COMMIT}"
DEFAULT_MAX_RECORDS = 50
HARD_MAX_RECORDS = 100
DEFAULT_MAX_GROUPS = 20
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_TIMEOUT_SECONDS = 4.0
_ALLOWED_FINISHES = ("normal", "holo", "reverse")
_SAFE_SOURCE_PATH = re.compile(
    r"^data-asia/[A-Za-z0-9._-]+/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)\.ts$"
)


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _same_local_id(first: object, second: object) -> bool:
    left = _norm(first).lstrip("#")
    right = _norm(second).lstrip("#")
    if not left or not right:
        return False
    if left.isdigit() and right.isdigit():
        return int(left) == int(right)
    return left.casefold() == right.casefold()


def _source_coordinate_ok(row: Mapping[str, Any]) -> bool:
    path = _norm(row.get("pinned_source_path"))
    match = _SAFE_SOURCE_PATH.fullmatch(path)
    if match is None:
        return False
    set_id, file_local_id = match.groups()
    if set_id != _norm(row.get("tcgdex_set_id")):
        return False
    return _same_local_id(file_local_id, row.get("tcgdex_local_id"))


def _extract_variants_block(text: str) -> str:
    match = re.search(r"\bvariants\s*:\s*\[", text)
    if match is None:
        return ""
    start = text.find("[", match.start())
    if start < 0:
        return ""

    depth = 0
    quote = ""
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in {"'", '"', "`"}:
            quote = char
            continue
        if char == "[":
            depth += 1
            continue
        if char == "]":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return ""


def source_finish_choices(text: str, *, set_id: str) -> tuple[str, ...]:
    """Parse only simple normal/holo/reverse variants from one pinned card file."""

    if not text or len(text) > 250_000:
        return ()
    set_import = re.compile(
        rf"^\s*import\s+Set\s+from\s+['\"]\.\./{re.escape(set_id)}['\"]\s*;?\s*$",
        flags=re.MULTILINE,
    )
    if set_import.search(text) is None:
        return ()

    block = _extract_variants_block(text)
    if not block:
        return ()
    observed = [
        value.strip().casefold()
        for value in re.findall(r"\btype\s*:\s*['\"]([^'\"]+)['\"]", block)
    ]
    if not observed or any(value not in _ALLOWED_FINISHES for value in observed):
        return ()
    return tuple(value for value in _ALLOWED_FINISHES if value in observed)


def provider_finish_state(row: Mapping[str, Any]) -> tuple[str, str, tuple[str, ...]]:
    """Recognize only an exact, standalone Cardova Holo claim.

    Other non-empty material tokens are deliberately opaque. This mirrors the
    earlier JP-promo probe's conservative semantics and avoids interpreting
    abbreviations such as FA/SR or compounds such as Holo Shiny.
    """

    values = tuple(
        _norm(row.get(key))
        for key in ("provider_attribute", "provider_attribute2", "provider_attribute3")
        if _norm(row.get(key))
    )
    if not values:
        return "ABSENT", "", ()
    if len(values) == 1 and values[0].casefold() == "holo":
        return "EXPLICIT_HOLO_ONLY", "holo", ()
    return "OPAQUE_MATERIAL", "", tuple(value.casefold() for value in values)


def _same_sale_identity(macro: Mapping[str, Any], variant: Mapping[str, Any]) -> bool:
    return all(
        (
            _norm(macro.get(macro_key)).casefold()
            == _norm(variant.get(variant_key)).casefold()
        )
        for macro_key, variant_key in (
            ("source_native_record_id", "source_native_record_id"),
            ("card_name_provider_claim", "card_name"),
            ("collector_number_provider_claim", "collector_number"),
            ("grader", "grader"),
            ("grade", "grade"),
        )
    )


def _default_source_fetcher(path: str, *, timeout_seconds: float) -> str:
    response = requests.get(f"{SOURCE_RAW_BASE}/{path}", timeout=timeout_seconds)
    if response.status_code != 200:
        return ""
    return response.text


def _cached_network_fetcher(timeout_seconds: float) -> Callable[[str], str]:
    cache: dict[str, str] = {}

    def fetch(path: str) -> str:
        if path not in cache:
            cache[path] = _default_source_fetcher(path, timeout_seconds=timeout_seconds)
        return cache[path]

    return fetch


def reconcile_record(
    macro: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    source_fetcher: Callable[[str], str],
) -> tuple[Optional[dict[str, Any]], str]:
    if (
        macro.get("macro_identity_exact") is not True
        or _norm(macro.get("macro_identity_status")) != "EXACT"
        or macro.get("microvariant_exact") is not False
        or macro.get("exact_identity_link_candidate") is not False
    ):
        return None, "MACRO_IDENTITY_NOT_EXACT_BOUNDED"
    if not _same_sale_identity(macro, variant):
        return None, "INPUT_IDENTITY_CONFLICT"
    if _norm(macro.get("pinned_source_commit")) != SOURCE_COMMIT:
        return None, "PINNED_SOURCE_COMMIT_CONFLICT"
    if not _source_coordinate_ok(macro):
        return None, "PINNED_SOURCE_COORDINATE_CONFLICT"

    path = _norm(macro.get("pinned_source_path"))
    set_id = _norm(macro.get("tcgdex_set_id"))
    try:
        source_text = source_fetcher(path)
    except Exception:
        source_text = ""
    source_finishes = source_finish_choices(source_text, set_id=set_id)
    if not source_finishes:
        return None, "PINNED_SOURCE_FINISH_UNAVAILABLE"

    provider_state, provider_finish, opaque_tokens = provider_finish_state(variant)
    finish_exact = False
    exact_finish = ""
    reason = ""

    if opaque_tokens:
        reason = "PROVIDER_MATERIAL_TOKEN_UNCORROBORATED"
    elif provider_finish:
        if provider_finish not in source_finishes:
            reason = "PROVIDER_FINISH_SOURCE_CONFLICT"
        else:
            finish_exact = True
            exact_finish = provider_finish
            reason = "FINISH_EXACT_PROVIDER_SOURCE_CORROBORATED"
    elif len(source_finishes) == 1:
        finish_exact = True
        exact_finish = source_finishes[0]
        reason = "FINISH_EXACT_UNIQUE_PINNED_SOURCE"
    else:
        reason = "PINNED_SOURCE_FINISH_AMBIGUOUS"

    out = {
        "source_native_record_id": _norm(macro.get("source_native_record_id")),
        "card_name_provider_claim": _norm(macro.get("card_name_provider_claim")),
        "collector_number_provider_claim": _norm(macro.get("collector_number_provider_claim")),
        "provider_set_label": _norm(macro.get("provider_set_label")),
        "grader": _norm(macro.get("grader")),
        "grade": _norm(macro.get("grade")),
        "tcgdex_card_id": _norm(macro.get("tcgdex_card_id")),
        "tcgdex_set_id": set_id,
        "tcgdex_local_id": _norm(macro.get("tcgdex_local_id")),
        "pinned_source_path": path,
        "pinned_source_commit": SOURCE_COMMIT,
        "source_finish_choices": list(source_finishes),
        "provider_finish_state": provider_state,
        "provider_finish_claim": provider_finish,
        "provider_opaque_material_tokens": list(opaque_tokens),
        "finish_exact": finish_exact,
        "finish": exact_finish,
        "finish_proof_reason": reason,
        "commercial_axes_proven": {"finish": exact_finish} if finish_exact else {},
        "remaining_unproven_axes": [
            "edition_applicability",
            "special_finish_applicability",
            "variant_applicability",
        ],
        "macro_identity_exact": True,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
        "exact_card_sale_evidence_ready": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
    }
    return out, reason


def run_records(
    macro_records: Sequence[Mapping[str, Any]],
    variant_records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    source_fetcher: Callable[[str], str],
) -> Mapping[str, Any]:
    variants_by_id: dict[str, list[Mapping[str, Any]]] = {}
    for row in variant_records:
        key = _norm(row.get("source_native_record_id"))
        if key:
            variants_by_id.setdefault(key, []).append(row)

    records: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    joined = 0

    for macro in macro_records:
        if len(records) >= max_records:
            break
        key = _norm(macro.get("source_native_record_id"))
        candidates = variants_by_id.get(key, [])
        if len(candidates) != 1:
            blocked["VARIANT_SURFACE_JOIN_NOT_UNIQUE"] += 1
            continue
        joined += 1
        row, reason = reconcile_record(macro, candidates[0], source_fetcher=source_fetcher)
        if row is None:
            blocked[reason] += 1
            continue
        records.append(row)
        reasons[reason] += 1

    return {
        "macro_records_seen": len(macro_records),
        "variant_records_seen": len(variant_records),
        "joined_records": joined,
        "records_emitted": len(records),
        "finish_exact_count": sum(1 for row in records if row["finish_exact"]),
        "microvariant_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "reasons": dict(sorted(reasons.items())),
        "blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def _stored_variant_rows(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Project only immutable stored surfaces needed for strict row joining."""

    projected: list[Mapping[str, Any]] = []
    for row in records:
        projected.append(
            {
                "source_native_record_id": _norm(row.get("source_native_record_id")),
                "card_name": _norm(row.get("card_name")),
                "collector_number": _norm(row.get("collector_number")),
                "grader": _norm(row.get("grader")),
                "grade": _norm(row.get("grade")),
                "provider_attribute": _norm(
                    row.get("provider_attribute") or row.get("attribute")
                ),
                "provider_attribute2": _norm(
                    row.get("provider_attribute2") or row.get("attribute2")
                ),
                "provider_attribute3": _norm(
                    row.get("provider_attribute3") or row.get("attribute3")
                ),
            }
        )
    return projected


def run_database(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    source_fetcher: Callable[[str], str],
) -> Mapping[str, Any]:
    """Recompute bounded macro proof and finish proof from one read-only DB snapshot."""

    target = recovery.validate_local_database_url(database_url)
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    stored_records = selected.get("records", [])
    if not isinstance(stored_records, list):
        raise RuntimeError("Robot KB unresolved records payload is malformed")
    clean_records = [row for row in stored_records if isinstance(row, Mapping)]

    registry_payload = bounded_macro.registry.run_records(
        clean_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
    )
    macro_payload = bounded_macro.compose_registry_result(registry_payload)
    macro_records = macro_payload.get("records", [])
    if not isinstance(macro_records, list):
        raise RuntimeError("bounded macro records payload is malformed")

    finish = run_records(
        [row for row in macro_records if isinstance(row, Mapping)],
        _stored_variant_rows(clean_records),
        max_records=max_records,
        source_fetcher=source_fetcher,
    )
    out: dict[str, Any] = {}
    out.update(target)
    out.update(
        {
            "unresolved_sale_transactions_available": selected.get(
                "unresolved_sale_transactions_available", 0
            ),
            "selected_records": selected.get("selected_records", len(clean_records)),
            "db_read_blocked": selected.get("db_read_blocked", {}),
            "macro_identity_exact_count": macro_payload.get("macro_identity_exact_count", 0),
            "macro_blocked": macro_payload.get("blocked", {}),
        }
    )
    out.update(finish)
    return out


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_LEGACY_MACRO_FINISH_PROOF",
        "database_read_only_transaction": True,
        "source_commit": SOURCE_COMMIT,
        "provider_attribute_is_identity_proof_alone": False,
        "source_coordinate_selected_by_provider_attribute": False,
        "finish_exact_is_partial_identity_only": True,
        "microvariant_exact": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def _records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = payload.get("records")
    if not isinstance(value, list):
        raise ValueError("input payload has no records list")
    return [row for row in value if isinstance(row, Mapping)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Prove Cardova legacy finish axes read-only")
    parser.add_argument("--database-url")
    parser.add_argument("--macro-input", type=Path)
    parser.add_argument("--variant-input", type=Path)
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

    database_mode = bool(_norm(args.database_url))
    file_mode = args.macro_input is not None or args.variant_input is not None
    if database_mode and file_mode:
        parser.error("use --database-url OR --macro-input + --variant-input, not both")
    if not database_mode and not (
        args.macro_input is not None and args.variant_input is not None
    ):
        parser.error("provide --database-url or both --macro-input and --variant-input")

    try:
        fetcher = _cached_network_fetcher(args.timeout_seconds)
        payload = dict(safe_summary())
        if database_mode:
            payload.update(
                run_database(
                    _norm(args.database_url),
                    max_records=args.max_records,
                    max_groups=args.max_groups,
                    min_distinct_dexids=args.min_distinct_dexids,
                    source_fetcher=fetcher,
                )
            )
        else:
            assert args.macro_input is not None and args.variant_input is not None
            macro_payload = json.loads(args.macro_input.read_text())
            variant_payload = json.loads(args.variant_input.read_text())
            if not isinstance(macro_payload, Mapping) or not isinstance(variant_payload, Mapping):
                raise ValueError("input JSON root must be an object")
            payload.update(
                run_records(
                    _records(macro_payload),
                    _records(variant_payload),
                    max_records=args.max_records,
                    source_fetcher=fetcher,
                )
            )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload = dict(safe_summary())
        payload["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
