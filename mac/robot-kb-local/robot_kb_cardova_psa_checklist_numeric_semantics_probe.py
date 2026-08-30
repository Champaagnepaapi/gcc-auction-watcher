#!/usr/bin/env python3
"""Read-only live PSA checklist proof for Cardova legacy numeric semantics.

This probe composes the existing Cardova legacy cohort + PSA set-level
corroboration. It then fetches only four reviewed public PSA Set Registry
composition pages and proves, per candidate row, that PSA lists the same card
name and card number as Cardova. The Cardova number must also equal the already
source-pinned TCGdex dexId candidate for that row.

The proof is deliberately row-scoped. It does not claim that every Cardova
numeric label is a Pokedex/dexId, does not use a card alias table, and does not
promote a commercial microvariant or write a canonical identity.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import urlparse

import requests


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_identity_recovery_batch as recovery  # noqa: E402
import robot_kb_cardova_psa_set_registry_corroboration_probe as set_probe  # noqa: E402


DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
HARD_MAX_GROUPS = 40
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PACING_SECONDS = 1.0


@dataclass(frozen=True)
class ReviewedPsaChecklist:
    provider_set_label: str
    composition_url: str
    expected_title_token: str


_REVIEWED_PSA_CHECKLISTS: Mapping[str, ReviewedPsaChecklist] = {
    "Pokemon TCG: Japanese Basic": ReviewedPsaChecklist(
        provider_set_label="Pokemon TCG: Japanese Basic",
        composition_url=(
            "https://www.psacard.com/psasetregistry/tcg/company-sets/"
            "1996-pokemon-japanese/composition/16381"
        ),
        expected_title_token="1996 Pokemon Japanese Basic",
    ),
    "Pokemon TCG: Japanese Jungle": ReviewedPsaChecklist(
        provider_set_label="Pokemon TCG: Japanese Jungle",
        composition_url=(
            "https://www.psacard.com/psasetregistry/tcg/company-sets/"
            "1997-pokemon-japanese-jungle/composition/17078"
        ),
        expected_title_token="1997 Pokemon Japanese Jungle",
    ),
    "Pokemon TCG: Japanese Rocket": ReviewedPsaChecklist(
        provider_set_label="Pokemon TCG: Japanese Rocket",
        composition_url=(
            "https://www.psacard.com/psasetregistry/tcg/company-sets/"
            "1997-pokemon-japanese-rocket/composition/17747"
        ),
        expected_title_token="1997 Pokemon Japanese Rocket",
    ),
    "Pokemon TCG: Japanese neo Gold, Silver, to a New World...": ReviewedPsaChecklist(
        provider_set_label="Pokemon TCG: Japanese neo Gold, Silver, to a New World...",
        composition_url=(
            "https://www.psacard.com/psasetregistry/tcg/company-sets/"
            "1999-pokemon-japanese-neo-genesis/composition/17089"
        ),
        expected_title_token="1999 Pokemon Japanese Neo Genesis",
    ),
}
_ALLOWED_PSA_URLS = frozenset(
    item.composition_url for item in _REVIEWED_PSA_CHECKLISTS.values()
)


class PsaChecklistError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _numeric_label(value: object) -> Optional[int]:
    raw = _norm(value)
    if raw.startswith("#"):
        raw = raw[1:]
    if not re.fullmatch(r"\d{1,4}", raw):
        return None
    number = int(raw)
    if not 1 <= number <= 2000:
        return None
    return number


def _norm_name(value: object) -> str:
    text = _norm(value).replace("’", "'").replace("`", "'").upper()
    # PSA adds only presentation-level suffixes in these reviewed checklists.
    # Strip those exact trailing suffixes; no substring/fuzzy matching is used.
    previous = None
    while text != previous:
        previous = text
        text = re.sub(r"(?:[- ]HOLO)\s*$", "", text).strip()
        text = re.sub(r"\s+(?:C|U|R)\s*$", "", text).strip()
    return " ".join(text.split())


class _ChecklistHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_h1 = False
        self._in_tr = False
        self._in_td = False
        self._h1_parts: list[str] = []
        self._cell_parts: list[str] = []
        self._row_cells: list[str] = []
        self.rows: list[tuple[str, str]] = []

    @property
    def title(self) -> str:
        return _norm(" ".join(self._h1_parts))

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, Optional[str]]]
    ) -> None:
        del attrs
        if tag == "h1":
            self._in_h1 = True
        elif tag == "tr":
            self._in_tr = True
            self._row_cells = []
        elif tag == "td" and self._in_tr:
            self._in_td = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1":
            self._in_h1 = False
        elif tag == "td" and self._in_td:
            self._in_td = False
            self._row_cells.append(_norm(" ".join(self._cell_parts)))
            self._cell_parts = []
        elif tag == "tr" and self._in_tr:
            self._in_tr = False
            if len(self._row_cells) >= 2:
                self.rows.append((self._row_cells[0], self._row_cells[1]))
            self._row_cells = []

    def handle_data(self, data: str) -> None:
        if self._in_h1:
            self._h1_parts.append(data)
        if self._in_td:
            self._cell_parts.append(data)


def parse_psa_checklist(
    html: str, *, expected_title_token: str
) -> Mapping[str, Any]:
    parser = _ChecklistHtmlParser()
    parser.feed(str(html or ""))
    title = parser.title
    if _norm_name(expected_title_token) not in _norm_name(title):
        raise PsaChecklistError("PSA_CHECKLIST_TITLE_MISMATCH")

    entries: list[dict[str, Any]] = []
    seen: Counter[tuple[str, int]] = Counter()
    for issue, raw_number in parser.rows:
        number = _numeric_label(raw_number)
        name = _norm_name(issue)
        if number is None or not name:
            continue
        key = (name, number)
        seen[key] += 1
        entries.append(
            {"issue": issue, "normalized_name": name, "card_number": number}
        )
    if not entries:
        raise PsaChecklistError("PSA_CHECKLIST_NO_NUMBERED_ROWS")
    return {"title": title, "entries": entries, "counts": dict(seen)}


def _validate_psa_url(url: str) -> None:
    if url not in _ALLOWED_PSA_URLS:
        raise PsaChecklistError("PSA_CHECKLIST_URL_NOT_REVIEWED")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "www.psacard.com":
        raise PsaChecklistError("PSA_CHECKLIST_URL_NOT_REVIEWED")


def default_psa_fetch(
    url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> str:
    _validate_psa_url(url)
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Safari/537.36 RobotPokemonKB/1.0"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=(5.0, float(timeout_seconds)),
            allow_redirects=True,
        )
    except requests.RequestException as error:
        raise PsaChecklistError(
            f"PSA_CHECKLIST_NETWORK_{type(error).__name__}"
        ) from error

    final = urlparse(response.url)
    if final.scheme != "https" or final.netloc != "www.psacard.com":
        raise PsaChecklistError("PSA_CHECKLIST_REDIRECT_OUTSIDE_REVIEWED_HOST")
    if response.status_code in (403, 429):
        raise PsaChecklistError(f"PSA_CHECKLIST_HTTP_{response.status_code}")
    if response.status_code != 200:
        raise PsaChecklistError(f"PSA_CHECKLIST_HTTP_{response.status_code}")
    return response.text


def _cohort_group_map(
    set_result: Mapping[str, Any],
) -> Mapping[str, Mapping[str, Any]]:
    groups = set_result.get("cohort", {}).get("groups", [])
    return {
        _norm(group.get("provider_set_label")): group
        for group in groups
        if isinstance(group, Mapping) and _norm(group.get("provider_set_label"))
    }


def run_records(
    records: Sequence[Mapping[str, Any]],
    *,
    max_groups: int,
    min_distinct_dexids: int,
    dex_searcher: Optional[
        Callable[[int], Sequence[Mapping[str, Any]]]
    ] = None,
    english_dex_searcher: Optional[
        Callable[[int], Sequence[Mapping[str, Any]]]
    ] = None,
    source_fetcher: Optional[Callable[[str], str]] = None,
    psa_fetcher: Optional[Callable[[str], str]] = None,
    pacing_seconds: float = DEFAULT_PACING_SECONDS,
) -> Mapping[str, Any]:
    set_result = set_probe.run_records(
        records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        dex_searcher=dex_searcher,
        english_dex_searcher=english_dex_searcher,
        source_fetcher=source_fetcher,
    )
    cohort_groups = _cohort_group_map(set_result)
    fetch = psa_fetcher or default_psa_fetch

    proven_rows: list[dict[str, Any]] = []
    groups_out: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    pages_fetched = 0
    circuit_open = False

    for set_group in set_result.get("corroborated_groups", []):
        if not isinstance(set_group, Mapping):
            blocked["SET_CORROBORATION_GROUP_MALFORMED"] += 1
            continue
        label = _norm(set_group.get("provider_set_label"))
        reviewed = _REVIEWED_PSA_CHECKLISTS.get(label)
        cohort_group = cohort_groups.get(label)
        if reviewed is None:
            blocked["PSA_CHECKLIST_NOT_REVIEWED"] += 1
            continue
        if cohort_group is None:
            blocked["COHORT_GROUP_NOT_FOUND"] += 1
            continue
        if circuit_open:
            blocked["PSA_CHECKLIST_CIRCUIT_OPEN"] += len(
                cohort_group.get("records", [])
            )
            continue

        try:
            html = fetch(reviewed.composition_url)
            pages_fetched += 1
            checklist = parse_psa_checklist(
                html, expected_title_token=reviewed.expected_title_token
            )
        except PsaChecklistError as error:
            reason = str(error)
            blocked[reason] += len(cohort_group.get("records", []))
            if reason in {
                "PSA_CHECKLIST_HTTP_403",
                "PSA_CHECKLIST_HTTP_429",
            }:
                circuit_open = True
            continue

        if psa_fetcher is None and pacing_seconds > 0:
            time.sleep(float(pacing_seconds))

        group_rows: list[dict[str, Any]] = []
        for candidate in cohort_group.get("records", []):
            if not isinstance(candidate, Mapping):
                blocked["COHORT_RECORD_MALFORMED"] += 1
                continue
            provider_number = _numeric_label(
                candidate.get("collector_number_provider_claim")
            )
            dex_id = candidate.get("dex_id_candidate")
            if provider_number is None or not isinstance(dex_id, int):
                blocked["PROVIDER_NUMBER_OR_DEXID_MALFORMED"] += 1
                continue
            if provider_number != dex_id:
                blocked["PROVIDER_NUMBER_NOT_EQUAL_DEXID_CANDIDATE"] += 1
                continue
            provider_name = _norm_name(
                candidate.get("card_name_provider_claim")
            )
            if not provider_name:
                blocked["PROVIDER_CARD_NAME_MISSING"] += 1
                continue
            key = (provider_name, provider_number)
            match_count = int(checklist["counts"].get(key, 0))
            if match_count == 0:
                blocked["PSA_CHECKLIST_NAME_NUMBER_NOT_FOUND"] += 1
                continue
            if match_count != 1:
                blocked["PSA_CHECKLIST_NAME_NUMBER_AMBIGUOUS"] += 1
                continue

            row = {
                "source_native_record_id": _norm(
                    candidate.get("source_native_record_id")
                ),
                "provider_set_label": label,
                "tcgdex_set_id_candidate": _norm(
                    set_group.get("tcgdex_set_id_candidate")
                ),
                "tcgdex_card_id_candidate": _norm(
                    candidate.get("tcgdex_card_id_candidate")
                ),
                "provider_card_name": _norm(
                    candidate.get("card_name_provider_claim")
                ),
                "provider_card_number": provider_number,
                "tcgdex_dex_id_candidate": dex_id,
                "psa_checklist_url": reviewed.composition_url,
                "psa_checklist_title": checklist["title"],
                "psa_name_number_exact_match": True,
                "provider_number_equals_tcgdex_dexid": True,
                "provider_numeric_semantics_proven_for_row": True,
                "macro_identity_exact_candidate": True,
                "macro_identity_exact": False,
                "microvariant_exact": False,
                "exact_identity_link_candidate": False,
            }
            proven_rows.append(row)
            group_rows.append(row)

        total_group_rows = len(cohort_group.get("records", []))
        groups_out.append(
            {
                "provider_set_label": label,
                "tcgdex_set_id_candidate": _norm(
                    set_group.get("tcgdex_set_id_candidate")
                ),
                "candidate_records": total_group_rows,
                "numeric_semantics_proven_records": len(group_rows),
                "numeric_semantics_proven_for_all_rows": (
                    len(group_rows) == total_group_rows
                ),
                "psa_checklist_url": reviewed.composition_url,
                "psa_checklist_title": checklist["title"],
            }
        )

    return {
        "set_corroboration_groups": set_result.get(
            "psa_registry_corroborated_groups", 0
        ),
        "set_corroboration_records": set_result.get(
            "psa_registry_corroborated_records", 0
        ),
        "psa_checklist_pages_reviewed": len(_REVIEWED_PSA_CHECKLISTS),
        "psa_checklist_pages_fetched": pages_fetched,
        "psa_checklist_circuit_open": circuit_open,
        "provider_numeric_semantics_proven_records": len(proven_rows),
        "macro_identity_exact_candidate_count": len(proven_rows),
        "macro_identity_exact_count": 0,
        "microvariant_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "still_unresolved_count": len(records),
        "blocked": dict(sorted(blocked.items())),
        "groups": groups_out,
        "records": proven_rows,
        "set_corroboration": set_result,
    }


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_PSA_CHECKLIST_NUMERIC_SEMANTICS",
        "database_read_only_transaction": True,
        "psa_public_checklist_live_fetch": True,
        "psa_reviewed_pages_max": 4,
        "psa_auth_used": False,
        "psa_cookie_or_session_imported": False,
        "card_alias_table_used": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "psa_name_normalization": (
            "CASE_WHITESPACE_AND_TRAILING_HOLO_RARITY_SUFFIX_ONLY"
        ),
        "provider_numeric_semantics_global_claim": False,
        "provider_numeric_semantics_row_scoped_only": True,
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
    selected = recovery._read_unresolved_from_kb(
        database_url, max_records=max_records
    )
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
        description=(
            "Read-only live PSA checklist proof for Cardova legacy numeric semantics"
        )
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument(
        "--min-distinct-dexids", type=int, default=DEFAULT_MIN_DISTINCT_DEXIDS
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(
            f"--max-records must be between 1 and {HARD_MAX_RECORDS}"
        )
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
