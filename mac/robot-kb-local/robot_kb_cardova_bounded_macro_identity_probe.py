#!/usr/bin/env python3
"""Read-only bounded macro-identity proof for legacy Cardova SOLD rows.

This probe composes two already-strict evidence layers:

1. the legacy cohort probe, which requires exact Cardova English name <-> TCGdex
   dexId agreement, one unique Japanese TCGdex set across the cohort, exactly one
   card for each selected dexId inside that set, and immutable source proof for
   every selected card;
2. the reviewed PSA Set Registry + pinned-set corroboration, which independently
   supports the Cardova verbose set label -> TCGdex set candidate for only four
   reviewed legacy Japanese sets.

The composed proof is deliberately row-scoped. It does NOT claim that Cardova's
numeric field globally means Pokédex/dexId. Instead, a row is macro-exact only
when its exact provider name, numeric value, corroborated set and unique pinned
TCGdex card all agree on one card coordinate.

Macro identity remains separate from commercial microvariant identity. No
canonical link is written here, unresolved finish/edition/variant dimensions are
not invented, and no V4 economic use, notification, purchase, bid, offer,
checkout or payment is possible.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
import robot_kb_cardova_legacy_set_cohort_probe as cohort  # noqa: E402
import robot_kb_cardova_psa_set_registry_corroboration_probe as registry  # noqa: E402


DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
HARD_MAX_GROUPS = 40
DEFAULT_MIN_DISTINCT_DEXIDS = 2

_COHORT_STATUS = "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY"
_SET_STATUS = "PSA_REGISTRY_AND_PINNED_SET_CORROBORATED_CANDIDATE_ONLY"
_MACRO_STATUS = "BOUNDED_SET_NAME_NUMERIC_UNIQUE_PINNED_MACRO_EXACT"


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _int(value: object) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def compose_registry_result(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Promote only rows whose complete bounded proof chain is present."""

    cohort_payload = payload.get("cohort")
    if not isinstance(cohort_payload, Mapping):
        return {
            "macro_identity_exact_count": 0,
            "microvariant_exact_count": 0,
            "exact_identity_link_candidate_count": 0,
            "blocked": {"COHORT_PAYLOAD_MISSING": 1},
            "groups": [],
            "records": [],
        }

    cohort_groups_raw = cohort_payload.get("groups")
    set_groups_raw = payload.get("corroborated_groups")
    if not isinstance(cohort_groups_raw, list) or not isinstance(set_groups_raw, list):
        return {
            "macro_identity_exact_count": 0,
            "microvariant_exact_count": 0,
            "exact_identity_link_candidate_count": 0,
            "blocked": {"PROOF_GROUPS_MISSING": 1},
            "groups": [],
            "records": [],
        }

    cohort_by_label = {
        _norm(group.get("provider_set_label")): group
        for group in cohort_groups_raw
        if isinstance(group, Mapping) and _norm(group.get("provider_set_label"))
    }

    blocked: Counter[str] = Counter()
    promoted_groups: list[dict[str, Any]] = []
    promoted_rows: list[dict[str, Any]] = []

    for set_group in set_groups_raw:
        if not isinstance(set_group, Mapping):
            blocked["SET_GROUP_MALFORMED"] += 1
            continue
        label = _norm(set_group.get("provider_set_label"))
        set_id = _norm(set_group.get("tcgdex_set_id_candidate"))
        if not label or not set_id:
            blocked["SET_GROUP_COORDINATE_MISSING"] += 1
            continue
        if _norm(set_group.get("corroboration_status")) != _SET_STATUS:
            blocked["SET_CORROBORATION_STATUS_UNPROVEN"] += 1
            continue
        if set_group.get("provider_set_label_exact_for_all_rows") is not True:
            blocked["PROVIDER_SET_LABEL_NOT_EXACT"] += 1
            continue
        if set_group.get("provider_titles_if_present_support_registry_set") is not True:
            blocked["PROVIDER_TITLE_CONFLICT"] += 1
            continue
        if set_group.get("macro_identity_exact") is not False:
            blocked["SET_INPUT_ALREADY_PROMOTED_UNEXPECTEDLY"] += 1
            continue

        group = cohort_by_label.get(label)
        if not isinstance(group, Mapping):
            blocked["COHORT_GROUP_NOT_FOUND"] += 1
            continue
        if _norm(group.get("tcgdex_set_id_candidate")) != set_id:
            blocked["COHORT_SET_ID_CONFLICT"] += 1
            continue
        if _norm(group.get("candidate_status")) != _COHORT_STATUS:
            blocked["COHORT_STATUS_UNPROVEN"] += 1
            continue
        if group.get("provider_name_dexid_exact_match_for_all_rows") is not True:
            blocked["COHORT_NAME_DEX_GATE_NOT_PROVEN"] += 1
            continue
        if _norm(group.get("pinned_source_commit")) != _norm(set_group.get("pinned_set_source_commit")):
            blocked["PINNED_SOURCE_COMMIT_CONFLICT"] += 1
            continue

        rows = group.get("records")
        if not isinstance(rows, list) or not rows:
            blocked["COHORT_RECORDS_MISSING"] += 1
            continue
        if _int(set_group.get("records_corroborated")) != len(rows):
            blocked["SET_RECORD_COUNT_CONFLICT"] += 1
            continue

        # Recheck the cohort's per-dex uniqueness invariant from its emitted
        # rows instead of trusting a boolean summary. Duplicate provider sales
        # of the same card are allowed; conflicting TCGdex card coordinates for
        # one dexId are not.
        card_ids_by_dex: dict[int, set[str]] = defaultdict(set)
        malformed = False
        for row in rows:
            if not isinstance(row, Mapping):
                malformed = True
                break
            dex_id = _int(row.get("dex_id_candidate"))
            card_id = _norm(row.get("tcgdex_card_id_candidate"))
            if dex_id is None or not card_id:
                malformed = True
                break
            card_ids_by_dex[dex_id].add(card_id)
        if malformed:
            blocked["COHORT_RECORD_MALFORMED"] += 1
            continue
        if any(len(values) != 1 for values in card_ids_by_dex.values()):
            blocked["COHORT_DEX_CARD_NOT_UNIQUE"] += 1
            continue

        group_rows: list[dict[str, Any]] = []
        group_failed = False
        for row in rows:
            assert isinstance(row, Mapping)
            dex_id = _int(row.get("dex_id_candidate"))
            card_id = _norm(row.get("tcgdex_card_id_candidate"))
            local_id = _norm(row.get("tcgdex_local_id_candidate"))
            parsed_set, parsed_local = cohort._split_card_id(card_id)
            if (
                row.get("provider_name_dexid_exact_match") is not True
                or _norm(row.get("candidate_status")) != _COHORT_STATUS
                or row.get("macro_identity_exact") is not False
                or row.get("exact_identity_link_candidate") is not False
                or dex_id is None
                or parsed_set != set_id
                or not local_id
                or parsed_local != local_id
                or not _norm(row.get("pinned_source_path"))
            ):
                group_failed = True
                break

            group_rows.append(
                {
                    "source_native_record_id": _norm(row.get("source_native_record_id")),
                    "card_name_provider_claim": _norm(row.get("card_name_provider_claim")),
                    "collector_number_provider_claim": _norm(row.get("collector_number_provider_claim")),
                    "provider_set_label": label,
                    "grader": _norm(row.get("grader")),
                    "grade": _norm(row.get("grade")),
                    "dex_id_row_bound_coordinate": dex_id,
                    "tcgdex_card_id": card_id,
                    "tcgdex_set_id": set_id,
                    "tcgdex_local_id": local_id,
                    "pinned_source_path": _norm(row.get("pinned_source_path")),
                    "pinned_source_commit": _norm(group.get("pinned_source_commit")),
                    "provider_numeric_semantics_global_claim": False,
                    "provider_numeric_semantics_proven_globally": False,
                    "row_bound_numeric_coordinate_verified": True,
                    "provider_name_dexid_exact_match": True,
                    "set_identity_independently_corroborated": True,
                    "tcgdex_card_unique_for_dex_within_set": True,
                    "macro_identity_status": "EXACT",
                    "macro_identity_reason": _MACRO_STATUS,
                    "macro_identity_exact": True,
                    "microvariant_exact": False,
                    "exact_identity_link_candidate": False,
                    "v4_economic_use": False,
                }
            )

        if group_failed:
            blocked["ROW_PROOF_CHAIN_INCOMPLETE"] += 1
            continue

        promoted_rows.extend(group_rows)
        promoted_groups.append(
            {
                "provider_set_label": label,
                "tcgdex_set_id": set_id,
                "records_promoted": len(group_rows),
                "distinct_dexids": len(card_ids_by_dex),
                "set_corroboration_status": _norm(set_group.get("corroboration_status")),
                "macro_identity_status": "EXACT",
                "macro_identity_reason": _MACRO_STATUS,
                "provider_numeric_semantics_global_claim": False,
                "microvariant_exact": False,
                "canonical_link_written": False,
            }
        )

    return {
        "macro_identity_exact_count": len(promoted_rows),
        "microvariant_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "blocked": dict(sorted(blocked.items())),
        "groups": promoted_groups,
        "records": promoted_rows,
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_BOUNDED_MACRO_IDENTITY_PROOF",
        "database_read_only_transaction": True,
        "row_scoped_proof_only": True,
        "provider_numeric_semantics_global_claim": False,
        "card_alias_table_used": False,
        "translation_assumed": False,
        "fuzzy_matching": False,
        "microvariant_exact": False,
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


def run(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
) -> Mapping[str, Any]:
    target = recovery.validate_local_database_url(database_url)
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    records = selected.get("records", [])
    if not isinstance(records, list):
        raise RuntimeError("Robot KB unresolved records payload is malformed")

    registry_payload = registry.run_records(
        records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
    )
    composed = compose_registry_result(registry_payload)

    summary = safe_summary()
    summary.update(target)
    summary.update(
        {
            "unresolved_sale_transactions_available": selected.get(
                "unresolved_sale_transactions_available", 0
            ),
            "selected_records": len(records),
            "db_read_blocked": selected.get("db_read_blocked", {}),
            "set_corroboration_groups": registry_payload.get(
                "psa_registry_corroborated_groups", 0
            ),
            "set_corroboration_records": registry_payload.get(
                "psa_registry_corroborated_records", 0
            ),
            "set_corroboration_blocked": registry_payload.get(
                "corroboration_blocked", {}
            ),
            "pinned_source_requests": registry_payload.get("pinned_source_requests", 0),
            **composed,
            "still_without_full_commercial_identity": len(records),
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compose bounded exact macro identity for reviewed Cardova legacy JP cohorts"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument(
        "--min-distinct-dexids", type=int, default=DEFAULT_MIN_DISTINCT_DEXIDS
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.max_groups <= HARD_MAX_GROUPS:
        parser.error(f"--max-groups must be between 1 and {HARD_MAX_GROUPS}")
    if args.min_distinct_dexids < 2:
        parser.error("--min-distinct-dexids must be at least 2")

    summary = safe_summary()
    try:
        database_url = os.environ.get("ROBOT_KB_DATABASE_URL", "")
        summary = dict(
            run(
                database_url,
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
            )
        )
        summary["error"] = None
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
