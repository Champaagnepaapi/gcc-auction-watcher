#!/usr/bin/env python3
"""Read-only PSA proof for Cardova Japanese Basic No Rarity printing.

This diagnostic starts from the already-bounded Cardova macro + finish proof.
It targets only rows whose provider material surface is exactly
``No Rarity Original Print`` and independently checks the exact card name +
provider card number against PSA's reviewed public
``1996 Pokemon Japanese Basic No Rarity Symbol`` checklist.

The PSA checklist can corroborate only the printing axis ``no_rarity_symbol``.
The provider phrase ``Original Print`` is not promoted to an edition claim and
``No Rarity`` is never re-labelled as First Edition. A unique finish still has
to come from the pinned TCGdex card file selected by the bounded macro proof.

Even when printing and finish are both exact, edition/special-finish/variant
applicability remain open here. Therefore this probe never creates a complete
commercial microvariant, canonical identity link, V4 economic input,
notification, Robot KB write or commerce action.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
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

import robot_kb_cardova_legacy_macro_finish_probe as finish_probe  # noqa: E402
import robot_kb_cardova_psa_checklist_numeric_semantics_probe as checklist_probe  # noqa: E402


SOURCE_COMMIT = finish_probe.SOURCE_COMMIT
BASIC_PROVIDER_SET = "Pokemon TCG: Japanese Basic"
BASIC_TCGDEX_SET = "PMCG1"
PROVIDER_NO_RARITY_TOKEN = "no rarity original print"
PSA_NO_RARITY_URL = (
    "https://www.psacard.com/psasetregistry/tcg/company-sets/"
    "1996-pokemon-japanese-basic-no-rarity-symbol/composition/19646"
)
PSA_NO_RARITY_TITLE = "1996 Pokemon Japanese Basic No Rarity Symbol"
DEFAULT_MAX_RECORDS = 500
HARD_MAX_RECORDS = 500
DEFAULT_MAX_GROUPS = 20
HARD_MAX_GROUPS = 40
DEFAULT_MIN_DISTINCT_DEXIDS = 2
DEFAULT_TIMEOUT_SECONDS = 20.0
DEFAULT_PACING_SECONDS = 1.0
_ALLOWED_FINISHES = frozenset({"normal", "holo", "reverse"})


class NoRarityProofError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _token(value: object) -> str:
    return _norm(value).casefold()


def _is_exact_no_rarity_candidate(row: Mapping[str, Any]) -> bool:
    opaque = row.get("provider_opaque_material_tokens")
    if not isinstance(opaque, Sequence) or isinstance(opaque, (str, bytes)):
        return False
    tokens = tuple(_token(value) for value in opaque if _token(value))
    return (
        row.get("macro_identity_exact") is True
        and row.get("microvariant_exact") is False
        and row.get("exact_identity_link_candidate") is False
        and _norm(row.get("provider_set_label")) == BASIC_PROVIDER_SET
        and _norm(row.get("tcgdex_set_id")) == BASIC_TCGDEX_SET
        and _norm(row.get("pinned_source_commit")) == SOURCE_COMMIT
        and tokens == (PROVIDER_NO_RARITY_TOKEN,)
    )


def _validate_psa_url(url: str) -> None:
    if url != PSA_NO_RARITY_URL:
        raise NoRarityProofError("PSA_NO_RARITY_URL_NOT_REVIEWED")
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc != "www.psacard.com":
        raise NoRarityProofError("PSA_NO_RARITY_URL_NOT_REVIEWED")


def default_psa_fetch(
    url: str, *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
) -> str:
    """Fetch only the one reviewed public PSA No Rarity composition page."""

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
        raise NoRarityProofError(
            f"PSA_NO_RARITY_NETWORK_{type(error).__name__}"
        ) from error

    final = urlparse(response.url)
    if final.scheme != "https" or final.netloc != "www.psacard.com":
        raise NoRarityProofError("PSA_NO_RARITY_REDIRECT_OUTSIDE_REVIEWED_HOST")
    if response.status_code in (403, 429):
        raise NoRarityProofError(f"PSA_NO_RARITY_HTTP_{response.status_code}")
    if response.status_code != 200:
        raise NoRarityProofError(f"PSA_NO_RARITY_HTTP_{response.status_code}")
    return response.text


def _candidate_finish(row: Mapping[str, Any]) -> tuple[bool, str]:
    choices = row.get("source_finish_choices")
    if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)):
        return False, ""
    normalized = tuple(_token(value) for value in choices if _token(value))
    if len(normalized) != 1 or normalized[0] not in _ALLOWED_FINISHES:
        return False, ""
    return True, normalized[0]


def _prove_row(
    row: Mapping[str, Any], checklist: Mapping[str, Any]
) -> tuple[Optional[dict[str, Any]], str]:
    if not _is_exact_no_rarity_candidate(row):
        return None, "NOT_EXACT_NO_RARITY_CANDIDATE"

    provider_number = checklist_probe._numeric_label(
        row.get("collector_number_provider_claim")
    )
    provider_name = checklist_probe._norm_name(row.get("card_name_provider_claim"))
    if provider_number is None or not provider_name:
        return None, "PROVIDER_NAME_OR_NUMBER_MALFORMED"

    key = (provider_name, provider_number)
    match_count = int(checklist.get("counts", {}).get(key, 0))
    if match_count == 0:
        return None, "PSA_NO_RARITY_NAME_NUMBER_NOT_FOUND"
    if match_count != 1:
        return None, "PSA_NO_RARITY_NAME_NUMBER_AMBIGUOUS"

    finish_exact, finish = _candidate_finish(row)
    out = dict(row)
    out.update(
        {
            "psa_no_rarity_checklist_url": PSA_NO_RARITY_URL,
            "psa_no_rarity_checklist_title": _norm(checklist.get("title")),
            "psa_no_rarity_name_number_exact_match": True,
            "provider_no_rarity_claim_exact": True,
            "printing_exact": True,
            "printing": "no_rarity_symbol",
            "printing_proof_reason": "PRINTING_EXACT_PROVIDER_PSA_NO_RARITY_CORROBORATED",
            "provider_original_print_wording_proven": False,
            "edition_exact": False,
            "edition": "",
            "no_rarity_is_first_edition": False,
            "finish_exact": bool(finish_exact),
            "finish": finish if finish_exact else "",
            "finish_proof_reason": (
                "FINISH_EXACT_UNIQUE_PINNED_SOURCE_AFTER_MATERIAL_AXIS_SEPARATION"
                if finish_exact
                else _norm(row.get("finish_proof_reason"))
            ),
            "commercial_axes_proven": (
                {"finish": finish, "printing": "no_rarity_symbol"}
                if finish_exact
                else {"printing": "no_rarity_symbol"}
            ),
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
    return out, "PRINTING_EXACT_PROVIDER_PSA_NO_RARITY_CORROBORATED"


def run_records(
    finish_payload: Mapping[str, Any],
    *,
    psa_fetcher: Optional[Callable[[str], str]] = None,
    pacing_seconds: float = DEFAULT_PACING_SECONDS,
) -> Mapping[str, Any]:
    source_rows = finish_payload.get("records")
    if not isinstance(source_rows, list):
        raise ValueError("finish payload has no records list")
    records = [dict(row) for row in source_rows if isinstance(row, Mapping)]
    candidates = [row for row in records if _is_exact_no_rarity_candidate(row)]

    blocked: Counter[str] = Counter()
    pages_fetched = 0
    circuit_open = False
    proven_by_id: dict[str, dict[str, Any]] = {}

    if candidates:
        fetch = psa_fetcher or default_psa_fetch
        try:
            html = fetch(PSA_NO_RARITY_URL)
            pages_fetched = 1
            checklist = checklist_probe.parse_psa_checklist(
                html, expected_title_token=PSA_NO_RARITY_TITLE
            )
        except (NoRarityProofError, checklist_probe.PsaChecklistError) as error:
            reason = str(error)
            blocked[reason] += len(candidates)
            if reason in {
                "PSA_NO_RARITY_HTTP_403",
                "PSA_NO_RARITY_HTTP_429",
            }:
                circuit_open = True
        else:
            if psa_fetcher is None and pacing_seconds > 0:
                time.sleep(float(pacing_seconds))
            for row in candidates:
                proven, reason = _prove_row(row, checklist)
                if proven is None:
                    blocked[reason] += 1
                    continue
                native_id = _norm(proven.get("source_native_record_id"))
                if not native_id:
                    blocked["SOURCE_NATIVE_RECORD_ID_MISSING"] += 1
                    continue
                if native_id in proven_by_id:
                    blocked["SOURCE_NATIVE_RECORD_ID_DUPLICATE"] += 1
                    proven_by_id.pop(native_id, None)
                    continue
                proven_by_id[native_id] = proven

    output_rows: list[dict[str, Any]] = []
    for row in records:
        native_id = _norm(row.get("source_native_record_id"))
        output_rows.append(proven_by_id.get(native_id, row))

    return {
        "unresolved_sale_transactions_available": finish_payload.get(
            "unresolved_sale_transactions_available", 0
        ),
        "selected_records": finish_payload.get("selected_records", 0),
        "macro_identity_exact_count": finish_payload.get(
            "macro_identity_exact_count", 0
        ),
        "macro_blocked": finish_payload.get("macro_blocked", {}),
        "no_rarity_candidates": len(candidates),
        "psa_no_rarity_checklist_pages_reviewed": 1,
        "psa_no_rarity_checklist_pages_fetched": pages_fetched,
        "psa_no_rarity_circuit_open": circuit_open,
        "psa_no_rarity_rows_proven": len(proven_by_id),
        "finish_exact_count": sum(1 for row in output_rows if row.get("finish_exact") is True),
        "printing_exact_count": sum(1 for row in output_rows if row.get("printing_exact") is True),
        "microvariant_exact_count": 0,
        "exact_identity_link_candidate_count": 0,
        "blocked": dict(sorted(blocked.items())),
        "records": output_rows,
    }


def run_database(
    database_url: str,
    *,
    max_records: int,
    max_groups: int,
    min_distinct_dexids: int,
    timeout_seconds: float,
    psa_fetcher: Optional[Callable[[str], str]] = None,
    source_fetcher: Optional[Callable[[str], str]] = None,
    pacing_seconds: float = DEFAULT_PACING_SECONDS,
) -> Mapping[str, Any]:
    """Run macro + finish + No Rarity proof from the guarded local DB read path."""

    source = source_fetcher or finish_probe._cached_network_fetcher(timeout_seconds)
    finish_payload = finish_probe.run_database(
        database_url,
        max_records=max_records,
        max_groups=max_groups,
        min_distinct_dexids=min_distinct_dexids,
        source_fetcher=source,
    )
    out = dict(run_records(finish_payload, psa_fetcher=psa_fetcher, pacing_seconds=pacing_seconds))
    for key in (
        "database_scope",
        "database_host_class",
        "database_name",
        "database_port",
        "db_read_blocked",
    ):
        if key in finish_payload:
            out[key] = finish_payload[key]
    return out


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_NO_RARITY_PRINTING_PROOF",
        "database_read_only_transaction": True,
        "source_commit": SOURCE_COMMIT,
        "provider_no_rarity_claim_is_identity_proof_alone": False,
        "psa_checklist_can_prove_printing_only": True,
        "no_rarity_is_first_edition": False,
        "provider_original_print_wording_proven": False,
        "printing_exact_is_partial_identity_only": True,
        "microvariant_exact": False,
        "canonical_link_written": False,
        "robot_kb_write": False,
        "sale_transaction_stored": False,
        "sale_transaction_ready": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove Cardova Japanese Basic No Rarity printing read-only"
    )
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--max-groups", type=int, default=DEFAULT_MAX_GROUPS)
    parser.add_argument(
        "--min-distinct-dexids", type=int, default=DEFAULT_MIN_DISTINCT_DEXIDS
    )
    parser.add_argument(
        "--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--pacing-seconds", type=float, default=DEFAULT_PACING_SECONDS
    )
    args = parser.parse_args(argv)

    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 1 <= args.max_groups <= HARD_MAX_GROUPS:
        parser.error(f"--max-groups must be between 1 and {HARD_MAX_GROUPS}")
    if not 2 <= args.min_distinct_dexids <= 20:
        parser.error("--min-distinct-dexids must be between 2 and 20")
    if not 0.5 <= args.timeout_seconds <= 30.0:
        parser.error("--timeout-seconds must be between 0.5 and 30")
    if not 0 <= args.pacing_seconds <= 5.0:
        parser.error("--pacing-seconds must be between 0 and 5")

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

    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
