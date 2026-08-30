#!/usr/bin/env python3
"""Memory-only compose of exact Cardova identity candidates with the existing P3 SOLD contract.

This module does not write Robot KB and does not create a canonical link. It only
proves that one already-exact commercial identity candidate and one immutable
Cardova paid/completed SOLD source record refer to the same provider row, then
reuses ``robot_kb_cardova_sale_transaction_dry_run.build_p3_sale`` to validate
sale time / hammer-price semantics.

The result is an exact-card SALE candidate for later persistence review, not a
persisted exact sale and not a V4 economic input.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence


SaleBuilder = Callable[[Mapping[str, Any]], tuple[Optional[tuple[Any, Any]], str]]


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _same_number(left: object, right: object) -> bool:
    a = _norm(left).lstrip("#")
    b = _norm(right).lstrip("#")
    if not a or not b:
        return False
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return a.casefold() == b.casefold()


def _language(value: object) -> str:
    token = _norm(value).casefold()
    return {
        "ja": "ja", "jp": "ja", "japanese": "ja",
        "en": "en", "english": "en",
    }.get(token, token)


def _exact_identity(row: Mapping[str, Any]) -> tuple[bool, str]:
    if row.get("macro_identity_exact") is not True:
        return False, "MACRO_IDENTITY_NOT_EXACT"
    if row.get("microvariant_exact") is not True:
        return False, "MICROVARIANT_NOT_EXACT"
    if row.get("exact_identity_link_candidate") is not True:
        return False, "EXACT_IDENTITY_LINK_CANDIDATE_FALSE"
    if row.get("canonical_link_written") is True:
        return False, "CANONICAL_LINK_ALREADY_WRITTEN"
    if not _norm(row.get("source_native_record_id")):
        return False, "SOURCE_ID_MISSING"
    if not _norm(row.get("tcgdex_card_id")):
        return False, "TCGDEX_CARD_ID_MISSING"
    if not _norm(row.get("tcgdex_set_id")) or not _norm(row.get("tcgdex_local_id")):
        return False, "TCGDEX_COORDINATE_MISSING"
    if not _norm(row.get("finish")):
        return False, "FINISH_MISSING"
    return True, "EXACT_IDENTITY_READY"


def _same_provider_identity(identity: Mapping[str, Any], sale: Mapping[str, Any]) -> bool:
    name = _norm(identity.get("card_name_provider_claim") or identity.get("card_name"))
    sale_name = _norm(sale.get("card_name"))
    number = identity.get("collector_number_provider_claim") or identity.get("collector_number")
    sale_number = sale.get("collector_number")
    grader = _norm(identity.get("grader")).casefold()
    sale_grader = _norm(sale.get("grader")).casefold()
    grade = _norm(identity.get("grade"))
    sale_grade = _norm(sale.get("grade"))
    if not name or name.casefold() != sale_name.casefold():
        return False
    if not _same_number(number, sale_number):
        return False
    if not grader or grader != sale_grader:
        return False
    if not grade or grade != sale_grade:
        return False
    identity_language = _language(identity.get("language"))
    sale_language = _language(sale.get("language"))
    if identity_language and sale_language and identity_language != sale_language:
        return False
    return True


def _default_sale_builder(observed_at: str) -> Callable[[Mapping[str, Any]], tuple[Optional[tuple[Any, Any]], str]]:
    import robot_kb_cardova_sale_transaction_dry_run as sale_dry

    def build(record: Mapping[str, Any]) -> tuple[Optional[tuple[Any, Any]], str]:
        return sale_dry.build_p3_sale(record, observed_at=observed_at)

    return build


def compose_exact_sale_candidates(
    sales: Sequence[Mapping[str, Any]],
    identity_rows: Sequence[Mapping[str, Any]],
    *,
    observed_at: Optional[str] = None,
    sale_builder: Optional[Callable[[Mapping[str, Any]], tuple[Optional[tuple[Any, Any]], str]]] = None,
) -> Mapping[str, Any]:
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    builder = sale_builder or _default_sale_builder(observed)

    raw_by_id: dict[str, Mapping[str, Any]] = {}
    duplicate_sales: set[str] = set()
    for sale in sales:
        source_id = _norm(sale.get("source_native_record_id"))
        if not source_id:
            continue
        if source_id in raw_by_id:
            duplicate_sales.add(source_id)
        else:
            raw_by_id[source_id] = sale
    for source_id in duplicate_sales:
        raw_by_id.pop(source_id, None)

    records: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    seen_identity_ids: set[str] = set()

    for identity in identity_rows:
        exact, exact_reason = _exact_identity(identity)
        if not exact:
            blocked[exact_reason] += 1
            continue
        source_id = _norm(identity.get("source_native_record_id"))
        if source_id in seen_identity_ids:
            blocked["DUPLICATE_IDENTITY_SOURCE_ID"] += 1
            continue
        seen_identity_ids.add(source_id)
        if source_id in duplicate_sales:
            blocked["DUPLICATE_SALE_SOURCE_ID"] += 1
            continue
        sale = raw_by_id.get(source_id)
        if sale is None:
            blocked["SALE_SOURCE_ROW_MISSING"] += 1
            continue
        if not _same_provider_identity(identity, sale):
            blocked["SALE_IDENTITY_PROVIDER_CONFLICT"] += 1
            continue

        built, sale_reason = builder(sale)
        if built is None:
            blocked[f"P3_SALE_CONTRACT:{sale_reason}"] += 1
            continue

        try:
            hammer_jpy = int(sale.get("final_bid_jpy"))
        except (TypeError, ValueError):
            blocked["P3_SALE_CONTRACT:FINAL_BID_INVALID"] += 1
            continue

        records.append(
            {
                "source_native_record_id": source_id,
                "tcgdex_card_id": _norm(identity.get("tcgdex_card_id")),
                "tcgdex_set_id": _norm(identity.get("tcgdex_set_id")),
                "tcgdex_local_id": _norm(identity.get("tcgdex_local_id")),
                "card_name": _norm(identity.get("card_name_provider_claim") or identity.get("card_name")),
                "collector_number": _norm(identity.get("collector_number_provider_claim") or identity.get("collector_number")),
                "language": _norm(identity.get("language") or sale.get("language")),
                "grader": _norm(identity.get("grader")),
                "grade": _norm(identity.get("grade")),
                "finish": _norm(identity.get("finish")),
                "printing": _norm(identity.get("printing")),
                "pinned_source_variant_dimensions": dict(identity.get("pinned_source_variant_dimensions") or {}),
                "certification_number": _norm(sale.get("certification_number")),
                "sale_occurred_at": _norm(sale.get("auction_end_at_utc")),
                "hammer_price_jpy": hammer_jpy,
                "price_component": "HAMMER_PRICE",
                "currency": "JPY",
                "p3_sale_contract_valid": True,
                "commercial_identity_exact": True,
                "exact_card_sale_candidate_ready": True,
                "canonical_link_written": False,
                "robot_kb_write": False,
                "sale_transaction_written": False,
                "v4_economic_use": False,
            }
        )

    return {
        "sales_input_count": len(sales),
        "identity_input_count": len(identity_rows),
        "exact_card_sale_candidate_count": len(records),
        "blocked_count": sum(blocked.values()),
        "blocked": dict(sorted(blocked.items())),
        "records": records,
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "MEMORY_ONLY_CARDOVA_EXACT_SALE_CANDIDATE_DRY_RUN",
        "existing_p3_sale_contract_reused": True,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_written": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def _load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{path} must contain object records[]")
    rows = payload["records"]
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{path} records[] must contain objects")
    return list(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Memory-only exact Cardova SOLD candidate compose")
    parser.add_argument("--sales-input", type=Path, required=True)
    parser.add_argument("--identity-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at", default="")
    args = parser.parse_args(argv)

    payload = dict(safe_summary())
    code = 1
    try:
        payload.update(
            compose_exact_sale_candidates(
                _load_records(args.sales_input),
                _load_records(args.identity_input),
                observed_at=_norm(args.observed_at) or None,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
