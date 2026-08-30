#!/usr/bin/env python3
"""Reviewed, bounded fallback for Cardova Japanese Basic No Rarity printing.

The live PSA checklist/cert surfaces can return HTTP 403 from the local Mac.
This module does not bypass that protection. Instead it composes the existing
live No Rarity probe with a manually reviewed PSA evidence manifest limited to
five exact card-name/card-number coordinates observed in the current Cardova
paid-SOLD cohort.

A reviewed coordinate only corroborates the row-specific Cardova provider claim
``No Rarity Original Print``. It does not prove the Cardova PSA certificate was
read, does not turn No Rarity into First Edition, and does not close edition,
special-finish or generic variant applicability. Therefore microvariant exact,
canonical links, Robot KB writes, V4 economics and commerce all remain disabled.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_no_rarity_printing_probe as live_probe  # noqa: E402


REVIEWED_AT = "2026-08-30"
REVIEWED_NO_RARITY_EVIDENCE: Mapping[tuple[str, int], Mapping[str, str]] = {
    ("sandshrew", 27): {
        "source_url": "https://www.psacard.com/cert/102399515/psa",
        "source_label": "1996 POKEMON JAPANESE BASIC #27 SANDSHREW NO RARITY SYMBOL",
    },
    ("nidorino", 33): {
        "source_url": "https://www.psacard.com/cert/122645726/psa",
        "source_label": "1996 POKEMON JAPANESE BASIC #33 NIDORINO NO RARITY SYMBOL",
    },
    ("arcanine", 59): {
        "source_url": "https://www.psacard.com/psasetregistry/tcg/pokemon-sets/1996-pokemon-japanese-basic/imagegallery/571398",
        "source_label": "1996 POKEMON JAPANESE BASIC 59 ARCANINE NO RARITY SYMBOL",
    },
    ("machop", 66): {
        "source_url": "https://www.psacard.com/psasetregistry/pecopeco/imagegallery/142239",
        "source_label": "1996 POKEMON JAPANESE BASIC 66 MACHOP NO RARITY SYMBOL",
    },
    ("gastly", 92): {
        "source_url": "https://www.psacard.com/psasetregistry/tomo/imagegallery/38865",
        "source_label": "1996 POKEMON JAPANESE BASIC 92 GASTLY NO RARITY SYMBOL",
    },
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _coord(row: Mapping[str, Any]) -> Optional[tuple[str, int]]:
    name = _norm(row.get("card_name_provider_claim")).casefold()
    number = _norm(row.get("collector_number_provider_claim")).lstrip("#")
    if not name or not number.isdigit():
        return None
    return name, int(number)


def _eligible_row(row: Mapping[str, Any]) -> bool:
    return (
        live_probe._is_exact_no_rarity_candidate(row)
        and row.get("printing_exact") is not True
        and row.get("microvariant_exact") is False
        and row.get("exact_identity_link_candidate") is False
    )


def _unique_finish(row: Mapping[str, Any]) -> str:
    choices = row.get("source_finish_choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
        return ""
    normalized = [_norm(value).casefold() for value in choices if _norm(value)]
    if len(normalized) != 1 or normalized[0] not in {"normal", "holo", "reverse"}:
        return ""
    return normalized[0]


def apply_reviewed_fallback(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = payload.get("records")
    if not isinstance(rows, list):
        raise ValueError("live No Rarity payload has no records list")

    live_blocked = dict(payload.get("blocked") or {})
    unresolved: Counter[str] = Counter()
    promoted = 0
    output_rows: list[dict[str, Any]] = []

    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if not _eligible_row(row):
            output_rows.append(row)
            continue

        coord = _coord(row)
        evidence = REVIEWED_NO_RARITY_EVIDENCE.get(coord) if coord else None
        if evidence is None:
            unresolved["REVIEWED_NO_RARITY_COORDINATE_EVIDENCE_MISSING"] += 1
            output_rows.append(row)
            continue

        finish = _unique_finish(row)
        if not finish:
            unresolved["REVIEWED_NO_RARITY_FINISH_NOT_UNIQUE"] += 1
            output_rows.append(row)
            continue

        row.update(
            {
                "reviewed_no_rarity_fallback_used": True,
                "reviewed_no_rarity_reviewed_at": REVIEWED_AT,
                "reviewed_no_rarity_source_url": evidence["source_url"],
                "reviewed_no_rarity_source_label": evidence["source_label"],
                "reviewed_no_rarity_cardova_cert_read": False,
                "provider_no_rarity_claim_exact": True,
                "printing_exact": True,
                "printing": "no_rarity_symbol",
                "printing_proof_reason": "PRINTING_EXACT_PROVIDER_REVIEWED_PSA_COORDINATE_CORROBORATED",
                "provider_original_print_wording_proven": False,
                "edition_exact": False,
                "edition": "",
                "no_rarity_is_first_edition": False,
                "finish_exact": True,
                "finish": finish,
                "finish_proof_reason": "FINISH_EXACT_UNIQUE_PINNED_SOURCE_AFTER_REVIEWED_PRINTING_CORROBORATION",
                "commercial_axes_proven": {
                    "finish": finish,
                    "printing": "no_rarity_symbol",
                },
                "remaining_unproven_axes": [
                    "edition_applicability",
                    "special_finish_applicability",
                    "variant_applicability",
                ],
                "microvariant_exact": False,
                "exact_identity_link_candidate": False,
                "exact_card_sale_evidence_ready": False,
                "sale_transaction_ready": False,
                "v4_economic_use": False,
            }
        )
        promoted += 1
        output_rows.append(row)

    out = dict(payload)
    out.update(
        {
            "live_psa_blocked": live_blocked,
            "reviewed_no_rarity_manifest_entries": len(REVIEWED_NO_RARITY_EVIDENCE),
            "reviewed_no_rarity_rows_proven": promoted,
            "reviewed_no_rarity_fallback_used": promoted > 0,
            "reviewed_no_rarity_cardova_cert_read": False,
            "printing_exact_count": sum(1 for row in output_rows if row.get("printing_exact") is True),
            "finish_exact_count": sum(1 for row in output_rows if row.get("finish_exact") is True),
            "microvariant_exact_count": 0,
            "exact_identity_link_candidate_count": 0,
            "blocked": dict(sorted(unresolved.items())),
            "records": output_rows,
        }
    )
    return out


def run_database(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
    pacing_seconds: float,
) -> Mapping[str, Any]:
    live = live_probe.run_database(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        timeout_seconds=timeout_seconds,
        pacing_seconds=pacing_seconds,
    )
    return apply_reviewed_fallback(live)


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_NO_RARITY_REVIEWED_FALLBACK",
        "live_psa_403_bypass": False,
        "reviewed_evidence_is_bounded": True,
        "reviewed_evidence_proves_cardova_cert": False,
        "no_rarity_is_first_edition": False,
        "provider_original_print_wording_proven": False,
        "microvariant_exact": False,
        "canonical_link_written": False,
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Apply bounded reviewed PSA No Rarity evidence read-only")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=500)
    parser.add_argument("--max-groups", type=int, default=20)
    parser.add_argument("--min-distinct-dexids", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--pacing-seconds", type=float, default=1.0)
    args = parser.parse_args(argv)

    try:
        payload = dict(safe_summary())
        payload.update(
            run_database(
                args.database_url,
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
                timeout_seconds=args.timeout_seconds,
                pacing_seconds=args.pacing_seconds,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload = dict(safe_summary())
        payload["error"] = f"{type(error).__name__}: {error}"
        code = 1

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
