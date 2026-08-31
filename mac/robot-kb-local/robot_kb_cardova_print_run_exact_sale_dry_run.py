#!/usr/bin/env python3
"""Cardova exact-sale memory dry-run using the validated P3 print_run registry.

This layer deliberately leaves PR #206 unchanged as the pre-schema-gap proof. It
reuses #206 persistence and only translates positively proven Cardova rarity-symbol
printing evidence into the #207 generic ``print_run`` dimension.

No durable PostgreSQL write, V4 economic use, notification, purchase or bid occurs.
"""

from __future__ import annotations

import argparse
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

import robot_kb_cardova_canonical_sale_persistence_dry_run as base  # noqa: E402


_BASE_CANONICAL_PLAN = base.canonical_plan
_VISIBLE_RARITY_SYMBOL_REASON = "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL"
_NO_RARITY = "no_rarity_symbol"
_PRINT_RUN_NO_RARITY = "NO_RARITY_SYMBOL"
_PRINT_RUN_SYMBOL_PRESENT = "RARITY_SYMBOL_PRESENT"


def _norm(value: object) -> str:
    return base._norm(value)


def _print_run_proof(identity: Mapping[str, Any]) -> tuple[str, str]:
    dims = identity.get("pinned_source_variant_dimensions")
    dim_printing = ""
    if isinstance(dims, Mapping):
        dim_printing = _norm(dims.get("printing")).casefold()
    identity_printing = _norm(identity.get("printing")).casefold()

    explicit = {token for token in (dim_printing, identity_printing) if token}
    if len(explicit) > 1:
        return "", "CARDOVA_PRINTING_PROOF_CONFLICT"
    if explicit:
        token = next(iter(explicit))
        if token != _NO_RARITY:
            return "", "P3_PRINT_RUN_MAPPING_UNSUPPORTED"
        if identity.get("printing_exact") is not True:
            return "", "CARDOVA_PRINTING_PROOF_NOT_EXACT"
        return _PRINT_RUN_NO_RARITY, "CARDOVA_EXPLICIT_NO_RARITY_PROOF"

    if _norm(identity.get("printing_applicability_reason")) == _VISIBLE_RARITY_SYMBOL_REASON:
        if identity.get("printing_applicability_exact") is not True:
            return "", "CARDOVA_RARITY_SYMBOL_PROOF_NOT_EXACT"
        return _PRINT_RUN_SYMBOL_PRESENT, "CARDOVA_REVIEWED_RARITY_SYMBOL_PROOF"

    return "", "CARDOVA_PRINT_RUN_PROOF_MISSING"


def canonical_plan(
    identity: Mapping[str, Any],
    sale: Mapping[str, Any],
) -> tuple[Optional[base.CanonicalPlan], str]:
    """Reuse #206 and resolve only its validated printing-schema blocker."""

    plan, reason = _BASE_CANONICAL_PLAN(identity, sale)
    if plan is not None or reason != base._PRINTING_SCHEMA_GAP_REASON:
        return plan, reason

    print_run, proof_reason = _print_run_proof(identity)
    if not print_run:
        return None, proof_reason

    # Remove only the Cardova source-level ``printing`` token before delegating
    # to #206. The exact information is immediately restored below as the P3
    # generic ``print_run`` assignment. No edition/default semantics are added.
    sanitized = dict(identity)
    dims = identity.get("pinned_source_variant_dimensions")
    clean_dims = dict(dims) if isinstance(dims, Mapping) else {}
    clean_dims.pop("printing", None)
    sanitized["pinned_source_variant_dimensions"] = clean_dims
    sanitized["printing"] = ""
    sanitized["printing_exact"] = False
    sanitized["printing_applicability_reason"] = "MAPPED_TO_P3_PRINT_RUN"

    plan, delegated_reason = _BASE_CANONICAL_PLAN(sanitized, sale)
    if plan is None:
        return None, delegated_reason

    assignments = dict(plan.profile_assignments)
    assignments["print_run"] = print_run
    applicability = dict(plan.applicability)
    applicability["print_run"] = "APPLICABLE"

    return (
        replace(
            plan,
            profile_assignments=dict(sorted(assignments.items())),
            applicability=dict(sorted(applicability.items())),
        ),
        "P3_CANONICAL_PLAN_READY",
    )


def run_memory_dry_run(
    sales: Sequence[Mapping[str, Any]],
    identity_rows: Sequence[Mapping[str, Any]],
    *,
    observed_at: Optional[str] = None,
    replay: bool = True,
) -> Mapping[str, Any]:
    """Run #206 persistence with the print_run-aware plan, restoring globals."""

    previous = base.canonical_plan
    base.canonical_plan = canonical_plan
    try:
        return base.run_memory_dry_run(
            sales,
            identity_rows,
            observed_at=observed_at,
            replay=replay,
        )
    finally:
        base.canonical_plan = previous


def safe_summary() -> Mapping[str, Any]:
    summary = dict(base.safe_summary())
    summary.update(
        {
            "mode": "MEMORY_ONLY_CARDOVA_PRINT_RUN_EXACT_SALE_DRY_RUN",
            "p3_207_print_run_registry_reused": True,
            "proof_preserving_print_run_mapping": True,
            "unsupported_printing_fail_closed": True,
            "no_rarity_implies_first_edition": False,
            "rarity_symbol_present_implies_unlimited": False,
            "printing_schema_gap_fail_closed": False,
        }
    )
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Memory-only Cardova exact-sale persistence with P3 rarity-symbol print_run"
    )
    parser.add_argument("--sales-input", type=Path, required=True)
    parser.add_argument("--identity-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at", default="")
    args = parser.parse_args(argv)

    payload = dict(safe_summary())
    code = 1
    try:
        payload.update(
            run_memory_dry_run(
                base._records(args.sales_input),
                base._records(args.identity_input),
                observed_at=_norm(args.observed_at) or None,
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
