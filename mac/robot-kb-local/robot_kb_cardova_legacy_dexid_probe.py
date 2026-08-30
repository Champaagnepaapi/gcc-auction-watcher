#!/usr/bin/env python3
"""Read-only source-pinned probe for legacy Japanese Cardova numeric labels.

Cardova legacy Japanese PSA rows frequently expose a numeric ``card_number``
that is not the TCGdex set-local id.  Reviewed examples such as Japanese Fossil
Haunter ``#093`` and neo2 Weedle ``#013`` line up instead with TCGdex ``dexId``.
That observation is not promoted to a universal provider semantic here.

This diagnostic therefore remains candidate-only.  It accepts only a narrow
set-id derivation that is structural in Cardova's verbose label (``neo 1`` ..
``neo 4`` -> ``neo1`` .. ``neo4``), queries TCGdex by dexId for retrieval, then
requires exactly one candidate in that set and verifies the exact card source
file against the immutable TCGdex cards-database commit already pinned by V4.

No provider English name is translated or matched to the Japanese source name.
No canonical identity/link is written and no candidate is exact-identity
eligible.  PostgreSQL access reuses the existing READ ONLY Cardova recovery
reader.  No V4 economic use, notification, purchase, bid, offer, checkout or
payment occurs.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402
import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402
import v4_canonical_multimarket as canonical  # noqa: E402
import v4_tcgdex_source_pinned_finish as source_finish  # noqa: E402


DEFAULT_MAX_RECORDS = 200
HARD_MAX_RECORDS = 500
_MAX_SOURCE_REQUESTS = 32
_SAFE_LOCAL = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
_NEO_LABEL = re.compile(
    r"^Pokemon\s+TCG:\s*Japanese\s+neo\s+([1-4])(?:\s|$)",
    flags=re.IGNORECASE,
)


class LegacyDexProviderError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def structural_legacy_set_id(set_name: object) -> tuple[str, str]:
    """Return a set id only when the Cardova label itself encodes neo N."""

    raw = _norm(set_name)
    match = _NEO_LABEL.match(raw)
    if match is None:
        return "", "STRUCTURAL_SET_ID_UNPROVEN"
    set_id = f"neo{match.group(1)}"
    return set_id, "STRUCTURAL_NEO_SET_ID"


def numeric_dex_candidate(number: object) -> tuple[Optional[int], str]:
    raw = _norm(number).lstrip("#")
    if not re.fullmatch(r"\d{1,4}", raw):
        return None, "NUMERIC_DEX_CANDIDATE_ABSENT"
    value = int(raw)
    if value <= 0 or value > 1025:
        return None, "NUMERIC_DEX_CANDIDATE_OUT_OF_RANGE"
    return value, "NUMERIC_DEX_CANDIDATE"


def _default_dex_search(dex_id: int) -> Sequence[Mapping[str, Any]]:
    try:
        status, payload, _headers = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/ja/cards",
            params={"dexId": f"eq:{dex_id}"},
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        raise LegacyDexProviderError(
            f"TCGDEX_DEX_SEARCH_{type(error).__name__}"
        ) from error
    if status != 200:
        raise LegacyDexProviderError(f"TCGDEX_DEX_SEARCH_HTTP_{status}")
    return canonical._extract_list_payload(payload)


class PinnedSourceFetcher:
    def __init__(self, *, max_requests: int = _MAX_SOURCE_REQUESTS):
        self.max_requests = max(0, int(max_requests))
        self.requests = 0
        self.cache: dict[str, str] = {}

    def __call__(self, path: str) -> str:
        if path in self.cache:
            return self.cache[path]
        if self.requests >= self.max_requests:
            raise LegacyDexProviderError("PINNED_SOURCE_BUDGET_EXHAUSTED")
        self.requests += 1
        try:
            response = source_finish._SESSION.get(
                f"{source_finish._SOURCE_RAW_BASE}/{path}",
                timeout=source_finish._SOURCE_TIMEOUT_SECONDS,
            )
        except Exception as error:
            raise LegacyDexProviderError(
                f"PINNED_SOURCE_{type(error).__name__}"
            ) from error
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            raise LegacyDexProviderError(f"PINNED_SOURCE_HTTP_{status}")
        text = str(getattr(response, "text", "") or "")
        if not text or len(text) > 250_000:
            raise LegacyDexProviderError("PINNED_SOURCE_MALFORMED_RESPONSE")
        self.cache[path] = text
        return text


def _source_proves_set_dex(text: str, *, set_id: str, dex_id: int) -> bool:
    set_import = re.compile(
        rf"^\s*import\s+Set\s+from\s+['\"]\.\./{re.escape(set_id)}['\"]\s*;?\s*$",
        flags=re.MULTILINE,
    )
    if set_import.search(str(text or "")) is None:
        return False
    if re.search(r"\bcategory\s*:\s*['\"]Pokemon['\"]", text) is None:
        return False
    dex_match = re.search(r"\bdexId\s*:\s*\[([^\]]+)\]", text)
    if dex_match is None:
        return False
    values = {
        int(token)
        for token in re.findall(r"\b\d{1,4}\b", dex_match.group(1))
        if 0 < int(token) <= 1025
    }
    return dex_id in values


def probe_record(
    record: Mapping[str, Any],
    *,
    dex_searcher: Callable[[int], Sequence[Mapping[str, Any]]] = _default_dex_search,
    source_fetcher: Callable[[str], str],
) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason
    if _norm(record.get("language")).casefold() != "japanese":
        return None, "JAPANESE_REQUIRED"

    set_id, set_reason = structural_legacy_set_id(record.get("set_name"))
    if not set_id:
        return None, set_reason
    dex_id, dex_reason = numeric_dex_candidate(record.get("collector_number"))
    if dex_id is None:
        return None, dex_reason

    try:
        briefs = list(dex_searcher(dex_id))
    except LegacyDexProviderError:
        raise
    except Exception as error:
        raise LegacyDexProviderError(
            f"TCGDEX_DEX_SEARCH_{type(error).__name__}"
        ) from error

    prefix = f"{set_id}-"
    candidates: dict[str, str] = {}
    for brief in briefs:
        card_id = _norm(brief.get("id"))
        if not card_id.startswith(prefix):
            continue
        local_id = card_id[len(prefix):]
        if not local_id or not _SAFE_LOCAL.fullmatch(local_id):
            raise LegacyDexProviderError("TCGDEX_DEX_SEARCH_MALFORMED_CARD_ID")
        candidates[card_id] = local_id

    if not candidates:
        return None, "SET_DEXID_CANDIDATE_NOT_FOUND"
    if len(candidates) != 1:
        return None, "SET_DEXID_CANDIDATE_AMBIGUOUS"

    card_id, local_id = next(iter(candidates.items()))
    series = source_finish._asia_series_for_set_id(set_id)
    if series != "neo":
        return None, "PINNED_ASIA_SERIES_UNPROVEN"
    source_path = f"data-asia/{series}/{set_id}/{local_id}.ts"
    text = source_fetcher(source_path)
    if not _source_proves_set_dex(text, set_id=set_id, dex_id=dex_id):
        return None, "PINNED_SOURCE_SET_DEXID_CONFLICT"

    return {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "card_name_provider_claim": _norm(record.get("card_name")),
        "collector_number_provider_claim": _norm(record.get("collector_number")),
        "set_name_provider_claim": _norm(record.get("set_name")),
        "language": "Japanese",
        "grader": _norm(record.get("grader")),
        "grade": _norm(record.get("grade")),
        "structural_set_id": set_id,
        "dex_id_candidate": dex_id,
        "tcgdex_card_id_candidate": card_id,
        "tcgdex_local_id_candidate": local_id,
        "pinned_source_path": source_path,
        "pinned_source_commit": source_finish._SOURCE_COMMIT,
        "pinned_source_set_dexid_proven": True,
        "provider_numeric_semantics_proven": False,
        "candidate_status": "SOURCE_PINNED_SET_DEXID_UNIQUE_CANDIDATE_ONLY",
        "macro_identity_exact": False,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
    }, "SOURCE_PINNED_SET_DEXID_UNIQUE_CANDIDATE_ONLY"


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    dex_searcher: Callable[[int], Sequence[Mapping[str, Any]]] = _default_dex_search,
    source_fetcher: Optional[Callable[[str], str]] = None,
) -> Mapping[str, Any]:
    fetcher = source_fetcher or PinnedSourceFetcher()
    rows: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    structural = 0
    numeric = 0
    for record in records:
        set_id, _ = structural_legacy_set_id(record.get("set_name"))
        if set_id:
            structural += 1
        dex_id, _ = numeric_dex_candidate(record.get("collector_number"))
        if dex_id is not None:
            numeric += 1
        try:
            row, reason = probe_record(
                record,
                dex_searcher=dex_searcher,
                source_fetcher=fetcher,
            )
        except LegacyDexProviderError as error:
            blocked[str(error)] += 1
            continue
        if row is None:
            blocked[reason] += 1
            continue
        rows.append(row)

    return {
        "records_attempted": len(records),
        "structural_neo_set_candidates": structural,
        "numeric_dex_candidates": numeric,
        "source_pinned_unique_dexid_candidate_count": len(rows),
        "macro_identity_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "still_unresolved_count": len(records),
        "blocked": dict(sorted(blocked.items())),
        "records": rows,
        "pinned_source_requests": int(getattr(fetcher, "requests", 0)),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_LEGACY_JP_PINNED_DEXID_CANDIDATE_PROBE",
        "database_read_only_transaction": True,
        "tcgdex_source_commit": source_finish._SOURCE_COMMIT,
        "set_mapping_rule": "STRUCTURAL_CARDOVA_NEO_1_TO_4_ONLY",
        "provider_numeric_semantics_proven": False,
        "dexid_used_as_retrieval_candidate_only": True,
        "provider_name_translation_assumed": False,
        "fuzzy_matching": False,
        "macro_identity_exact": False,
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


def run(database_url: str, *, max_records: int) -> Mapping[str, Any]:
    target = recovery.validate_local_database_url(database_url)
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    probed = run_records(selected["records"])
    return {
        **target,
        **{key: value for key, value in selected.items() if key != "records"},
        **probed,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only source-pinned Cardova legacy dexId candidate probe"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")

    summary = safe_summary()
    code = 1
    try:
        summary.update(
            run(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                max_records=args.max_records,
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
