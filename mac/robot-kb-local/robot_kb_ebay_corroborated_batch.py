#!/usr/bin/env python3
"""Manual bounded batch for exact TCGdex canonicalization + corroborated eBay sales.

The batch only composes already-proven Robot KB capabilities:

- #192 benchmark/corroboration classification remains the SOLD gate;
- #194 exact GCC -> TCGdex canonicalization remains the identity gate;
- #193 append-only corroborated sale importer remains the persistence path.

Safety properties:

- no eBay/PSA/RapidAPI network call is made by this module;
- TCGdex is contacted only when a corroborated target lacks a PROVEN canonical link;
- validate writes nothing;
- write requires an explicit confirmation token and is bounded to <= 50 reviewed records;
- one failed/ambiguous item is blocked without weakening another item's gate;
- only CORROBORATED_SOLD may become SALE_TRANSACTION;
- no V4 economic use, purchase, bid, checkout, payment, notification or schedule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
LOCAL_DIR = Path(__file__).resolve().parent
if str(LOCAL_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_DIR))

from robot_kb_ebay_corroborated_import import (  # noqa: E402
    CorroboratedImportError,
    _load_json,
    gcc_listing_id as importer_gcc_listing_id,
    persist_corroborated_sale,
    select_corroborated_item,
    validate_database_target,
)
from robot_kb_ebay_exact_benchmark import (  # noqa: E402
    _normalized_grade,
    _normalized_grader,
    load_corroboration_file,
    normalize_language,
    normalized,
)
from robot_kb_tcgdex_canonicalize import (  # noqa: E402
    CanonicalizationError,
    _norm_number,
    canonical_plan,
    gcc_listing_id as canonical_gcc_listing_id,
    load_gcc_identity,
    persist_plan,
    resolve_tcgdex_exact,
)


DEFAULT_MAX_ITEMS = 20
HARD_MAX_ITEMS = 50
WRITE_CONFIRMATION = "WRITE_CORROBORATED_SALES"


class CorroboratedBatchError(RuntimeError):
    pass


def _safe_item(item_id: str) -> dict[str, Any]:
    return {
        "item_id": item_id,
        "corroborated_sold": False,
        "gcc_identity_consistent": False,
        "tcgdex_exact": False,
        "microvariant_proven": False,
        "canonical_card_resolved": False,
        "canonicalization_persisted": False,
        "ready_for_write": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "duplicate_sale_replay": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def safe_summary(*, mode: str, max_items: int, records_available: int) -> dict[str, Any]:
    return {
        "mode": mode,
        "max_items": max_items,
        "corroboration_records_available": records_available,
        "items_considered": 0,
        "corroborated_sold": 0,
        "blocked": 0,
        "unexpected_errors": 0,
        "canonical_already_proven": 0,
        "canonicalization_ready": 0,
        "canonicalizations_persisted": 0,
        "sale_transactions_stored": 0,
        "duplicate_sale_replays": 0,
        "robot_kb_write": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
        "items": [],
    }


def _validate_limit(value: int) -> int:
    if isinstance(value, bool) or value < 1 or value > HARD_MAX_ITEMS:
        raise CorroboratedBatchError(
            f"--max-items must be between 1 and {HARD_MAX_ITEMS}"
        )
    return value


def _selected_item_ids(corroborations: Mapping[str, Any], max_items: int) -> list[str]:
    _validate_limit(max_items)
    return sorted(str(item_id) for item_id in corroborations)[:max_items]


def _assert_target_matches_retained_gcc(target: Any, identity: Any) -> None:
    """Block stale benchmark identity before canonicalization or sale persistence."""

    target_listing = importer_gcc_listing_id(target.gcc_url)
    canonical_listing = canonical_gcc_listing_id(identity.listing_id)
    if target_listing != canonical_listing:
        raise CorroboratedBatchError("benchmark target GCC listing conflicts with retained GCC identity")

    checks = (
        (normalized(target.title), normalized(identity.title), "title"),
        (normalized(target.card_set), normalized(identity.card_set), "set"),
        (
            _norm_number(target.collector_number),
            _norm_number(identity.collector_number),
            "collector number",
        ),
        (
            normalize_language(target.language),
            identity.language_code.upper(),
            "language",
        ),
        (
            _normalized_grader(target.grader),
            _normalized_grader(identity.grader),
            "grader",
        ),
        (
            _normalized_grade(target.grade),
            _normalized_grade(identity.grade),
            "grade",
        ),
    )
    for left, right, label in checks:
        if not left or left != right:
            raise CorroboratedBatchError(
                f"benchmark target {label} conflicts with retained GCC identity"
            )
    if target.year is not None and target.year != identity.year:
        raise CorroboratedBatchError(
            "benchmark target year conflicts with retained GCC identity"
        )


def _existing_canonical_card(kb: Any, target: Any) -> Optional[str]:
    try:
        return validate_database_target(kb, target)
    except CorroboratedImportError as exc:
        # Only the explicit zero-link case may continue into #194 bootstrap.
        # Any contradictory/non-unique state remains blocking.
        if str(exc).endswith("got 0"):
            return None
        raise


def _prepare_canonicalization(
    kb: Any,
    target: Any,
    *,
    cache: dict[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    listing_id = importer_gcc_listing_id(target.gcc_url)
    cached = cache.get(listing_id)
    if cached is not None:
        return cached

    identity = load_gcc_identity(kb, listing_id)
    _assert_target_matches_retained_gcc(target, identity)
    resolved = resolve_tcgdex_exact(identity)
    plan = canonical_plan(identity, resolved)
    prepared = {
        "identity": identity,
        "plan": plan,
        "listing_id": listing_id,
    }
    cache[listing_id] = prepared
    return prepared


def _process_item(
    kb: Any,
    *,
    mode: str,
    report: Mapping[str, Any],
    corroborations: Mapping[str, Any],
    item_id: str,
    canonical_cache: dict[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    result = _safe_item(item_id)

    target, candidate, record = select_corroborated_item(
        report,
        corroborations,
        item_id,
    )
    result["corroborated_sold"] = True
    result["gcc_url"] = target.gcc_url
    result["sale"] = {
        "date_sold": record.date_sold,
        "sale_price_minor": record.sale_price_minor,
        "currency": record.currency,
        "source": record.source,
    }

    card_id = _existing_canonical_card(kb, target)
    if card_id is not None:
        result["canonical_card_resolved"] = True
        result["canonical_card_id"] = card_id
        result["canonical_source"] = "EXISTING_PROVEN_GCC_LINK"
    else:
        prepared = _prepare_canonicalization(
            kb,
            target,
            cache=canonical_cache,
        )
        identity = prepared["identity"]
        plan = prepared["plan"]
        result["gcc_identity_consistent"] = True
        result["tcgdex_exact"] = True
        result["microvariant_proven"] = True
        result["canonical_plan"] = asdict(plan)

        if mode == "write":
            persisted = persist_plan(kb, identity, plan)
            result["canonicalization_persisted"] = True
            result["robot_kb_write"] = True
            result["canonical_card_id"] = persisted["canonical_card_id"]
            card_id = validate_database_target(kb, target)
            if card_id != persisted["canonical_card_id"]:
                raise CorroboratedBatchError(
                    "post-canonicalization GCC link does not resolve to persisted canonical card"
                )
            result["canonical_card_resolved"] = True
            result["canonical_source"] = "BATCH_TCGDEX_CANONICALIZATION"
        else:
            result["canonical_source"] = "TCGDEX_PLAN_READY_NO_WRITE"

    result["ready_for_write"] = True
    if mode == "validate":
        result["status"] = "READY"
        return result

    sale_result = persist_corroborated_sale(kb, target, candidate, record)
    result["robot_kb_write"] = True
    result["canonical_card_id"] = sale_result["canonical_card_id"]
    stored = int(sale_result.get("sale_transactions_stored", 0) or 0)
    duplicate = int(sale_result.get("duplicate_sale_replays", 0) or 0)
    result["sale_transactions_stored"] = stored
    result["duplicate_sale_replays"] = duplicate
    result["observations_replayed"] = int(
        sale_result.get("observations_replayed", 0) or 0
    )
    result["sale_transaction_stored"] = stored > 0
    result["duplicate_sale_replay"] = duplicate > 0
    if stored > 0:
        result["status"] = "SALE_STORED"
    elif duplicate > 0:
        result["status"] = "DUPLICATE_REPLAY"
    else:
        raise CorroboratedBatchError(
            "sale write produced neither a stored transaction nor an idempotent duplicate replay"
        )
    return result


def run_batch(
    kb: Any,
    *,
    mode: str,
    report: Mapping[str, Any],
    corroborations: Mapping[str, Any],
    max_items: int,
) -> tuple[dict[str, Any], int]:
    item_ids = _selected_item_ids(corroborations, max_items)
    summary = safe_summary(
        mode=mode,
        max_items=max_items,
        records_available=len(corroborations),
    )
    summary["items_considered"] = len(item_ids)
    summary["truncated"] = len(corroborations) > len(item_ids)
    canonical_cache: dict[str, Mapping[str, Any]] = {}

    for item_id in item_ids:
        try:
            item = dict(
                _process_item(
                    kb,
                    mode=mode,
                    report=report,
                    corroborations=corroborations,
                    item_id=item_id,
                    canonical_cache=canonical_cache,
                )
            )
            summary["corroborated_sold"] += 1
            if item.get("canonical_source") == "EXISTING_PROVEN_GCC_LINK":
                summary["canonical_already_proven"] += 1
            elif item.get("canonical_source") == "TCGDEX_PLAN_READY_NO_WRITE":
                summary["canonicalization_ready"] += 1
            if item.get("canonicalization_persisted"):
                summary["canonicalizations_persisted"] += 1
            summary["sale_transactions_stored"] += int(
                item.get("sale_transactions_stored", 0) or 0
            )
            summary["duplicate_sale_replays"] += int(
                item.get("duplicate_sale_replays", 0) or 0
            )
            if item.get("robot_kb_write"):
                summary["robot_kb_write"] = True
            summary["items"].append(item)
        except (CorroboratedImportError, CanonicalizationError, CorroboratedBatchError, ValueError) as exc:
            blocked = _safe_item(item_id)
            blocked["status"] = "BLOCKED"
            blocked["error"] = str(exc)
            summary["blocked"] += 1
            summary["items"].append(blocked)
        except Exception as exc:
            failed = _safe_item(item_id)
            failed["status"] = "ERROR"
            failed["error"] = f"{type(exc).__name__}: {exc}"
            summary["unexpected_errors"] += 1
            summary["items"].append(failed)

    return summary, (1 if summary["unexpected_errors"] else 0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate or manually run a bounded batch of exact TCGdex canonicalization "
            "and independently corroborated eBay sale imports"
        )
    )
    parser.add_argument("mode", choices=("validate", "write"))
    parser.add_argument("--benchmark-file", type=Path, required=True)
    parser.add_argument("--corroboration-file", type=Path, required=True)
    parser.add_argument("--max-items", type=int, default=DEFAULT_MAX_ITEMS)
    parser.add_argument(
        "--confirm-write",
        default="",
        help=f"required for write mode: {WRITE_CONFIRMATION}",
    )
    args = parser.parse_args(argv)

    try:
        max_items = _validate_limit(args.max_items)
        if args.mode == "write" and args.confirm_write != WRITE_CONFIRMATION:
            raise CorroboratedBatchError(
                f"write mode requires --confirm-write {WRITE_CONFIRMATION}"
            )
        report = _load_json(args.benchmark_file, "benchmark")
        corroborations = load_corroboration_file(args.corroboration_file)
        database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
        if not database:
            raise CorroboratedBatchError("ROBOT_KB_DATABASE_URL is required")

        from robot_kb.repository import KnowledgeBase

        with KnowledgeBase.open(database) as kb:
            summary, exit_code = run_batch(
                kb,
                mode=args.mode,
                report=report,
                corroborations=corroborations,
                max_items=max_items,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return exit_code
    except (CorroboratedBatchError, CorroboratedImportError, ValueError) as exc:
        summary = safe_summary(
            mode=args.mode,
            max_items=args.max_items,
            records_available=0,
        )
        summary["error"] = str(exc)
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as exc:
        summary = safe_summary(
            mode=args.mode,
            max_items=args.max_items,
            records_available=0,
        )
        summary["error"] = f"{type(exc).__name__}: {exc}"
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
