#!/usr/bin/env python3
"""Read-only cohort probe for legacy Japanese Cardova set labels.

Legacy Cardova PSA rows often expose a numeric ``card_number`` that behaves like
Pokédex ``dexId`` rather than TCGdex set-local id. The existing legacy probe
proves that pattern only for structurally named ``neo 1..4`` labels and keeps it
candidate-only.

This probe addresses the remaining labels without adding a translation table or
card-by-card aliases. Before any cohort inference, each numeric Cardova claim is
gated against TCGdex English cards at that exact dexId: the provider English
card name must occur as an exact whitespace-normalized/case-insensitive name.
This rejects localId-style rows such as ``Pachirisu #017`` instead of pretending
017 is Pachirisu's Pokédex number.

Rows that pass that per-row semantic gate are grouped by the exact Cardova
verbose set label. For every group with at least two distinct proven numeric
candidates, TCGdex Japanese cards are queried by dexId. A set candidate exists
only when exactly one TCGdex set contains exactly one card for every distinct
dexId in that Cardova cohort. Every selected card is then re-proven against the
immutable TCGdex cards-database commit already pinned by V4.

This is deliberately retrieval/candidate evidence only. The exact-name gate is
not treated as universal provider-number semantics and does not promote the set
or card to exact identity. No provider name is translated. No canonical
identity/link is written and there is no V4 economic/notification/transaction
capability.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
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
import robot_kb_cardova_legacy_dexid_probe as legacy  # noqa: E402
import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402
import v4_canonical_multimarket as canonical  # noqa: E402
import v4_tcgdex_source_pinned_finish as source_finish  # noqa: E402


DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
HARD_MAX_GROUPS = 40
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_MAX_DEX_REQUESTS = 96
DEFAULT_MAX_ENGLISH_DEX_REQUESTS = 96
DEFAULT_MAX_SOURCE_REQUESTS = 96
_SAFE_COORDINATE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class CohortProviderError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _split_card_id(card_id: object) -> tuple[str, str]:
    raw = _norm(card_id)
    if "-" not in raw:
        return "", ""
    set_id, local_id = raw.rsplit("-", 1)
    if not (
        set_id
        and local_id
        and _SAFE_COORDINATE.fullmatch(set_id)
        and _SAFE_COORDINATE.fullmatch(local_id)
    ):
        return "", ""
    return set_id, local_id


def _default_english_dex_search(dex_id: int) -> Sequence[Mapping[str, Any]]:
    try:
        status, payload, _headers = canonical._json_get(
            f"{canonical.TCGDEX_BASE_URL}/en/cards",
            params={"dexId": f"eq:{dex_id}"},
            timeout=canonical.TCGDEX_TIMEOUT_SECONDS,
        )
    except Exception as error:
        raise CohortProviderError(
            f"TCGDEX_EN_DEX_SEARCH_{type(error).__name__}"
        ) from error
    if status != 200:
        raise CohortProviderError(f"TCGDEX_EN_DEX_SEARCH_HTTP_{status}")
    return canonical._extract_list_payload(payload)


class BoundedDexSearcher:
    def __init__(
        self,
        *,
        max_requests: int = DEFAULT_MAX_DEX_REQUESTS,
        delegate: Callable[[int], Sequence[Mapping[str, Any]]] = legacy._default_dex_search,
    ):
        self.max_requests = max(0, int(max_requests))
        self.delegate = delegate
        self.requests = 0
        self.cache: dict[int, list[Mapping[str, Any]]] = {}

    def __call__(self, dex_id: int) -> Sequence[Mapping[str, Any]]:
        if dex_id in self.cache:
            return self.cache[dex_id]
        if self.requests >= self.max_requests:
            raise CohortProviderError("TCGDEX_DEX_SEARCH_BUDGET_EXHAUSTED")
        self.requests += 1
        try:
            rows = list(self.delegate(dex_id))
        except legacy.LegacyDexProviderError as error:
            raise CohortProviderError(str(error)) from error
        except CohortProviderError:
            raise
        except Exception as error:
            raise CohortProviderError(
                f"TCGDEX_DEX_SEARCH_{type(error).__name__}"
            ) from error
        self.cache[dex_id] = rows
        return rows


class BoundedEnglishDexSearcher:
    def __init__(
        self,
        *,
        max_requests: int = DEFAULT_MAX_ENGLISH_DEX_REQUESTS,
        delegate: Callable[[int], Sequence[Mapping[str, Any]]] = _default_english_dex_search,
    ):
        self.max_requests = max(0, int(max_requests))
        self.delegate = delegate
        self.requests = 0
        self.cache: dict[int, list[Mapping[str, Any]]] = {}

    def __call__(self, dex_id: int) -> Sequence[Mapping[str, Any]]:
        if dex_id in self.cache:
            return self.cache[dex_id]
        if self.requests >= self.max_requests:
            raise CohortProviderError("TCGDEX_EN_DEX_SEARCH_BUDGET_EXHAUSTED")
        self.requests += 1
        try:
            rows = list(self.delegate(dex_id))
        except CohortProviderError:
            raise
        except Exception as error:
            raise CohortProviderError(
                f"TCGDEX_EN_DEX_SEARCH_{type(error).__name__}"
            ) from error
        self.cache[dex_id] = rows
        return rows


def _candidate_cards_by_set(
    briefs: Sequence[Mapping[str, Any]],
) -> Mapping[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for brief in briefs:
        if not isinstance(brief, Mapping):
            continue
        card_id = _norm(brief.get("id"))
        set_id, local_id = _split_card_id(card_id)
        if not set_id or not local_id:
            continue
        if card_id not in grouped[set_id]:
            grouped[set_id].append(card_id)
    return {key: tuple(values) for key, values in grouped.items()}


def _source_path(set_id: str, local_id: str) -> str:
    series = source_finish._asia_series_for_set_id(set_id)
    if not series:
        return ""
    return f"data-asia/{series}/{set_id}/{local_id}.ts"


def _eligible_numeric_row(record: Mapping[str, Any]) -> tuple[Optional[int], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason
    if _norm(record.get("language")).casefold() != "japanese":
        return None, "JAPANESE_REQUIRED"
    if legacy.structural_legacy_set_id(record.get("set_name"))[0]:
        return None, "STRUCTURAL_NEO_ALREADY_HANDLED"
    dex_id, reason = legacy.numeric_dex_candidate(record.get("collector_number"))
    return dex_id, reason


def _provider_name_matches_dex(
    record: Mapping[str, Any],
    *,
    dex_id: int,
    english_dex_searcher: Callable[[int], Sequence[Mapping[str, Any]]],
) -> tuple[bool, str]:
    provider_name = _norm(record.get("card_name"))
    if not provider_name:
        return False, "PROVIDER_CARD_NAME_MISSING"
    try:
        briefs = list(english_dex_searcher(dex_id))
    except CohortProviderError:
        raise
    except Exception as error:
        raise CohortProviderError(
            f"TCGDEX_EN_DEX_SEARCH_{type(error).__name__}"
        ) from error

    expected = provider_name.casefold()
    exact_names = {
        _norm(brief.get("name")).casefold()
        for brief in briefs
        if isinstance(brief, Mapping) and _norm(brief.get("name"))
    }
    if expected not in exact_names:
        return False, "PROVIDER_NAME_DEXID_EXACT_MISMATCH"
    return True, "PROVIDER_NAME_DEXID_EXACT_MATCH"


def probe_group(
    label: str,
    records: Sequence[Mapping[str, Any]],
    *,
    min_distinct_dexids: int,
    dex_searcher: Callable[[int], Sequence[Mapping[str, Any]]],
    english_dex_searcher: Callable[[int], Sequence[Mapping[str, Any]]],
    source_fetcher: Callable[[str], str],
) -> tuple[Optional[dict[str, Any]], str]:
    by_dex: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for record in records:
        dex_id, reason = _eligible_numeric_row(record)
        if dex_id is None:
            if reason == "STRUCTURAL_NEO_ALREADY_HANDLED":
                continue
            return None, reason
        name_matches, name_reason = _provider_name_matches_dex(
            record,
            dex_id=dex_id,
            english_dex_searcher=english_dex_searcher,
        )
        if not name_matches:
            return None, name_reason
        by_dex[dex_id].append(record)

    if len(by_dex) < min_distinct_dexids:
        return None, "COHORT_DISTINCT_DEXIDS_INSUFFICIENT"

    per_dex: dict[int, Mapping[str, tuple[str, ...]]] = {}
    for dex_id in sorted(by_dex):
        per_dex[dex_id] = _candidate_cards_by_set(dex_searcher(dex_id))
        if not per_dex[dex_id]:
            return None, "COHORT_DEXID_NO_TCGDEX_CANDIDATES"

    common_sets: Optional[set[str]] = None
    for dex_id in sorted(per_dex):
        exact_once = {
            set_id
            for set_id, card_ids in per_dex[dex_id].items()
            if len(card_ids) == 1
        }
        common_sets = exact_once if common_sets is None else common_sets & exact_once

    if not common_sets:
        return None, "COHORT_SET_NOT_FOUND"
    if len(common_sets) != 1:
        return None, "COHORT_SET_AMBIGUOUS"
    set_id = next(iter(common_sets))

    selected_by_dex: dict[int, dict[str, str]] = {}
    source_paths: list[str] = []
    for dex_id in sorted(per_dex):
        card_ids = per_dex[dex_id].get(set_id, ())
        if len(card_ids) != 1:
            return None, "COHORT_SET_CARD_AMBIGUOUS"
        card_id = card_ids[0]
        parsed_set, local_id = _split_card_id(card_id)
        if parsed_set != set_id or not local_id:
            return None, "COHORT_CARD_ID_MALFORMED"
        path = _source_path(set_id, local_id)
        if not path:
            return None, "PINNED_ASIA_SERIES_UNPROVEN"
        try:
            text = source_fetcher(path)
        except legacy.LegacyDexProviderError as error:
            raise CohortProviderError(str(error)) from error
        if not legacy._source_proves_set_dex(text, set_id=set_id, dex_id=dex_id):
            return None, "PINNED_SOURCE_SET_DEXID_CONFLICT"
        selected_by_dex[dex_id] = {
            "tcgdex_card_id_candidate": card_id,
            "tcgdex_local_id_candidate": local_id,
            "pinned_source_path": path,
        }
        if path not in source_paths:
            source_paths.append(path)

    row_candidates: list[dict[str, Any]] = []
    for dex_id in sorted(by_dex):
        proof = selected_by_dex[dex_id]
        for record in by_dex[dex_id]:
            row_candidates.append(
                {
                    "source_native_record_id": _norm(record.get("source_native_record_id")),
                    "card_name_provider_claim": _norm(record.get("card_name")),
                    "collector_number_provider_claim": _norm(record.get("collector_number")),
                    "set_name_provider_claim": label,
                    "grader": _norm(record.get("grader")),
                    "grade": _norm(record.get("grade")),
                    "dex_id_candidate": dex_id,
                    **proof,
                    "provider_name_dexid_exact_match": True,
                    "provider_numeric_semantics_proven": False,
                    "candidate_status": "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY",
                    "macro_identity_exact": False,
                    "microvariant_exact": False,
                    "exact_identity_link_candidate": False,
                }
            )

    return {
        "provider_set_label": label,
        "records_in_group": len(records),
        "distinct_dexids": len(by_dex),
        "tcgdex_set_id_candidate": set_id,
        "pinned_source_commit": source_finish._SOURCE_COMMIT,
        "pinned_source_files_proven": len(source_paths),
        "provider_name_dexid_exact_match_for_all_rows": True,
        "provider_numeric_semantics_proven": False,
        "candidate_status": "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY",
        "macro_identity_exact": False,
        "exact_identity_link_candidate": False,
        "records": row_candidates,
    }, "SOURCE_PINNED_COHORT_SET_DEXID_NAME_GATED_CANDIDATE_ONLY"


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_groups: int,
    min_distinct_dexids: int,
    dex_searcher: Optional[Callable[[int], Sequence[Mapping[str, Any]]]] = None,
    english_dex_searcher: Optional[Callable[[int], Sequence[Mapping[str, Any]]]] = None,
    source_fetcher: Optional[Callable[[str], str]] = None,
) -> Mapping[str, Any]:
    searcher = dex_searcher or BoundedDexSearcher()
    english_searcher = english_dex_searcher or BoundedEnglishDexSearcher()
    fetcher = source_fetcher or legacy.PinnedSourceFetcher(
        max_requests=DEFAULT_MAX_SOURCE_REQUESTS
    )

    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    skipped: Counter[str] = Counter()
    for record in records:
        dex_id, reason = _eligible_numeric_row(record)
        if dex_id is None:
            skipped[reason] += 1
            continue
        label = _norm(record.get("set_name"))
        if not label:
            skipped["SET_LABEL_MISSING"] += 1
            continue
        groups[label].append(record)

    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    selected_groups = ordered[:max_groups]
    results: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    for label, group_records in selected_groups:
        try:
            result, reason = probe_group(
                label,
                group_records,
                min_distinct_dexids=min_distinct_dexids,
                dex_searcher=searcher,
                english_dex_searcher=english_searcher,
                source_fetcher=fetcher,
            )
        except CohortProviderError as error:
            blocked[str(error)] += 1
            continue
        if result is None:
            blocked[reason] += 1
            continue
        results.append(result)

    candidate_rows = sum(len(result["records"]) for result in results)
    return {
        "records_attempted": len(records),
        "eligible_nonstructural_numeric_records": sum(len(v) for v in groups.values()),
        "eligible_set_labels": len(groups),
        "groups_selected": len(selected_groups),
        "groups_source_pinned_unique": len(results),
        "candidate_records": candidate_rows,
        "macro_identity_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "still_unresolved_count": len(records),
        "skipped": dict(sorted(skipped.items())),
        "blocked": dict(sorted(blocked.items())),
        "groups": results,
        "dex_search_requests": int(getattr(searcher, "requests", 0)),
        "english_dex_name_gate_requests": int(getattr(english_searcher, "requests", 0)),
        "pinned_source_requests": int(getattr(fetcher, "requests", 0)),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_LEGACY_JP_SET_COHORT_CANDIDATE_PROBE",
        "database_read_only_transaction": True,
        "tcgdex_source_commit": source_finish._SOURCE_COMMIT,
        "set_mapping_rule": "EXACT_PROVIDER_LABEL_COHORT_INTERSECTION_AFTER_EXACT_EN_NAME_DEXID_GATE",
        "translation_table_used": False,
        "card_alias_table_used": False,
        "provider_name_dexid_exact_gate": True,
        "provider_numeric_semantics_proven": False,
        "dexid_used_as_retrieval_candidate_only": True,
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


def run(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
) -> Mapping[str, Any]:
    target = recovery.validate_local_database_url(database_url)
    selected = recovery._read_unresolved_from_kb(database_url, max_records=max_records)
    probed = run_records(
        selected["records"],
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
    )
    return {
        **target,
        **{key: value for key, value in selected.items() if key != "records"},
        **probed,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Cardova legacy Japanese set-cohort candidate probe"
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
    if not 2 <= args.min_distinct_dexids <= 20:
        parser.error("--min-distinct-dexids must be between 2 and 20")

    summary = safe_summary()
    code = 1
    try:
        summary.update(
            run(
                os.getenv("ROBOT_KB_DATABASE_URL", ""),
                max_records=args.max_records,
                max_groups=args.max_groups,
                min_distinct_dexids=args.min_distinct_dexids,
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
