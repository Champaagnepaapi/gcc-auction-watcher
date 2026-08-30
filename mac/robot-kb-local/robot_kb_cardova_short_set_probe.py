#!/usr/bin/env python3
"""Read-only exact Cardova short-set -> TCGdex coordinate diagnostic.

This diagnostic exists only to distinguish a provider handoff problem from a
real TCGdex catalogue gap for Cardova paid-SOLD evidence.  It never fuzzy
matches or translates a set/card name.

For each already-proven Cardova paid-SOLD record it uses the provider-native
``variety_short`` preserved by the harvest as retrieval-only input:

  exact short set name -> exactly one TCGdex set -> exact set/localId endpoint

The final coordinate is accepted as macro identity only when the existing V4
coordinate validator accepts it.  For Japanese cards, a localized TCGdex card
name may differ from Cardova's romanized display name because exact set + exact
localId already determines the card; no translation is inferred.  Existing
``variants_detailed``/source gates are then consulted separately.

No Robot KB write, SALE_TRANSACTION, V4 economics, notification, purchase, bid,
offer, checkout or payment is possible from this module.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import v4_canonical_multimarket as canonical  # noqa: E402
import v4_global_economic_confirmation as confirmation  # noqa: E402
import v4_tcgdex_generalized_coordinate_recovery as generalized  # noqa: E402
import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
_SET_CACHE: dict[tuple[str, str], tuple[str, str]] = {}


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _language_code(value: object) -> str:
    token = _norm(value).casefold()
    return {"japanese": "ja", "ja": "ja", "jp": "ja", "english": "en", "en": "en"}.get(token, "")


def _exact_set_id(language_code: str, short_set: str) -> tuple[str, str]:
    """Return (set_id, status) for one exact TCGdex set-name lookup."""

    key = (language_code, short_set.casefold())
    if key in _SET_CACHE:
        return _SET_CACHE[key]
    try:
        status, payload, _ = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/{language_code}/sets",
            params={"name": f"eq:{short_set}"},
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        result = ("", f"SET_LOOKUP_EXCEPTION:{type(error).__name__}")
        _SET_CACHE[key] = result
        return result
    if status != 200:
        result = ("", f"SET_LOOKUP_HTTP_{status}")
        _SET_CACHE[key] = result
        return result
    sets = canonical._extract_list_payload(payload)
    if not sets:
        result = ("", "SHORT_SET_NOT_IN_TCGDEX")
        _SET_CACHE[key] = result
        return result
    if len(sets) != 1:
        result = ("", "SHORT_SET_AMBIGUOUS")
        _SET_CACHE[key] = result
        return result
    set_id = _norm(sets[0].get("id"))
    if not set_id:
        result = ("", "SHORT_SET_MALFORMED")
        _SET_CACHE[key] = result
        return result
    result = (set_id, "EXACT_SHORT_SET")
    _SET_CACHE[key] = result
    return result


def probe_record(record: Mapping[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason

    identity = paid_identity.identity_from_record(record)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "IDENTITY_INPUT_INCOMPLETE"

    short_set = _norm(record.get("provider_set_name_short"))
    if not short_set:
        return None, "SHORT_SET_MISSING"
    language_code = _language_code(identity.language)
    if not language_code:
        return None, "LANGUAGE_UNSUPPORTED"

    set_id, set_status = _exact_set_id(language_code, short_set)
    if not set_id:
        return None, set_status

    retrieval_identity = replace(identity, set_name=short_set)
    lot = confirmation._lot_for_identity(retrieval_identity)
    recovered = generalized._fetch_coordinate(
        lot,
        language_code=language_code,
        listing_set=short_set,
        listing_name=identity.name,
        set_id=set_id,
        expected_count=None,
        # Exact set name + exact localId is the identity proof.  This allows the
        # Japanese catalogue name to remain localized without translating it.
        allow_localized_name_mismatch=True,
    )
    if recovered is None:
        return None, "EXACT_SHORT_SET_NO_COORDINATE"
    if recovered.status != "EXACT":
        suffix = f":{_norm(recovered.reason)}" if _norm(recovered.reason) else ""
        return None, f"SHORT_SET_COORDINATE_{recovered.status}{suffix}"
    if _norm(recovered.language_code).casefold() != language_code:
        return None, "SHORT_SET_COORDINATE_LANGUAGE_CONFLICT"

    micro_ok, micro_status, micro_reason, micro_dimensions = paid_identity._microvariant_check(
        identity, recovered
    )
    row = {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "card_name": identity.name,
        "provider_set_name": _norm(record.get("set_name")),
        "provider_set_name_short": short_set,
        "collector_number": identity.number,
        "language": identity.language,
        "grader": identity.grader,
        "grade": identity.grade,
        "certification_number": _norm(record.get("certification_number")),
        "tcgdex_set_id": _norm(recovered.set_id),
        "tcgdex_card_id": _norm(recovered.card_id),
        "tcgdex_local_id": _norm(recovered.local_id),
        "macro_identity_status": "EXACT",
        "macro_identity_reason": _norm(recovered.reason),
        "microvariant_status": micro_status,
        "microvariant_reason": micro_reason,
        "microvariant_dimensions": dict(micro_dimensions),
        "microvariant_exact": bool(micro_ok),
        "exact_card_sale_evidence_ready": bool(micro_ok),
        "sale_transaction_ready": False,
    }
    return row, "EXACT_SHORT_SET_COORDINATE"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_EXACT_SHORT_SET_TCGDEX_PROBE",
        "retrieval_rule": "EXACT_PROVIDER_SHORT_SET_NAME_PLUS_EXACT_LOCALID",
        "fuzzy_matching": False,
        "translation_assumed": False,
        "provider_set_alias_table_used": False,
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


def run(records: Sequence[Mapping[str, Any]], *, max_records: int) -> Mapping[str, Any]:
    _SET_CACHE.clear()
    paid_identity.install_tcgdex_stack_once()
    selected = list(records[:max_records])
    exact: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    macro_exact = 0
    micro_exact = 0
    for record in selected:
        row, reason = probe_record(record)
        if row is None:
            blocked[reason] += 1
            continue
        macro_exact += 1
        if row.get("microvariant_exact") is True:
            micro_exact += 1
        exact.append(row)
    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "unique_short_sets_queried": len(_SET_CACHE),
        "macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": micro_exact,
        "blocked": dict(sorted(blocked.items())),
        "records": exact,
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
    parser = argparse.ArgumentParser(description="Probe exact Cardova short-set TCGdex coordinates")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    summary = safe_summary()
    try:
        summary.update(run(load_records(args.input), max_records=args.max_records))
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
