#!/usr/bin/env python3
"""Read-only Cardova -> official Pokemon Japan printed-coordinate probe.

This diagnostic exists for Japanese promo cards whose exact printed coordinate is
present on Cardova but absent from TCGdex.  It uses only public official
``pokemon-card.com`` endpoints and never invents a Cardova/TCGdex alias.

Required proof chain:

  proven Cardova paid-SOLD row
    -> Japanese language
    -> structurally valid promo coordinate such as ``294/XY-P``
    -> structural official search code (``XY-P`` -> ``XYP``)
    -> official ``resultAPI.php`` enumeration for that set
    -> exactly one official detail page containing the exact printed coordinate

The set-code transform removes only the literal hyphen from an already-proven
``*-P`` namespace.  It is retrieval-only; the final identity proof is the exact
printed coordinate on one unique official detail page.

This probe deliberately does *not* claim a commercial microvariant from the
official page alone.  Exact official macro identity therefore remains separate
from ``exact_card_sale_evidence_ready`` and from ``SALE_TRANSACTION``.  Cardova's
public history also does not prove the exact payment-completion timestamp or an
all-in buyer total.

No Robot KB write, V4 economic use, notification, purchase, bid, offer,
checkout or payment is possible here.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse
import unicodedata

import requests


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_paid_sold_identity as paid_identity  # noqa: E402
import robot_kb_cardova_number_namespace_probe as namespace_probe  # noqa: E402


DEFAULT_MAX_RECORDS = 20
HARD_MAX_RECORDS = 50
DEFAULT_DELAY_SECONDS = 0.35
HARD_MAX_DELAY_SECONDS = 5.0
MAX_RESULT_PAGES = 25
MAX_SET_CARD_IDS = 500
MAX_DETAIL_REQUESTS = 900
OFFICIAL_BASE = "https://www.pokemon-card.com"
OFFICIAL_RESULT_API = f"{OFFICIAL_BASE}/card-search/resultAPI.php"
OFFICIAL_REFERER = f"{OFFICIAL_BASE}/card-search/"
OFFICIAL_HOST = "www.pokemon-card.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0 Safari/537.36"
)
_HEADERS = {"User-Agent": USER_AGENT, "Referer": OFFICIAL_REFERER, "Accept": "application/json,text/html;q=0.9,*/*;q=0.8"}
_SET_CODE_RE = re.compile(r"^[A-Za-z0-9]{2,16}$")
_CARD_ID_RE = re.compile(r"^[0-9]{1,10}$")


class _TextAndHeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.h1_parts: list[str] = []
        self._h1_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag.casefold() == "h1":
            self._h1_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "h1" and self._h1_depth:
            self._h1_depth -= 1

    def handle_data(self, data: str) -> None:
        if data:
            self.parts.append(data)
            if self._h1_depth:
                self.h1_parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self.parts)

    @property
    def heading(self) -> str:
        return " ".join(self.h1_parts)


@dataclass(frozen=True)
class OfficialCoordinateMatch:
    card_id: str
    detail_url: str
    official_name: str
    printed_number: str
    official_set_code: str


class OfficialProviderError(RuntimeError):
    pass


class OfficialBoundError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _compact(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", "", text).strip()


def official_set_code(namespace: object) -> tuple[str, str]:
    """Return the official search code for a structurally proven JP promo namespace.

    ``XY-P`` -> ``XYP``, ``BW-P`` -> ``BWP`` and ``L-P`` -> ``LP`` are not a
    provider alias table.  The only permitted transform is removing the single
    hyphen immediately before the terminal ``P``.
    """

    raw = _norm(namespace)
    if not raw or any(ch.isspace() for ch in raw):
        return "", "OFFICIAL_PROMO_NAMESPACE_MALFORMED"
    if not re.fullmatch(r"[A-Za-z0-9]+-P", raw, flags=re.IGNORECASE):
        return "", "OFFICIAL_NOT_JP_PROMO_NAMESPACE"
    code = raw[:-2] + "P"
    if not _SET_CODE_RE.fullmatch(code):
        return "", "OFFICIAL_SET_CODE_MALFORMED"
    return code, "STRUCTURAL_PROMO_SET_CODE"


def _safe_official_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return parsed.scheme == "https" and parsed.hostname == OFFICIAL_HOST


def _detail_url(card_id: str) -> str:
    if not _CARD_ID_RE.fullmatch(str(card_id or "")):
        raise ValueError("invalid official card id")
    return f"{OFFICIAL_BASE}/card-search/details.php/card/{card_id}"


def extract_exact_coordinate_from_detail(
    html: str,
    *,
    card_id: str,
    local_id: str,
    namespace: str,
    official_code: str,
) -> Optional[OfficialCoordinateMatch]:
    """Accept one detail page only when its visible text has the exact coordinate."""

    parser = _TextAndHeadingParser()
    parser.feed(str(html or ""))
    compact_text = _compact(parser.text).upper()
    target = _compact(f"{local_id}/{namespace}").upper()
    if not target or target not in compact_text:
        return None

    detail_url = _detail_url(card_id)
    official_name = _norm(parser.heading)
    return OfficialCoordinateMatch(
        card_id=str(card_id),
        detail_url=detail_url,
        official_name=official_name,
        printed_number=f"{local_id}/{namespace}",
        official_set_code=official_code,
    )


class OfficialPokemonJpCatalog:
    def __init__(
        self,
        *,
        session: Optional[requests.Session] = None,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        max_detail_requests: int = MAX_DETAIL_REQUESTS,
    ) -> None:
        if not 0 <= delay_seconds <= HARD_MAX_DELAY_SECONDS:
            raise ValueError("delay_seconds out of bounds")
        if not 1 <= max_detail_requests <= MAX_DETAIL_REQUESTS:
            raise ValueError("max_detail_requests out of bounds")
        self.session = session or requests.Session()
        self.delay_seconds = float(delay_seconds)
        self.max_detail_requests = int(max_detail_requests)
        self.detail_requests = 0
        self.result_requests = 0
        self._detail_cache: dict[str, str] = {}
        self._set_card_ids: dict[str, list[str]] = {}

    def _sleep(self) -> None:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

    def _get(self, url: str, *, params: Optional[Mapping[str, str]] = None, json_expected: bool = False) -> Any:
        if not _safe_official_url(url):
            raise OfficialProviderError("OFFICIAL_URL_NOT_ALLOWED")
        try:
            response = self.session.get(url, params=params, headers=_HEADERS, timeout=20)
        except requests.RequestException as error:
            raise OfficialProviderError(f"OFFICIAL_REQUEST_{type(error).__name__}") from error
        if not _safe_official_url(str(getattr(response, "url", url))):
            raise OfficialProviderError("OFFICIAL_REDIRECT_NOT_ALLOWED")
        status = int(getattr(response, "status_code", 0) or 0)
        if status == 429:
            raise OfficialProviderError("OFFICIAL_HTTP_429")
        if status in {401, 403}:
            raise OfficialProviderError(f"OFFICIAL_HTTP_{status}")
        if status != 200:
            raise OfficialProviderError(f"OFFICIAL_HTTP_{status}")
        if json_expected:
            try:
                payload = response.json()
            except ValueError as error:
                raise OfficialProviderError("OFFICIAL_INVALID_JSON") from error
            if not isinstance(payload, Mapping):
                raise OfficialProviderError("OFFICIAL_JSON_NOT_OBJECT")
            return payload
        return str(getattr(response, "text", "") or "")

    def enumerate_set_card_ids(self, official_code: str) -> list[str]:
        cached = self._set_card_ids.get(official_code)
        if cached is not None:
            return list(cached)
        if not _SET_CODE_RE.fullmatch(official_code):
            raise OfficialProviderError("OFFICIAL_SET_CODE_MALFORMED")

        ids: list[str] = []
        seen: set[str] = set()
        page = 1
        while True:
            if page > MAX_RESULT_PAGES:
                raise OfficialBoundError("OFFICIAL_SET_PAGE_BOUND_EXCEEDED")
            payload = self._get(
                OFFICIAL_RESULT_API,
                params={
                    "pg": official_code,
                    "se_ta": "",
                    "page": str(page),
                    "regulation_sidebar_form": "all",
                    "sm_and_keyword": "true",
                },
                json_expected=True,
            )
            self.result_requests += 1
            card_list = payload.get("cardList")
            if card_list is None:
                raise OfficialProviderError("OFFICIAL_CARD_LIST_MISSING")
            if not isinstance(card_list, list):
                raise OfficialProviderError("OFFICIAL_CARD_LIST_MALFORMED")
            for item in card_list:
                if not isinstance(item, Mapping):
                    raise OfficialProviderError("OFFICIAL_CARD_ROW_MALFORMED")
                card_id = _norm(item.get("cardID"))
                if not _CARD_ID_RE.fullmatch(card_id):
                    raise OfficialProviderError("OFFICIAL_CARD_ID_MALFORMED")
                if card_id not in seen:
                    seen.add(card_id)
                    ids.append(card_id)
                    if len(ids) > MAX_SET_CARD_IDS:
                        raise OfficialBoundError("OFFICIAL_SET_CARD_BOUND_EXCEEDED")
            try:
                max_page = int(payload.get("maxPage") or page)
            except (TypeError, ValueError) as error:
                raise OfficialProviderError("OFFICIAL_MAX_PAGE_MALFORMED") from error
            if max_page > MAX_RESULT_PAGES:
                raise OfficialBoundError("OFFICIAL_SET_PAGE_BOUND_EXCEEDED")
            if page >= max_page or not card_list:
                break
            page += 1
            self._sleep()

        self._set_card_ids[official_code] = list(ids)
        return ids

    def detail_html(self, card_id: str) -> str:
        cached = self._detail_cache.get(card_id)
        if cached is not None:
            return cached
        if self.detail_requests >= self.max_detail_requests:
            raise OfficialBoundError("OFFICIAL_DETAIL_REQUEST_BOUND_EXCEEDED")
        url = _detail_url(card_id)
        html = self._get(url, json_expected=False)
        self.detail_requests += 1
        self._detail_cache[card_id] = html
        self._sleep()
        return html

    def lookup_coordinate(self, local_id: str, namespace: str) -> tuple[Optional[OfficialCoordinateMatch], str, int]:
        official_code, code_status = official_set_code(namespace)
        if not official_code:
            return None, code_status, 0
        matches: list[OfficialCoordinateMatch] = []
        for card_id in self.enumerate_set_card_ids(official_code):
            match = extract_exact_coordinate_from_detail(
                self.detail_html(card_id),
                card_id=card_id,
                local_id=local_id,
                namespace=namespace,
                official_code=official_code,
            )
            if match is not None:
                matches.append(match)
                if len(matches) > 1:
                    return None, "OFFICIAL_COORDINATE_AMBIGUOUS", len(matches)
        if not matches:
            return None, "OFFICIAL_COORDINATE_NOT_FOUND", 0
        return matches[0], "OFFICIAL_COORDINATE_EXACT_UNIQUE", 1


def probe_record(
    record: Mapping[str, Any],
    *,
    catalog: OfficialPokemonJpCatalog,
) -> tuple[Optional[dict[str, Any]], str]:
    eligible, reason = paid_identity._eligible_record(record)
    if not eligible:
        return None, reason
    identity = paid_identity.identity_from_record(record)
    language = _norm(identity.language).casefold()
    if language not in {"japanese", "ja", "jp"}:
        return None, "OFFICIAL_JP_LANGUAGE_REQUIRED"

    local_id, namespace, parse_status = namespace_probe.printed_number_namespace(identity.number)
    if not namespace:
        return None, parse_status
    official_code, code_status = official_set_code(namespace)
    if not official_code:
        return None, code_status

    try:
        match, lookup_status, match_count = catalog.lookup_coordinate(local_id, namespace)
    except OfficialBoundError as error:
        return None, str(error)
    except OfficialProviderError as error:
        return None, str(error)
    if match is None:
        return None, lookup_status

    row = {
        "source_native_record_id": _norm(record.get("source_native_record_id")),
        "card_name": identity.name,
        "collector_number": identity.number,
        "language": identity.language,
        "grader": identity.grader,
        "grade": identity.grade,
        "certification_number": _norm(record.get("certification_number")),
        "printed_local_id": local_id,
        "printed_namespace": namespace,
        "official_search_set_code": official_code,
        "official_card_id": match.card_id,
        "official_detail_url": match.detail_url,
        "official_japanese_name": match.official_name,
        "official_printed_number": match.printed_number,
        "official_coordinate_match_count": match_count,
        "macro_identity_status": "EXACT",
        "macro_identity_reason": "POKEMON_JP_OFFICIAL_UNIQUE_PRINTED_COORDINATE",
        "official_catalog_entry_unique": True,
        "microvariant_status": "UNPROVEN",
        "microvariant_reason": "OFFICIAL_COORDINATE_DOES_NOT_PROVE_ALL_COMMERCIAL_VARIANT_AXES",
        "microvariant_exact": False,
        "exact_card_sale_evidence_ready": False,
        "payment_completed_at_proven": False,
        "sale_transaction_ready": False,
    }
    return row, "OFFICIAL_COORDINATE_EXACT_UNIQUE"


def safe_summary() -> dict[str, Any]:
    return {
        "mode": "READ_ONLY_CARDOVA_POKEMON_JP_OFFICIAL_COORDINATE_PROBE",
        "official_source": "pokemon-card.com",
        "official_result_api": OFFICIAL_RESULT_API,
        "retrieval_rule": "STRUCTURAL_PROMO_SET_CODE_THEN_UNIQUE_EXACT_OFFICIAL_PRINTED_COORDINATE",
        "structural_set_code_transform_only": True,
        "provider_set_alias_table_used": False,
        "fuzzy_matching": False,
        "translation_assumed": False,
        "japanese_only": True,
        "official_unique_coordinate_required": True,
        "microvariant_exact_required_for_sale_evidence": True,
        "payment_completed_at_proven": False,
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


def run(
    records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
    catalog: OfficialPokemonJpCatalog,
) -> Mapping[str, Any]:
    selected = list(records[:max_records])
    rows: list[dict[str, Any]] = []
    blocked: Counter[str] = Counter()
    promo_candidates = 0
    official_codes: set[str] = set()
    macro_exact = 0

    for record in selected:
        _local_id, namespace, _ = namespace_probe.printed_number_namespace(record.get("collector_number"))
        code, _ = official_set_code(namespace)
        if code and _norm(record.get("language")).casefold() in {"japanese", "ja", "jp"}:
            promo_candidates += 1
            official_codes.add(code)

        row, reason = probe_record(record, catalog=catalog)
        if row is None:
            blocked[reason] += 1
            continue
        macro_exact += 1
        rows.append(row)
        # Exact macro identity is intentionally not promoted to exact commercial
        # sale evidence while the microvariant remains unproven.
        blocked[row["microvariant_reason"]] += 1

    return {
        "input_records": len(records),
        "selected_records": len(selected),
        "japanese_promo_coordinate_candidate_count": promo_candidates,
        "unique_official_search_set_codes": sorted(official_codes),
        "unique_official_search_set_code_count": len(official_codes),
        "official_macro_identity_exact_count": macro_exact,
        "exact_microvariant_count": 0,
        "official_result_requests": catalog.result_requests,
        "official_detail_requests": catalog.detail_requests,
        "blocked": dict(sorted(blocked.items())),
        "records": rows,
    }


def load_records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError("input JSON must contain records[]")
    records = payload["records"]
    if any(not isinstance(record, Mapping) for record in records):
        raise ValueError("records[] must contain objects only")
    return list(records)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Probe exact Cardova coordinates against official Pokemon Japan")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument("--max-detail-requests", type=int, default=MAX_DETAIL_REQUESTS)
    args = parser.parse_args(argv)
    if not 1 <= args.max_records <= HARD_MAX_RECORDS:
        parser.error(f"--max-records must be between 1 and {HARD_MAX_RECORDS}")
    if not 0 <= args.delay_seconds <= HARD_MAX_DELAY_SECONDS:
        parser.error(f"--delay-seconds must be between 0 and {HARD_MAX_DELAY_SECONDS}")
    if not 1 <= args.max_detail_requests <= MAX_DETAIL_REQUESTS:
        parser.error(f"--max-detail-requests must be between 1 and {MAX_DETAIL_REQUESTS}")

    summary = safe_summary()
    try:
        catalog = OfficialPokemonJpCatalog(
            delay_seconds=args.delay_seconds,
            max_detail_requests=args.max_detail_requests,
        )
        summary.update(run(load_records(args.input), max_records=args.max_records, catalog=catalog))
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
