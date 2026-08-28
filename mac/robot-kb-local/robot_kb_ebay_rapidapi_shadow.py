from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

import requests


RAPIDAPI_HOST = "ebay-average-selling-price.p.rapidapi.com"
RAPIDAPI_URL = f"https://{RAPIDAPI_HOST}/findCompletedItems"
SOURCE_CODE = "ebay_rapidapi_completed_shadow"
SOURCE_NAME = "eBay completed items via RapidAPI"
ALLOWED_MAX_RESULTS = frozenset({60, 120, 240})
SUPPORTED_SITE_IDS = frozenset({"0"})  # phase 1: ebay.com / USD only
_ITEM_ID_RE = re.compile(r"^\d{8,20}$")
_ACCEPTED_OFFER_RE = re.compile(r"\b(?:accepts? offers?|best offer)\b", re.I)


@dataclass(frozen=True)
class CompletedItemCandidate:
    item_id: str
    title: str
    sale_price_minor: int
    currency: str
    date_sold: str
    buying_format: str
    condition: str
    shipping_price_minor: Optional[int]
    link: str
    image_url: str
    accepted_offer_ambiguous: bool


@dataclass(frozen=True)
class ParseResult:
    candidates: tuple[CompletedItemCandidate, ...]
    rejected: int
    duplicates: int
    accepted_offer_ambiguous: int
    aggregate_fields_ignored: tuple[str, ...]
    provider_clean_no_match: bool
    provider_error: str = ""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _minor(value: object) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount < 0:
        return None
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_date(value: object) -> Optional[str]:
    text = _string(value)
    if not text:
        return None
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        parsed = None
    if parsed is None:
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def _currency(value: object, site_id: str) -> Optional[str]:
    raw = _string(value).upper().replace(" ", "")
    if site_id == "0" and raw in {"USD", "US$", "$"}:
        return "USD"
    return None


def _ebay_link(value: object, site_id: str) -> str:
    link = _string(value)
    if not link:
        return ""
    try:
        parsed = urlparse(link)
    except ValueError:
        return ""
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https":
        return ""
    if site_id == "0" and not (host == "ebay.com" or host.endswith(".ebay.com")):
        return ""
    return link


def parse_product(
    row: Mapping[str, Any], *, site_id: str = "0"
) -> Optional[CompletedItemCandidate]:
    if site_id not in SUPPORTED_SITE_IDS:
        return None
    item_id = _string(row.get("item_id"))
    title = _string(row.get("title"))
    price = _minor(row.get("sale_price"))
    unit = _currency(row.get("currency"), site_id)
    sold_date = _parse_date(row.get("date_sold"))
    buying_format = _string(row.get("buying_format"))
    link = _ebay_link(row.get("link"), site_id)
    if (
        not _ITEM_ID_RE.fullmatch(item_id)
        or not title
        or price is None
        or unit is None
        or sold_date is None
        or not buying_format
        or not link
    ):
        return None

    shipping_raw = row.get("shipping_price")
    shipping = _minor(shipping_raw) if shipping_raw is not None else None
    if shipping_raw is not None and shipping is None:
        return None

    return CompletedItemCandidate(
        item_id=item_id,
        title=title,
        sale_price_minor=price,
        currency=unit,
        date_sold=sold_date,
        buying_format=buying_format,
        condition=_string(row.get("condition")),
        shipping_price_minor=shipping,
        link=link,
        image_url=_string(row.get("image_url")),
        accepted_offer_ambiguous=bool(_ACCEPTED_OFFER_RE.search(buying_format)),
    )


def parse_response(payload: object, *, site_id: str = "0") -> ParseResult:
    if site_id not in SUPPORTED_SITE_IDS:
        return ParseResult((), 0, 0, 0, (), False, "unsupported-site-id")
    if not isinstance(payload, Mapping):
        return ParseResult((), 0, 0, 0, (), False, "malformed-payload")
    if payload.get("success") is not True:
        return ParseResult((), 0, 0, 0, (), False, "provider-success-not-true")

    aggregate_fields = tuple(
        key
        for key in ("average_price", "median_price", "min_price", "max_price")
        if key in payload
    )
    products = payload.get("products")
    if not isinstance(products, Sequence) or isinstance(products, (str, bytes)):
        return ParseResult(
            (), 0, 0, 0, aggregate_fields, False, "products-not-array"
        )

    output: list[CompletedItemCandidate] = []
    seen: set[str] = set()
    rejected = 0
    duplicates = 0
    ambiguous = 0
    for raw in products:
        if not isinstance(raw, Mapping):
            rejected += 1
            continue
        candidate = parse_product(raw, site_id=site_id)
        if candidate is None:
            rejected += 1
            continue
        if candidate.item_id in seen:
            duplicates += 1
            continue
        seen.add(candidate.item_id)
        ambiguous += int(candidate.accepted_offer_ambiguous)
        output.append(candidate)

    return ParseResult(
        tuple(output),
        rejected,
        duplicates,
        ambiguous,
        aggregate_fields,
        not output and not products,
        "",
    )


def build_request_body(
    keywords: str,
    *,
    max_search_results: int = 60,
    site_id: str = "0",
    excluded_keywords: str = "",
    category_id: str = "",
) -> dict[str, Any]:
    query = keywords.strip()
    if not query:
        raise ValueError("keywords are required")
    if max_search_results not in ALLOWED_MAX_RESULTS:
        raise ValueError("max_search_results must be one of 60, 120, 240")
    if site_id not in SUPPORTED_SITE_IDS:
        raise ValueError("phase-1 shadow supports only eBay site_id=0")
    body: dict[str, Any] = {
        "keywords": query,
        "max_search_results": max_search_results,
        "remove_outliers": False,
        "site_id": site_id,
    }
    if excluded_keywords.strip():
        body["excluded_keywords"] = excluded_keywords.strip()
    if category_id.strip():
        body["category_id"] = category_id.strip()
    return body


def fetch_completed_items(
    key: str,
    keywords: str,
    *,
    max_search_results: int = 60,
    site_id: str = "0",
    excluded_keywords: str = "",
    category_id: str = "",
    timeout: float = 30.0,
    session: Optional[requests.Session] = None,
) -> tuple[int, object, Mapping[str, Any]]:
    secret = key.strip()
    if not secret:
        raise ValueError("RapidAPI key is required")
    body = build_request_body(
        keywords,
        max_search_results=max_search_results,
        site_id=site_id,
        excluded_keywords=excluded_keywords,
        category_id=category_id,
    )
    owned = session is None
    client = session or requests.Session()
    try:
        response = client.post(
            RAPIDAPI_URL,
            headers={
                "Content-Type": "application/json",
                "x-rapidapi-host": RAPIDAPI_HOST,
                "x-rapidapi-key": secret,
            },
            json=body,
            timeout=timeout,
        )
        try:
            payload: object = response.json()
        except ValueError:
            payload = {}
        return int(response.status_code), payload, response.headers
    finally:
        if owned:
            client.close()


def _runtime():
    from robot_kb.domain import ObservationType, SourceKind
    from robot_kb.sidecar.models import (
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
    )
    from robot_kb.sidecar.persistence import ShadowKnowledgePersistence

    return (
        ObservationType,
        SourceKind,
        IdentityClaim,
        NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
        ShadowKnowledgePersistence,
    )


def _digest(*values: object) -> str:
    return hashlib.sha256(
        "|".join(str(value or "") for value in values).encode()
    ).hexdigest()


def _payload_fingerprint(payload: object) -> str:
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def candidate_observation(
    candidate: CompletedItemCandidate, *, query: str, observed_at: str
):
    (
        ObservationType,
        SourceKind,
        IdentityClaim,
        NormalizedObservation,
        _RawSourceRecord,
        _ShadowDiagnostics,
        _ShadowKnowledgePersistence,
    ) = _runtime()
    claims = (
        IdentityClaim("ebay_item_id", candidate.item_id, SourceKind.PROVIDER),
        IdentityClaim("card_title_raw", candidate.title, SourceKind.PROVIDER),
        IdentityClaim("listing_url", candidate.link, SourceKind.PROVIDER),
        IdentityClaim("buying_format", candidate.buying_format, SourceKind.PROVIDER),
        IdentityClaim("condition", candidate.condition, SourceKind.PROVIDER),
        IdentityClaim("provider_marketplace", "eBay", SourceKind.PROVIDER),
    )
    return NormalizedObservation(
        observation_type=ObservationType.PROVIDER_METRIC_OBSERVATION,
        source_native_record_id=f"ebay-item:{candidate.item_id}",
        observed_at=observed_at,
        event_at=f"{candidate.date_sold}T00:00:00+00:00",
        event_time_precision="DAY",
        fact={
            "metric_name": "EBAY_RAPIDAPI_COMPLETED_ITEM_CANDIDATE",
            "metric_value_minor": candidate.sale_price_minor,
            "currency": candidate.currency,
            "shipping_value_minor": candidate.shipping_price_minor,
            "item_level_sold": False,
            "provider_completed_item_candidate": True,
            "provider_asserted_date_sold": candidate.date_sold,
            "final_price_semantics_proven": False,
            "accepted_offer_price_ambiguous": candidate.accepted_offer_ambiguous,
            "query_context": query,
            "evidence_class": "COMPLETED_ITEM_PROVIDER_ASSERTED_SHADOW",
        },
        identity_subject_type="EBAY_COMPLETED_ITEM_SHADOW",
        identity_subject_label=f"eBay completed-item candidate {candidate.item_id}",
        identity_namespace="EBAY_ITEM_ID",
        identity_identifier_value=candidate.item_id,
        unresolved_dimensions=(
            "canonical_identity",
            "commercial_microvariant",
            "final_price_semantics",
        ),
        claims=tuple(claim for claim in claims if claim.value),
        exact_identity_eligible=False,
        genuine_sale_evidence=False,
    )


def persist_shadow_response(
    kb: Any,
    payload: Mapping[str, Any],
    parsed: ParseResult,
    *,
    query: str,
    observed_at: str,
    site_id: str = "0",
) -> int:
    (
        ObservationType,
        _SourceKind,
        _IdentityClaim,
        _NormalizedObservation,
        RawSourceRecord,
        ShadowDiagnostics,
        ShadowKnowledgePersistence,
    ) = _runtime()
    observations = []
    for candidate in parsed.candidates:
        native = f"ebay-item:{candidate.item_id}"
        existing = kb.connection.execute(
            """
            SELECT 1
            FROM market_observation o
            JOIN source_system s ON s.id=o.source_system_id
            WHERE s.code=? AND o.source_native_record_id=? AND o.observation_type=?
            LIMIT 1
            """,
            (
                SOURCE_CODE,
                native,
                ObservationType.PROVIDER_METRIC_OBSERVATION.value,
            ),
        ).fetchone()
        if existing is None:
            observations.append(
                candidate_observation(candidate, query=query, observed_at=observed_at)
            )

    raw_id = "rapidapi-response:" + _digest(
        query, site_id, _payload_fingerprint(payload)
    )[:32]
    record = RawSourceRecord(
        source_code=SOURCE_CODE,
        source_name=SOURCE_NAME,
        source_role="PROVIDER",
        source_native_record_id=raw_id,
        payload=dict(payload),
        retrieved_at=observed_at,
        object_type="PROVIDER_RESPONSE",
        external_native_id=raw_id,
    )
    ShadowKnowledgePersistence(kb).ingest(
        record, tuple(observations), ShadowDiagnostics()
    )
    return len(observations)


def sanitized_summary(status: int, parsed: ParseResult) -> dict[str, Any]:
    return {
        "http_status": status,
        "accepted_candidates": len(parsed.candidates),
        "rejected_products": parsed.rejected,
        "duplicates": parsed.duplicates,
        "accepted_offer_ambiguous": parsed.accepted_offer_ambiguous,
        "aggregate_fields_ignored": list(parsed.aggregate_fields_ignored),
        "provider_clean_no_match": parsed.provider_clean_no_match,
        "provider_error": parsed.provider_error,
        "item_level_sold": False,
        "genuine_sale_evidence": False,
        "v4_economic_use": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def run_probe(
    key: str,
    query: str,
    *,
    max_search_results: int = 60,
    site_id: str = "0",
    session: Optional[requests.Session] = None,
) -> tuple[int, dict[str, Any]]:
    try:
        status, payload, _headers = fetch_completed_items(
            key,
            query,
            max_search_results=max_search_results,
            site_id=site_id,
            session=session,
        )
    except (requests.RequestException, ValueError) as error:
        return 1, {
            "http_status": 0,
            "provider_error": type(error).__name__,
            "item_level_sold": False,
            "genuine_sale_evidence": False,
            "v4_economic_use": False,
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
            "automatic_payment": False,
        }
    parsed = (
        parse_response(payload, site_id=site_id)
        if status == 200
        else ParseResult((), 0, 0, 0, (), False, f"http-{status}")
    )
    summary = sanitized_summary(status, parsed)
    if parsed.candidates:
        summary["examples"] = [
            {
                "item_id": row.item_id,
                "title": row.title,
                "sale_price_minor": row.sale_price_minor,
                "currency": row.currency,
                "date_sold": row.date_sold,
                "buying_format": row.buying_format,
                "shipping_price_minor": row.shipping_price_minor,
                "accepted_offer_ambiguous": row.accepted_offer_ambiguous,
            }
            for row in parsed.candidates[:3]
        ]
    return (0 if status == 200 and not parsed.provider_error else 1), summary


def run_ingest(
    key: str,
    query: str,
    *,
    max_search_results: int = 60,
    site_id: str = "0",
) -> tuple[int, dict[str, Any]]:
    status, payload, _headers = fetch_completed_items(
        key,
        query,
        max_search_results=max_search_results,
        site_id=site_id,
    )
    parsed = (
        parse_response(payload, site_id=site_id)
        if status == 200
        else ParseResult((), 0, 0, 0, (), False, f"http-{status}")
    )
    summary = sanitized_summary(status, parsed)
    if status != 200 or parsed.provider_error:
        return 1, summary
    database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
    if not database:
        summary["provider_error"] = "ROBOT_KB_DATABASE_URL-required"
        return 1, summary

    from robot_kb.repository import KnowledgeBase

    observed_at = iso_now()
    with KnowledgeBase.open(database) as kb:
        stored = persist_shadow_response(
            kb,
            payload if isinstance(payload, Mapping) else {},
            parsed,
            query=query,
            observed_at=observed_at,
            site_id=site_id,
        )
    summary["stored_shadow_candidates"] = stored
    return 0, summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Shadow-only eBay completed-item provider diagnostic"
    )
    parser.add_argument("mode", choices=("probe", "ingest"))
    parser.add_argument(
        "--query",
        default=os.getenv(
            "ROBOT_KB_EBAY_RAPIDAPI_QUERY", "Pokemon Pikachu PSA 10"
        ),
    )
    parser.add_argument(
        "--max-search-results",
        type=int,
        default=60,
        choices=sorted(ALLOWED_MAX_RESULTS),
    )
    parser.add_argument(
        "--site-id", default="0", choices=sorted(SUPPORTED_SITE_IDS)
    )
    args = parser.parse_args(argv)
    key = os.getenv("ROBOT_KB_EBAY_RAPIDAPI_KEY", "").strip()
    if not key:
        print(
            json.dumps(
                {
                    "provider_error": "rapidapi-key-not-configured",
                    "item_level_sold": False,
                    "genuine_sale_evidence": False,
                    "v4_economic_use": False,
                },
                sort_keys=True,
            )
        )
        return 2
    if args.mode == "probe":
        code, result = run_probe(
            key,
            args.query,
            max_search_results=args.max_search_results,
            site_id=args.site_id,
        )
    else:
        code, result = run_ingest(
            key,
            args.query,
            max_search_results=args.max_search_results,
            site_id=args.site_id,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
