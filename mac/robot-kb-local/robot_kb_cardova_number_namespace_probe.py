#!/usr/bin/env python3
"""Read-only Cardova printed-number namespace -> exact TCGdex coordinate probe.

Cardova paid-SOLD rows expose printed references such as ``294/XY-P`` where the
right-hand token can itself be an official Pokemon set namespace.  This probe
uses that token only as a literal TCGdex set-id candidate; it never translates,
fuzzy-matches or consults a Cardova->TCGdex alias table.

Required chain:

  proven Cardova paid-SOLD row
    -> structurally valid non-numeric printed-number suffix
    -> literal suffix used as TCGdex set id
    -> exact TCGdex set/localId endpoint
    -> exact returned language + coordinate
    -> existing variants_detailed microvariant gate

A numeric denominator such as ``102/100`` is never treated as a set id.  A
suffix that does not exist as the literal TCGdex set id simply remains blocked.
Even exact identity remains ``sale_transaction_ready=false`` because Cardova's
public payload does not prove the payment-completion timestamp or all-in total.
No Robot KB write, V4 economic use, notification, purchase, bid, offer,
checkout or payment is possible here.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import v4_global_economic_confirmation as confirmation  # noqa: E402
import v4_tcgdex_generalized_coordinate_recovery as generalized  # noqa: E402
import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,23}$")
_LOCAL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,23}$")


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _language_code(value: object) -> str:
    token = _norm(value).casefold()
    return {
        "japanese": "ja",
        "ja": "ja",
        "jp": "ja",
        "english": "en",
        "en": "en",
    }.get(token, "")


def printed_number_namespace(value: object) -> tuple[str, str, str]:
    """Return (local_id, literal_set_id_candidate, status).

    Only one slash is accepted.  The suffix must contain at least one letter so
    ordinary numeric denominators cannot be promoted to set namespaces.  Any
    internal whitespace is rejected rather than normalized away: a provider
    value like ``XY P`` must never be fabricated into ``XYP``.
    """

    raw = str(value or "").strip().lstrip("#")
    if not raw:
        return "", "", "NUMBER_MISSING"
    if any(ch.isspace() for ch in raw):
        return "", "", "NUMBER_NAMESPACE_MALFORMED"
    if raw.count("/") != 1:
        return "", "", "NUMBER_NAMESPACE_MALFORMED"
    local_id, namespace = raw.split("/", 1)
    if not local_id or not namespace:
        return "", "", "NUMBER_NAMESPACE_MALFORMED"
    if not _LOCAL_RE.fullmatch(local_id):
        return "", "", "NUMBER_LOCALID_MALFORMED"
    if namespace.isdigit():
        return "", "", "NUMBER_NAMESPACE_ABSENT"
    if not any(ch.isalpha() for ch in namespace):
        return "", "", "NUMBER_NAMESPACE_ABSENT"
    if not _NAMESPACE_RE.fullmatch(namespace):
        return "", "", "NUMBER_NAMESPACE_MALFORMED"
    return local_id, namespace, "EXACT_LITERAL_NAMESPACE_CANDIDATE"


def probe_record(
    record: Mapping[str, Any],
    *,
    coordinate_fetcher: Callable[..., Any] = generalized._fetch_coordinate,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason

    identity = paid_identity.identity_from_record(record)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "IDENTITY_INPUT_INCOMPLETE"

    local_id_candidate, set_id_candidate, parse_status = printed_number_namespace(identity.number)
    if not set_id_candidate:
        return None, parse_status

    language_code = _language_code(identity.language)
    if not language_code:
        return None, "LANGUAGE_UNSUPPORTED"

    # The provider suffix is used literally as the TCGdex set id.  There is no
    # alias normalization here.  The original printed reference remains on the
    # lot so generalized._fetch_coordinate must still prove its exact localId.
    retrieval_identity = replace(identity, set_name=set_id_candidate)
    lot = confirmation._lot_for_identity(retrieval_identity)
    recovered = coordinate_fetcher(
        lot,
        language_code=language_code,
        listing_set=set_id_candidate,
        listing_name=identity.name,
        set_id=set_id_candidate,
        expected_count=None,
        # Japanese Cardova names are romanized while the ja TCGdex coordinate
        # may be localized. Exact literal set id + exact localId is sufficient
        # macro identity proof; no translation is inferred.
        allow_localized_name_mismatch=(language_code == "ja"),
    )
    if recovered is None:
        return None, "LITERAL_NAMESPACE_COORDINATE_NOT_IN_TCGDEX"
    status = _norm(getattr(recovered, "status", "")) or "UNRESOLVED"
    recovered_reason = _norm(getattr(recovered, "reason", ""))
    if status != "EXACT":
        suffix = f":{recovered_reason}" if recovered_reason else ""
        return None, f"LITERAL_NAMESPACE_COORDINATE_{status}{suffix}"
    if _norm(getattr(recovered, "set_id", "")) != set_id_candidate:
        return None, "LITERAL_NAMESPACE_SET_ID_CONFLICT"
    if _norm(getattr(recovered, "language_code", "")).casefold() != language_code:
        return None, "LITERAL_NAMESPACE_LANGUAGE_CONFLICT"

    micro_ok, micro_status, micro_reason, micro_dimensions = microvariant_checker(
        identity, recovered
    )
    row = {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "card_name": identity.name,
        "collector_number": identity.number,
        "printed_local_id_candidate": local_id_candidate,
        "printed_set_id_candidate": set_id_candidate,
        "language": identity.language,
        "grader": identity.grader,
        "grade": identity.grade,
        "certification_number": _norm(record.get("certification_number")),
        "tcgdex_set_id": _norm(getattr(recovered, "set_id", "")),
        "tcgdex_card_id": _norm(getattr(recovered, "card_id", "")),
        "tcgdex_local_id": _norm(getattr(recovered, "local_id", "")),
        "macro_identity_status": "EXACT",
        "macro_identity_reason": recovered_reason,
        "microvariant_status": micro_status,
        "microvariant_reason": micro_reason,
        "microvariant_dimensions": dict(micro_dimensions),
        "microvariant_exact": bool(micro_ok),
        "exact_card_sale_evidence_ready": bool(micro_ok),
        "payment_completed_at_proven": False,
        "sale_transaction_ready": False,
    }
    if not micro_ok:
        suffix = f":{micro_reason}" if micro_reason else ""
        return row, f"MICROVARIANT_{micro_status}{suffix}"
    return row, "EXACT_LITERAL_NAMESPACE_COORDINATE"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PRINTED_NUMBER_LITERAL_TCGDEX_NAMESPACE_PROBE",
        "retrieval_rule": "NON_NUMERIC_PRINTED_SUFFIX_AS_LITERAL_SET_ID_PLUS_EXACT_LOCALID",
        "numeric_denominator_as_set_id": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "provider_set_alias_table_used": False,
        "literal_provider_namespace_only": True,
        "tcgdex_exact_coordinate_required": True,
        "microvariant_exact_required": True,
        "payment_completed_at_proven": False,
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


def run(
    records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    coordinate_fetcher: Callable[..., Any] = generalized._fetch_coordinate,
    microvariant_checker: Callable[[Any, Any], tuple[bool, str, str, Mapping[str, str]]] = paid_identity._microvariant_check,
    stack_installer: Callable[[], None] = paid_identity.install_tcgdex_stack_once,
) -> Mapping[str, Any]:
    stack_installer()
    selected = list(records[:max_records])
    rows: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    namespace_candidates = 0
    namespaces: set[str] = set()
    macro_exact = 0
    micro_exact = 0

    for record in selected:
        _local_id, namespace, _parse_status = printed_number_namespace(record.get("collector_number"))
        if namespace:
            namespace_candidates += 1
            namespaces.add(namespace)

        row, reason = probe_record(
            record,
            coordinate_fetcher=coordinate_fetcher,
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
        "structured_namespace_candidate_count": namespace_candidates,
        "unique_literal_namespaces": sorted(namespaces),
        "unique_literal_namespace_count": len(namespaces),
        "macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": micro_exact,
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
    parser = argparse.ArgumentParser(
        description="Probe Cardova printed-number literal TCGdex namespaces"
    )
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
