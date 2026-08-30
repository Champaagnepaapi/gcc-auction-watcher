#!/usr/bin/env python3
"""Read-only PSA Set Registry corroboration for Cardova legacy set candidates.

This probe does not create an identity resolver. It reuses the existing Cardova
legacy cohort probe, which already requires per-row exact English name <-> dexId
agreement, one unique Japanese TCGdex set across the cohort, and immutable
source proof for every selected card.

A second, independent set-level gate is then applied for a small reviewed set of
PSA Set Registry pages. PSA issue-year semantics are kept separate from the
actual Japanese set release year. Cardova's exact provider set label must match
the reviewed label for every row. Legacy rows may lack a preserved provider
title; when a title is present it must carry the reviewed PSA issue-year/set
token. The immutable TCGdex set file must independently match the reviewed item
count and release year. If PSA's issue year differs from the release year, an
independent reviewed release-year source is mandatory.

The result remains candidate-only. No macro identity, microvariant or canonical
link is promoted here. The reviewed evidence is deliberately set-level, not a
card-by-card alias table, and unsupported labels fail closed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
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
import robot_kb_cardova_legacy_set_cohort_probe as cohort  # noqa: E402
import v4_tcgdex_source_pinned_finish as source_finish  # noqa: E402


DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
HARD_MAX_GROUPS = 40
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_MAX_SOURCE_REQUESTS = 128
_SAFE_SET_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@dataclass(frozen=True)
class ReviewedPsaSetEvidence:
    provider_set_label: str
    psa_set_title: str
    provider_set_token: str
    psa_issue_year: int
    required_items: int
    source_url: str
    pinned_release_year: int
    release_year_source_url: str = ""
    release_year_source_note: str = ""
    observed_at: str = "2026-08-30"


# Public set-level evidence reviewed independently on 2026-08-30. PSA provides
# the issue title/year and checklist size. `pinned_release_year` is a distinct
# semantic field: it is never inferred from PSA's issue year. Where those years
# differ (Neo Genesis), an independent official Pokémon release-history source
# is recorded explicitly.
_REVIEWED_PSA_SET_EVIDENCE: Mapping[str, ReviewedPsaSetEvidence] = {
    "Pokemon TCG: Japanese Basic": ReviewedPsaSetEvidence(
        provider_set_label="Pokemon TCG: Japanese Basic",
        psa_set_title="1996 Pokemon Japanese Basic",
        provider_set_token="Basic",
        psa_issue_year=1996,
        required_items=102,
        source_url="https://www.psacard.com/psasetregistry/tcg/company-sets/1996-pokemon-japanese-basic/16381",
        pinned_release_year=1996,
    ),
    "Pokemon TCG: Japanese Jungle": ReviewedPsaSetEvidence(
        provider_set_label="Pokemon TCG: Japanese Jungle",
        psa_set_title="1997 Pokemon Japanese Jungle",
        provider_set_token="Jungle",
        psa_issue_year=1997,
        required_items=48,
        source_url="https://www.psacard.com/psasetregistry/tcg/company-sets/1997-pokemon-japanese-jungle/17078",
        pinned_release_year=1997,
    ),
    "Pokemon TCG: Japanese Rocket": ReviewedPsaSetEvidence(
        provider_set_label="Pokemon TCG: Japanese Rocket",
        psa_set_title="1997 Pokemon Japanese Rocket",
        provider_set_token="Rocket",
        psa_issue_year=1997,
        required_items=65,
        source_url="https://www.psacard.com/psasetregistry/tcg/company-sets/1997-pokemon-japanese-rocket/17747",
        pinned_release_year=1997,
    ),
    "Pokemon TCG: Japanese neo Gold, Silver, to a New World...": ReviewedPsaSetEvidence(
        provider_set_label="Pokemon TCG: Japanese neo Gold, Silver, to a New World...",
        psa_set_title="1999 Pokemon Japanese Neo Genesis",
        provider_set_token="Neo",
        psa_issue_year=1999,
        required_items=96,
        source_url="https://www.psacard.com/psasetregistry/tcg/company-sets/1999-pokemon-japanese-neo-genesis/17089",
        pinned_release_year=2000,
        release_year_source_url="https://www.pokemon-card.com/ex/25th/chronicle/",
        release_year_source_note=(
            "Official Pokemon Card Game 25th Chronicle places expansion pack "
            "第1弾『金、銀、新世界へ...』 in 2000"
        ),
    ),
}


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _provider_title_supports_registry(
    record: Mapping[str, Any], evidence: ReviewedPsaSetEvidence
) -> tuple[bool, str]:
    title = _norm(record.get("provider_title"))
    if not title:
        # Legacy Cardova SOLD payloads can legitimately lack this optional
        # surface. Exact provider set-label equality remains mandatory below.
        return True, "PROVIDER_TITLE_ABSENT_NO_CONFLICT"

    card_name = _norm(record.get("card_name"))
    number = _norm(record.get("collector_number"))
    grade = _norm(record.get("grade"))
    if not (card_name and number and grade):
        return False, "PROVIDER_TITLE_IDENTITY_FIELDS_MISSING"

    prefix = f"{evidence.psa_issue_year} Pokemon Japanese "
    if not title.casefold().startswith(prefix.casefold()):
        return False, "PROVIDER_TITLE_PSA_YEAR_PREFIX_MISMATCH"
    if f" {card_name} ".casefold() not in f" {title} ".casefold():
        return False, "PROVIDER_TITLE_CARD_NAME_MISMATCH"

    tail = f" {evidence.provider_set_token} {number} PSA {grade}"
    if tail.casefold() not in title.casefold():
        return False, "PROVIDER_TITLE_PSA_SET_TOKEN_MISMATCH"
    return True, "PROVIDER_TITLE_PSA_SET_TOKEN_EXACT"


def _set_source_path(set_id: str) -> str:
    if not _SAFE_SET_ID.fullmatch(set_id):
        return ""
    series = source_finish._asia_series_for_set_id(set_id)
    if not series:
        return ""
    return f"data-asia/{series}/{set_id}.ts"


def _parse_pinned_set_metadata(text: str, *, set_id: str) -> tuple[Optional[dict[str, Any]], str]:
    raw = str(text or "")
    id_match = re.search(r"\bid\s*:\s*['\"]([^'\"]+)['\"]", raw)
    count_match = re.search(r"\bofficial\s*:\s*(\d{1,4})\b", raw)
    date_match = re.search(r"\breleaseDate\s*:\s*['\"](\d{4})-(\d{2})-(\d{2})['\"]", raw)
    if not (id_match and count_match and date_match):
        return None, "PINNED_SET_METADATA_MALFORMED"
    if id_match.group(1) != set_id:
        return None, "PINNED_SET_ID_CONFLICT"
    return {
        "set_id": set_id,
        "official_count": int(count_match.group(1)),
        "release_year": int(date_match.group(1)),
        "release_date": "-".join(date_match.groups()),
    }, "PINNED_SET_METADATA_EXACT"


def _release_year_evidence_complete(evidence: ReviewedPsaSetEvidence) -> bool:
    if evidence.psa_issue_year == evidence.pinned_release_year:
        return True
    return bool(_norm(evidence.release_year_source_url))


def corroborate_group(
    group: Mapping[str, Any],
    original_records: Mapping[str, Mapping[str, Any]],
    *,
    source_fetcher: Callable[[str], str],
) -> tuple[Optional[dict[str, Any]], str]:
    label = _norm(group.get("provider_set_label"))
    evidence = _REVIEWED_PSA_SET_EVIDENCE.get(label)
    if evidence is None:
        return None, "PSA_SET_REGISTRY_EVIDENCE_UNAVAILABLE"
    if not _release_year_evidence_complete(evidence):
        return None, "RELEASE_YEAR_SEMANTICS_EVIDENCE_MISSING"
    if group.get("provider_name_dexid_exact_match_for_all_rows") is not True:
        return None, "COHORT_NAME_DEX_GATE_NOT_PROVEN"
    if group.get("macro_identity_exact") is not False:
        return None, "INPUT_ALREADY_PROMOTED_UNEXPECTEDLY"

    candidate_rows = group.get("records")
    if not isinstance(candidate_rows, list) or not candidate_rows:
        return None, "COHORT_RECORDS_MISSING"

    for candidate in candidate_rows:
        if not isinstance(candidate, Mapping):
            return None, "COHORT_RECORD_MALFORMED"
        native_id = _norm(candidate.get("source_native_record_id"))
        original = original_records.get(native_id)
        if original is None:
            return None, "ORIGINAL_RECORD_NOT_FOUND"
        if _norm(original.get("set_name")) != evidence.provider_set_label:
            return None, "PROVIDER_SET_LABEL_CONFLICT"
        ok, reason = _provider_title_supports_registry(original, evidence)
        if not ok:
            return None, reason

    set_id = _norm(group.get("tcgdex_set_id_candidate"))
    path = _set_source_path(set_id)
    if not path:
        return None, "PINNED_SET_PATH_UNPROVEN"
    try:
        text = source_fetcher(path)
    except legacy.LegacyDexProviderError:
        raise
    except Exception as error:
        raise legacy.LegacyDexProviderError(
            f"PINNED_SET_SOURCE_{type(error).__name__}"
        ) from error

    metadata, reason = _parse_pinned_set_metadata(text, set_id=set_id)
    if metadata is None:
        return None, reason
    if metadata["official_count"] != evidence.required_items:
        return None, "PSA_REGISTRY_PINNED_COUNT_CONFLICT"
    if metadata["release_year"] != evidence.pinned_release_year:
        return None, "PSA_REGISTRY_PINNED_YEAR_CONFLICT"

    return {
        "provider_set_label": label,
        "tcgdex_set_id_candidate": set_id,
        "records_corroborated": len(candidate_rows),
        "reviewed_psa_set_registry_title": evidence.psa_set_title,
        "reviewed_psa_issue_year": evidence.psa_issue_year,
        "reviewed_psa_set_registry_required_items": evidence.required_items,
        "reviewed_psa_set_registry_url": evidence.source_url,
        "reviewed_psa_set_registry_observed_at": evidence.observed_at,
        "reviewed_release_year": evidence.pinned_release_year,
        "reviewed_release_year_source_url": evidence.release_year_source_url,
        "reviewed_release_year_source_note": evidence.release_year_source_note,
        "psa_issue_year_used_as_release_year": False,
        "provider_set_label_exact_for_all_rows": True,
        "provider_titles_if_present_support_registry_set": True,
        "pinned_set_source_path": path,
        "pinned_set_source_commit": source_finish._SOURCE_COMMIT,
        "pinned_set_official_count": metadata["official_count"],
        "pinned_set_release_date": metadata["release_date"],
        "corroboration_status": "PSA_REGISTRY_AND_PINNED_SET_CORROBORATED_CANDIDATE_ONLY",
        "macro_identity_exact": False,
        "microvariant_exact": False,
        "exact_identity_link_candidate": False,
    }, "PSA_REGISTRY_AND_PINNED_SET_CORROBORATED_CANDIDATE_ONLY"


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_groups: int,
    min_distinct_dexids: int,
    dex_searcher: Optional[Callable[[int], Sequence[Mapping[str, Any]]]] = None,
    english_dex_searcher: Optional[Callable[[int], Sequence[Mapping[str, Any]]]] = None,
    source_fetcher: Optional[Callable[[str], str]] = None,
) -> Mapping[str, Any]:
    fetcher = source_fetcher or legacy.PinnedSourceFetcher(
        max_requests=DEFAULT_MAX_SOURCE_REQUESTS
    )
    cohort_result = cohort.run_records(
        records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        dex_searcher=dex_searcher,
        english_dex_searcher=english_dex_searcher,
        source_fetcher=fetcher,
    )
    originals = {
        _norm(record.get("source_native_record_id")): record
        for record in records
        if _norm(record.get("source_native_record_id"))
    }

    corroborated: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    for group in cohort_result.get("groups", []):
        try:
            result, reason = corroborate_group(
                group, originals, source_fetcher=fetcher
            )
        except legacy.LegacyDexProviderError as error:
            blocked[str(error)] += 1
            continue
        if result is None:
            blocked[reason] += 1
            continue
        corroborated.append(result)

    return {
        "cohort_groups_source_pinned_unique": cohort_result.get("groups_source_pinned_unique", 0),
        "cohort_candidate_records": cohort_result.get("candidate_records", 0),
        "psa_registry_evidence_labels_available": len(_REVIEWED_PSA_SET_EVIDENCE),
        "psa_registry_corroborated_groups": len(corroborated),
        "psa_registry_corroborated_records": sum(
            int(item["records_corroborated"]) for item in corroborated
        ),
        "macro_identity_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "still_unresolved_count": len(records),
        "corroboration_blocked": dict(sorted(blocked.items())),
        "corroborated_groups": corroborated,
        "cohort": cohort_result,
        "pinned_source_requests": int(getattr(fetcher, "requests", 0)),
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PSA_SET_REGISTRY_CORROBORATION",
        "database_read_only_transaction": True,
        "reviewed_psa_set_registry_evidence_used": True,
        "psa_registry_live_fetch_used": False,
        "psa_registry_evidence_observed_at": "2026-08-30",
        "set_level_evidence_only": True,
        "provider_title_required": False,
        "provider_title_conflict_blocks": True,
        "psa_issue_year_used_as_release_year": False,
        "independent_release_year_source_required_when_years_differ": True,
        "card_alias_table_used": False,
        "translation_assumed": False,
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
        description="Read-only PSA Set Registry corroboration for Cardova legacy candidates"
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
