#!/usr/bin/env python3
"""Read-only exact TCGdex identity pass for proven Cardova paid-SOLD evidence.

Input is the JSON produced by ``robot_kb_cardova_paid_sold_harvest.py``.  The
harvest has already proved provider-level payment/completion semantics and JPY
final-winning-bid evidence.  This phase only asks whether the same record can be
bound to one exact TCGdex card and one exact compatible commercial microvariant.

No new Cardova resolver exists here.  The module reuses the production V4
seven-layer deterministic TCGdex stack, the validated source-alias recovery and
``variants_detailed`` microvariant gate.  Ambiguous, missing, conflicting,
opaque or provider-error results remain blocked.

Even an exact identity remains ``sale_transaction_ready=false``: Cardova's
public closed-auction payload exposes auction end time, not the exact payment-
completion timestamp.  This module never writes Robot KB or SALE_TRANSACTION
and has no V4 economic/notification/transaction capability.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v4_global_market_core import CommercialIdentity  # noqa: E402
import v4_global_economic_confirmation as confirmation  # noqa: E402
import v4_tcgdex_detailed_variants as detailed_variants  # noqa: E402
from v4_global_marketplace_tcgdex_source_alias_recovery import (  # noqa: E402
    install_global_marketplace_tcgdex_source_alias_recovery,
)
from v4_tcgdex_exact_coordinate_recovery import (  # noqa: E402
    install_v4_tcgdex_exact_coordinate_recovery,
)
from v4_tcgdex_generalized_coordinate_recovery import (  # noqa: E402
    install_v4_tcgdex_generalized_coordinate_recovery,
)
from v4_tcgdex_japanese_set_aliases import install_v4_tcgdex_japanese_set_aliases  # noqa: E402
from v4_tcgdex_run1054_set_aliases import install_v4_tcgdex_run1054_set_aliases  # noqa: E402
from v4_tcgdex_source_pinned_finish import install_v4_tcgdex_source_pinned_finish  # noqa: E402
from v4_tcgdex_two_of_three_backport import install_v4_tcgdex_two_of_three_backport  # noqa: E402
from v4_tcgdex_unique_coordinate_fallback import (  # noqa: E402
    install_v4_tcgdex_unique_coordinate_fallback,
)


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
PROVEN_SOURCE = "cardova_public_past_auction"
PROVEN_STATUS = "PAID_COMPLETED"
PROVEN_CURRENCY = "JPY"

_TCGDEX_STACK_INSTALLED = False


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _positive_int(value: object) -> bool:
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False


def install_tcgdex_stack_once() -> None:
    """Install the existing exact stack once; never recursively re-wrap per row."""

    global _TCGDEX_STACK_INSTALLED
    if _TCGDEX_STACK_INSTALLED:
        return

    # Production V4 order.  The flag is set only after every installer succeeds,
    # so a partial/failed install cannot be reported as ready.
    install_v4_tcgdex_exact_coordinate_recovery()
    install_v4_tcgdex_run1054_set_aliases()
    install_v4_tcgdex_japanese_set_aliases()
    install_v4_tcgdex_generalized_coordinate_recovery()
    install_v4_tcgdex_two_of_three_backport()
    install_v4_tcgdex_unique_coordinate_fallback()
    install_v4_tcgdex_source_pinned_finish()
    detailed_variants.install_v4_tcgdex_detailed_variants()
    install_global_marketplace_tcgdex_source_alias_recovery()
    _TCGDEX_STACK_INSTALLED = True


def _eligible_record(record: Mapping[str, Any]) -> tuple[bool, str]:
    if _norm(record.get("source")) != PROVEN_SOURCE:
        return False, "SOURCE_NOT_PROVEN_CARDOVA"
    if record.get("sale_evidence_ready") is not True:
        return False, "SALE_EVIDENCE_NOT_READY"
    if _norm(record.get("provider_sale_status")) != PROVEN_STATUS:
        return False, "PAID_COMPLETED_STATUS_MISSING"
    if record.get("provider_sale_status_proven") is not True:
        return False, "PAYMENT_SEMANTICS_UNPROVEN"
    if _norm(record.get("currency")).upper() != PROVEN_CURRENCY:
        return False, "CURRENCY_NOT_JPY"
    if record.get("currency_proven") is not True:
        return False, "CURRENCY_UNPROVEN"
    if not _positive_int(record.get("final_bid_jpy")):
        return False, "FINAL_BID_INVALID"
    if not _norm(record.get("source_native_record_id")):
        return False, "SOURCE_ID_MISSING"
    if not _norm(record.get("certification_number")):
        return False, "CERT_NUMBER_MISSING"
    if not _norm(record.get("auction_end_at_utc")):
        return False, "AUCTION_END_MISSING"
    return True, "ELIGIBLE"


def identity_from_record(record: Mapping[str, Any]) -> CommercialIdentity:
    return CommercialIdentity(
        name=_norm(record.get("card_name")),
        set_name=_norm(record.get("set_name")),
        number=_norm(record.get("collector_number")),
        language=_norm(record.get("language")),
        grader=_norm(record.get("grader")).upper(),
        grade=_norm(record.get("grade")),
        # Cardova historical rows currently do not prove these axes.  Leaving
        # them empty is intentional; TCGdex must prove a unique microvariant or
        # the record remains blocked.
        edition="",
        finish="",
        variant="",
    )


def _microvariant_check(identity: CommercialIdentity, canonical: Any) -> tuple[bool, str, str, Mapping[str, str]]:
    expected = detailed_variants._expected_from_global_identity(identity)
    decision = detailed_variants.detailed_variant_decision(canonical, expected)
    dimensions: Mapping[str, str] = {}
    if decision.selected is not None:
        dimensions = decision.selected.dimension_map()
    return (
        bool(decision.compatible and decision.status == "EXACT"),
        str(decision.status or "UNPROVEN"),
        str(decision.reason or ""),
        dimensions,
    )


def resolve_record(
    record: Mapping[str, Any],
    *,
    resolver: Callable[[CommercialIdentity], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[CommercialIdentity, Any], tuple[bool, str, str, Mapping[str, str]]] = _microvariant_check,
) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = _eligible_record(record)
    if not eligible:
        return None, reason

    identity = identity_from_record(record)
    if not identity.complete_for_exact_market or not identity.opportunity_language:
        return None, "IDENTITY_INPUT_INCOMPLETE"

    try:
        _lot, canonical = resolver(identity)
    except Exception as error:
        return None, f"TCGDEX_EXCEPTION:{type(error).__name__}"

    status = _norm(getattr(canonical, "status", "")) or "UNRESOLVED"
    canonical_reason = _norm(getattr(canonical, "reason", ""))
    if status != "EXACT":
        suffix = f":{canonical_reason}" if canonical_reason else ""
        return None, f"TCGDEX_{status}{suffix}"

    canonical_language = _norm(getattr(canonical, "language_code", "")).casefold()
    expected_language = "ja" if identity.language.casefold() in {"ja", "jp", "japanese"} else "en"
    if canonical_language != expected_language:
        return None, "TCGDEX_LANGUAGE_CONFLICT"

    micro_ok, micro_status, micro_reason, micro_dimensions = microvariant_checker(identity, canonical)
    if not micro_ok:
        suffix = f":{micro_reason}" if micro_reason else ""
        return None, f"MICROVARIANT_{micro_status}{suffix}"

    resolved = dict(record)
    resolved.update(
        {
            "identity_status": "EXACT",
            "identity_reason": canonical_reason,
            "canonical_card_name": _norm(getattr(canonical, "name", "")),
            "canonical_set_name": _norm(getattr(canonical, "set_name", "")),
            "canonical_language": canonical_language,
            "tcgdex_card_id": _norm(getattr(canonical, "card_id", "")),
            "microvariant_status": "EXACT",
            "microvariant_reason": micro_reason,
            "microvariant_dimensions": dict(micro_dimensions),
            "exact_card_sale_evidence_ready": True,
            # Still deliberately blocked: no explicit Cardova payment timestamp.
            "payment_completed_at_proven": False,
            "sale_transaction_ready": False,
        }
    )
    return resolved, "EXACT_IDENTITY_AND_MICROVARIANT"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PAID_SOLD_TCGDEX_IDENTITY",
        "input_source_required": PROVEN_SOURCE,
        "paid_status_required": PROVEN_STATUS,
        "currency_required": PROVEN_CURRENCY,
        "identity_resolution_attempted": True,
        "tcgdex_stack": "V4_7_LAYER_PLUS_DETAILED_VARIANTS_AND_REVIEWED_SOURCE_ALIAS",
        "tcgdex_stack_installed_once_per_process": True,
        "new_identity_resolver_created": False,
        "payment_completed_at_proven": False,
        "sale_transaction_ready": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def resolve_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    resolver: Callable[[CommercialIdentity], tuple[Any, Any]] = confirmation.resolve_global_canonical,
    microvariant_checker: Callable[[CommercialIdentity, Any], tuple[bool, str, str, Mapping[str, str]]] = _microvariant_check,
    stack_installer: Callable[[], None] = install_tcgdex_stack_once,
) -> Mapping[str, Any]:
    stack_installer()
    selected = list(records[:max_records])
    exact: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    macro_exact = 0

    for record in selected:
        # Count macro exact separately without weakening the final microvariant gate.
        eligible, pre_reason = _eligible_record(record)
        if not eligible:
            blocked[pre_reason] += 1
            continue
        identity = identity_from_record(record)
        if not identity.complete_for_exact_market or not identity.opportunity_language:
            blocked["IDENTITY_INPUT_INCOMPLETE"] += 1
            continue
        try:
            _lot, canonical = resolver(identity)
        except Exception as error:
            blocked[f"TCGDEX_EXCEPTION:{type(error).__name__}"] += 1
            continue
        status = _norm(getattr(canonical, "status", "")) or "UNRESOLVED"
        canonical_reason = _norm(getattr(canonical, "reason", ""))
        if status != "EXACT":
            key = f"TCGDEX_{status}" + (f":{canonical_reason}" if canonical_reason else "")
            blocked[key] += 1
            continue
        macro_exact += 1

        # Reuse the already-resolved canonical instead of performing a second
        # TCGdex request.  This keeps one resolution pass per target.
        def resolved_once(_identity: CommercialIdentity, *, _canonical=canonical):
            return None, _canonical

        resolved, final_reason = resolve_record(
            record,
            resolver=resolved_once,
            microvariant_checker=microvariant_checker,
        )
        if resolved is None:
            blocked[final_reason] += 1
            continue
        exact.append(resolved)

    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": len(exact),
        "blocked": dict(sorted(blocked.items())),
        "records": exact,
    }


def load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("input JSON must be an object")
    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("input JSON must contain records[]")
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError("records[] must contain objects only")
    return list(records)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve exact TCGdex identity for Cardova paid-SOLD evidence")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    summary = safe_summary()
    try:
        records = load_records(args.input)
        summary.update(resolve_records(records, max_records=args.max_records))
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
