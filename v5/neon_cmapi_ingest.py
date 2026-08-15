from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

import psycopg

from . import neon_source_scout_ingest as base


EVIDENCE_PATH = Path("cmapi_opportunity_evidence.json")
SOURCE_CODES = {
    "cmapi": ("CardMarket API TCG (RapidAPI/tcggopro)", "PROVIDER"),
    "ebay": ("eBay", "MARKET"),
    "cardmarket": ("Cardmarket", "MARKET"),
    "tcgplayer": ("TCGplayer", "MARKET"),
}


def _ensure_source(cur: psycopg.Cursor[Any], code: str, name: str, role: str) -> str:
    return base._ensure_source(cur, code, name, role)


def _persist_payload_record(
    cur: psycopg.Cursor[Any],
    *,
    source_id: str,
    source_native_record_id: str,
    payload: object,
    retrieved_at: str,
    external_object_id: str | None = None,
    source_updated_at: str | None = None,
) -> tuple[str, str]:
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload_bytes = payload_json.encode("utf-8")
    payload_sha = base._digest(payload_bytes)
    created_at = base._now()
    source_record_id = base._id("srecord", source_native_record_id, payload_sha)

    cur.execute(
        """
        INSERT INTO source_payload (
            payload_sha256, payload_bytes, payload_format, byte_length, created_at
        ) VALUES (%s, %s, 'CANONICAL_JSON', %s, %s)
        ON CONFLICT (payload_sha256) DO NOTHING
        """,
        (payload_sha, payload_bytes, len(payload_bytes), created_at),
    )
    cur.execute(
        """
        INSERT INTO source_record (
            id, source_system_id, external_object_id, source_native_record_id,
            payload_sha256, retrieved_at, source_updated_at, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_system_id, source_native_record_id, payload_sha256) DO NOTHING
        """,
        (
            source_record_id,
            source_id,
            external_object_id,
            source_native_record_id,
            payload_sha,
            retrieved_at,
            source_updated_at,
            created_at,
        ),
    )
    cur.execute(
        """
        INSERT INTO source_record_payload (source_record_id, payload_sha256, created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (source_record_id) DO NOTHING
        """,
        (source_record_id, payload_sha, created_at),
    )
    lineage_key = f"lineage_{base._digest([source_record_id, retrieved_at])}"
    retrieval_id = base._id("sretrieval", lineage_key)
    cur.execute(
        """
        INSERT INTO source_record_retrieval (
            id, source_record_id, external_object_id, retrieved_at,
            source_updated_at, lineage_key, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (lineage_key) DO NOTHING
        """,
        (
            retrieval_id,
            source_record_id,
            external_object_id,
            retrieved_at,
            source_updated_at,
            lineage_key,
            created_at,
        ),
    )
    return source_record_id, payload_sha


def _ensure_external_object(
    cur: psycopg.Cursor[Any],
    *,
    source_id: str,
    object_type: str,
    source_native_id: str,
    upstream_source_id: str | None = None,
    upstream_native_id: str | None = None,
) -> str:
    external_id = base._id("extobj", source_id, object_type, source_native_id)
    created_at = base._now()
    cur.execute(
        """
        INSERT INTO external_object (
            id, source_system_id, object_type, source_native_id,
            upstream_market_system_id, upstream_native_id, created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_system_id, object_type, source_native_id) DO NOTHING
        """,
        (
            external_id,
            source_id,
            object_type,
            source_native_id,
            upstream_source_id,
            upstream_native_id,
            created_at,
        ),
    )
    cur.execute(
        "SELECT id FROM external_object WHERE source_system_id = %s AND object_type = %s AND source_native_id = %s",
        (source_id, object_type, source_native_id),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"external_object missing: {object_type}:{source_native_id}")
    return str(row[0])


def _insert_metric(
    cur: psycopg.Cursor[Any],
    *,
    provider_source_id: str,
    upstream_source_id: str | None,
    source_record_id: str,
    source_native_record_id: str,
    payload_sha256: str,
    metric_name: str,
    observed_at: str,
    amount_minor: int | None = None,
    currency: str | None = None,
    sample_size: int | None = None,
    event_at: str | None = None,
    event_precision: str = "EXACT",
    window_started_at: str | None = None,
    window_ended_at: str | None = None,
) -> bool:
    if amount_minor is None:
        currency = None
    content = {
        "source_record_id": source_record_id,
        "source_native_record_id": source_native_record_id,
        "metric_name": metric_name,
        "amount_minor": amount_minor,
        "currency": currency,
        "sample_size": sample_size,
        "event_at": event_at,
        "event_precision": event_precision,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "payload_sha256": payload_sha256,
    }
    content_sha = base._digest(content)
    idempotency_key = f"obskey_{base._digest(['cmapi', source_native_record_id, payload_sha256])}"
    observation_id = base._id("observation", idempotency_key)
    created_at = base._now()
    event_value = event_at or observed_at

    cur.execute(
        """
        INSERT INTO market_observation (
            id, observation_type, source_system_id, upstream_market_system_id,
            source_record_id, source_native_record_id, upstream_event_object_id,
            canonical_card_id, idempotency_key, content_sha256, event_at,
            event_time_precision, observed_at, ingested_at, source_updated_at,
            revision_of_observation_id, created_at, lifecycle_state, sealed_at
        ) VALUES (
            %s, 'PROVIDER_METRIC_OBSERVATION', %s, %s,
            %s, %s, NULL,
            NULL, %s, %s, %s,
            %s, %s, %s, NULL,
            NULL, %s, 'DRAFT', NULL
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            observation_id,
            provider_source_id,
            upstream_source_id,
            source_record_id,
            source_native_record_id,
            idempotency_key,
            content_sha,
            event_value,
            event_precision,
            observed_at,
            created_at,
            created_at,
        ),
    )
    cur.execute("SELECT id, lifecycle_state FROM market_observation WHERE idempotency_key = %s", (idempotency_key,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"metric observation missing: {source_native_record_id}")
    observation_id, lifecycle = str(row[0]), str(row[1])
    if lifecycle == "SEALED":
        return False
    if lifecycle != "DRAFT":
        raise RuntimeError(f"unexpected metric lifecycle: {lifecycle}")

    cur.execute(
        """
        INSERT INTO provider_metric_observation (
            observation_id, metric_name, metric_value_minor, currency,
            window_started_at, window_ended_at, sample_size
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (
            observation_id,
            metric_name,
            amount_minor,
            currency,
            window_started_at,
            window_ended_at,
            sample_size,
        ),
    )
    inserted = cur.rowcount > 0
    cur.execute(
        "UPDATE market_observation SET lifecycle_state = 'SEALED', sealed_at = %s WHERE id = %s AND lifecycle_state = 'DRAFT'",
        (base._now(), observation_id),
    )
    return inserted


def _minor(value: object) -> int | None:
    return base._minor(value)


def _token_words(value: object) -> list[str]:
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _sale_offer_matches_card(card: Mapping[str, object], offer: Mapping[str, object]) -> bool:
    title_tokens = _token_words(offer.get("title"))
    if not title_tokens:
        return False
    title_set = set(title_tokens)
    name_tokens = _token_words(card.get("name"))
    set_tokens = [token for token in _token_words(card.get("set")) if token not in {"the", "and"}]
    number = str(card.get("number") or "").split("/", 1)[0].lstrip("0") or "0"
    if not name_tokens or not all(token in title_set for token in name_tokens):
        return False
    if set_tokens and not all(token in title_set for token in set_tokens):
        return False
    if number not in title_set:
        return False
    company = str(offer.get("company") or "").upper()
    grade = str(offer.get("grade") or "")
    return company == "PSA" and grade in {"10", "10.0"}


def _insert_sale(
    cur: psycopg.Cursor[Any],
    *,
    provider_source_id: str,
    ebay_source_id: str,
    source_record_id: str,
    payload_sha256: str,
    retrieved_at: str,
    tcgdex_id: str,
    canonical_en: Mapping[str, object],
    offer: Mapping[str, object],
) -> str:
    item_id = str(offer.get("ebay_item_id") or "").strip()
    ended_at = str(offer.get("ended_at") or "").strip()
    currency = str(offer.get("currency") or "").upper().strip()
    grader = str(offer.get("company") or "").upper().strip()
    grade = str(offer.get("grade") or "").strip()
    amount_minor = _minor(offer.get("price"))
    if not (item_id and ended_at and len(currency) == 3 and grader and grade and amount_minor is not None):
        return "REJECTED_INCOMPLETE"
    if not _sale_offer_matches_card(canonical_en, offer):
        return "REJECTED_IDENTITY"

    extobj_id = _ensure_external_object(
        cur,
        source_id=provider_source_id,
        object_type="EBAY_SOLD_LISTING",
        source_native_id=f"ebay:{item_id}",
        upstream_source_id=ebay_source_id,
        upstream_native_id=item_id,
    )
    source_native = f"cmapi:ebay-sold:{item_id}:tcgdex:{tcgdex_id}:PSA:10"
    idempotency_key = f"obskey_{base._digest(['cmapi-ebay-sale', item_id, ended_at, amount_minor, currency, tcgdex_id, grader, grade])}"
    observation_id = base._id("observation", idempotency_key)
    content_sha = base._digest(
        {
            "item_id": item_id,
            "ended_at": ended_at,
            "amount_minor": amount_minor,
            "currency": currency,
            "tcgdex_id": tcgdex_id,
            "grader": grader,
            "grade": grade,
            "payload_sha256": payload_sha256,
        }
    )
    created_at = base._now()
    cur.execute(
        """
        INSERT INTO market_observation (
            id, observation_type, source_system_id, upstream_market_system_id,
            source_record_id, source_native_record_id, upstream_event_object_id,
            canonical_card_id, idempotency_key, content_sha256, event_at,
            event_time_precision, observed_at, ingested_at, source_updated_at,
            revision_of_observation_id, created_at, lifecycle_state, sealed_at
        ) VALUES (
            %s, 'SALE_TRANSACTION', %s, %s,
            %s, %s, %s,
            NULL, %s, %s, %s,
            'EXACT', %s, %s, NULL,
            NULL, %s, 'DRAFT', NULL
        )
        ON CONFLICT (idempotency_key) DO NOTHING
        """,
        (
            observation_id,
            provider_source_id,
            ebay_source_id,
            source_record_id,
            source_native,
            extobj_id,
            idempotency_key,
            content_sha,
            ended_at,
            retrieved_at,
            created_at,
            created_at,
        ),
    )
    cur.execute("SELECT id, lifecycle_state FROM market_observation WHERE idempotency_key = %s", (idempotency_key,))
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"sale observation missing: {item_id}")
    observation_id, lifecycle = str(row[0]), str(row[1])
    if lifecycle == "SEALED":
        return "REPLAY"
    if lifecycle != "DRAFT":
        raise RuntimeError(f"unexpected sale lifecycle {lifecycle}: {item_id}")

    cur.execute(
        """
        INSERT INTO sale_transaction (
            observation_id, listing_started_at, sale_occurred_at, transaction_status
        ) VALUES (%s, NULL, %s, 'COMPLETED')
        ON CONFLICT (observation_id) DO NOTHING
        """,
        (observation_id, ended_at),
    )
    price_id = base._id("price", observation_id, "ITEM_PRICE")
    cur.execute(
        """
        INSERT INTO price_component (
            id, observation_id, component_type, amount_minor, currency,
            knowledge_state, inclusion_state, created_at
        ) VALUES (%s, %s, 'ITEM_PRICE', %s, %s, 'KNOWN', 'INCLUDED', %s)
        ON CONFLICT (observation_id, component_type) DO NOTHING
        """,
        (price_id, observation_id, amount_minor, currency, base._now()),
    )
    cur.execute(
        "UPDATE market_observation SET lifecycle_state = 'SEALED', sealed_at = %s WHERE id = %s AND lifecycle_state = 'DRAFT'",
        (base._now(), observation_id),
    )
    return "INSERTED"


def _current_metric_specs(row: Mapping[str, object], tcgdex_id: str) -> list[tuple[str, str, int | None, str | None, int | None]]:
    specs: list[tuple[str, str, int | None, str | None, int | None]] = []
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    cm = prices.get("cardmarket") if isinstance(prices.get("cardmarket"), Mapping) else {}
    for field, label in (
        ("lowest_near_mint", "CMAPI_CARDMARKET_LOW_ASK:EN_ANCHOR"),
        ("lowest_near_mint_FR", "CMAPI_CARDMARKET_LOW_ASK:FR"),
        ("7d_average", "CMAPI_CARDMARKET_7D_AVERAGE:GLOBAL"),
        ("30d_average", "CMAPI_CARDMARKET_30D_AVERAGE:GLOBAL"),
    ):
        amount = _minor(cm.get(field))
        if amount is not None:
            specs.append(("cardmarket", f"{label}:TCGDEX:{tcgdex_id}", amount, "EUR", None))

    tp = prices.get("tcg_player") if isinstance(prices.get("tcg_player"), Mapping) else {}
    tp_currency = str(tp.get("currency") or "").upper()
    if len(tp_currency) == 3:
        amount = _minor(tp.get("market_price"))
        if amount is not None:
            specs.append(("tcgplayer", f"CMAPI_TCGPLAYER_MARKET:TCGDEX:{tcgdex_id}", amount, tp_currency, None))

    ebay = prices.get("ebay") if isinstance(prices.get("ebay"), Mapping) else {}
    ebay_currency = str(ebay.get("currency") or "USD").upper()
    graded = ebay.get("graded") if isinstance(ebay.get("graded"), Mapping) else {}
    for grader, grades in graded.items():
        if not isinstance(grades, Mapping):
            continue
        for grade, grade_row in grades.items():
            if not isinstance(grade_row, Mapping):
                continue
            amount = _minor(grade_row.get("median_price"))
            try:
                sample = int(grade_row.get("sample_size") or 0)
            except (TypeError, ValueError):
                sample = None
            if amount is not None and len(ebay_currency) == 3:
                specs.append(
                    (
                        "ebay",
                        f"CMAPI_EBAY_SOLD_MEDIAN:{str(grader).upper()}:{grade}:TCGDEX:{tcgdex_id}",
                        amount,
                        ebay_currency,
                        sample,
                    )
                )
    return specs


def ingest(connection_string: str, evidence_path: Path = EVIDENCE_PATH) -> dict[str, int]:
    document = json.loads(evidence_path.read_text(encoding="utf-8"))
    cards = document.get("cards") if isinstance(document, Mapping) else None
    if not isinstance(cards, list):
        raise RuntimeError("CMAPI evidence sidecar is malformed")

    stats = {
        "cards": 0,
        "payloads": 0,
        "source_records": 0,
        "metrics": 0,
        "sale_candidates": 0,
        "sales_inserted": 0,
        "sales_replayed": 0,
        "sales_rejected_identity": 0,
        "sales_rejected_incomplete": 0,
    }
    with psycopg.connect(connection_string) as conn:
        with conn.cursor() as cur:
            source_ids = {
                code: _ensure_source(cur, code, name, role)
                for code, (name, role) in SOURCE_CODES.items()
            }
            for card in cards:
                if not isinstance(card, Mapping) or card.get("identity_status") != "EXACT_EN_ANCHOR":
                    continue
                tcgdex_id = str(card.get("tcgdex_id") or "").strip()
                retrieved_at = str(card.get("retrieved_at") or base._now())
                matched = card.get("matched_card") if isinstance(card.get("matched_card"), Mapping) else {}
                provider_id = str(matched.get("id") or "").strip()
                canonical_en = card.get("canonical_en") if isinstance(card.get("canonical_en"), Mapping) else {}
                if not tcgdex_id or not provider_id:
                    continue
                provider_object_id = _ensure_external_object(
                    cur,
                    source_id=source_ids["cmapi"],
                    object_type="CARD",
                    source_native_id=f"card:{provider_id}",
                )

                search_payload = card.get("search_payload")
                if search_payload is not None:
                    native = f"cmapi:search:card:{provider_id}:tcgdex:{tcgdex_id}"
                    record_id, payload_sha = _persist_payload_record(
                        cur,
                        source_id=source_ids["cmapi"],
                        source_native_record_id=native,
                        payload=search_payload,
                        retrieved_at=retrieved_at,
                        external_object_id=provider_object_id,
                    )
                    stats["payloads"] += 1
                    stats["source_records"] += 1
                    rows = search_payload.get("data") if isinstance(search_payload, Mapping) else None
                    matched_row = None
                    if isinstance(rows, list):
                        for row in rows:
                            if isinstance(row, Mapping) and str(row.get("id") or "") == provider_id:
                                matched_row = row
                                break
                    if isinstance(matched_row, Mapping):
                        for upstream, metric_name, amount, currency, sample in _current_metric_specs(matched_row, tcgdex_id):
                            if _insert_metric(
                                cur,
                                provider_source_id=source_ids["cmapi"],
                                upstream_source_id=source_ids[upstream],
                                source_record_id=record_id,
                                source_native_record_id=f"{native}:{metric_name}",
                                payload_sha256=payload_sha,
                                metric_name=metric_name,
                                observed_at=retrieved_at,
                                amount_minor=amount,
                                currency=currency,
                                sample_size=sample,
                            ):
                                stats["metrics"] += 1

                history = card.get("history") if isinstance(card.get("history"), Mapping) else {}
                for lang_code in ("en", "fr"):
                    summary = history.get(lang_code) if isinstance(history.get(lang_code), Mapping) else {}
                    payload = summary.get("payload")
                    if not isinstance(payload, Mapping):
                        continue
                    native = f"cmapi:history:card:{provider_id}:tcgdex:{tcgdex_id}:lang:{lang_code}"
                    record_id, payload_sha = _persist_payload_record(
                        cur,
                        source_id=source_ids["cmapi"],
                        source_native_record_id=native,
                        payload=payload,
                        retrieved_at=retrieved_at,
                        external_object_id=provider_object_id,
                    )
                    stats["payloads"] += 1
                    stats["source_records"] += 1
                    points = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
                    search_currency = "EUR"
                    for event_day, values in points.items():
                        if not isinstance(values, Mapping):
                            continue
                        cm_amount = _minor(values.get("cm_low"))
                        if cm_amount is not None:
                            metric = f"CMAPI_CARDMARKET_HISTORY_LOW_ASK:{lang_code.upper()}:TCGDEX:{tcgdex_id}"
                            if _insert_metric(
                                cur,
                                provider_source_id=source_ids["cmapi"],
                                upstream_source_id=source_ids["cardmarket"],
                                source_record_id=record_id,
                                source_native_record_id=f"{native}:{event_day}:cm_low",
                                payload_sha256=payload_sha,
                                metric_name=metric,
                                observed_at=retrieved_at,
                                amount_minor=cm_amount,
                                currency="EUR",
                                event_at=str(event_day),
                                event_precision="DAY",
                            ):
                                stats["metrics"] += 1
                        tp_amount = _minor(values.get("tcg_player_market"))
                        if tp_amount is not None and lang_code == "en":
                            metric = f"CMAPI_TCGPLAYER_HISTORY_MARKET:GLOBAL:TCGDEX:{tcgdex_id}"
                            if _insert_metric(
                                cur,
                                provider_source_id=source_ids["cmapi"],
                                upstream_source_id=source_ids["tcgplayer"],
                                source_record_id=record_id,
                                source_native_record_id=f"{native}:{event_day}:tcgplayer_market",
                                payload_sha256=payload_sha,
                                metric_name=metric,
                                observed_at=retrieved_at,
                                amount_minor=tp_amount,
                                currency=search_currency,
                                event_at=str(event_day),
                                event_precision="DAY",
                            ):
                                stats["metrics"] += 1

                sold = card.get("ebay_psa10_sold_offers") if isinstance(card.get("ebay_psa10_sold_offers"), Mapping) else {}
                sold_payload = sold.get("payload")
                if isinstance(sold_payload, Mapping):
                    native = f"cmapi:ebay-sold-offers:card:{provider_id}:tcgdex:{tcgdex_id}:PSA:10:page:1"
                    record_id, payload_sha = _persist_payload_record(
                        cur,
                        source_id=source_ids["cmapi"],
                        source_native_record_id=native,
                        payload=sold_payload,
                        retrieved_at=retrieved_at,
                        external_object_id=provider_object_id,
                    )
                    stats["payloads"] += 1
                    stats["source_records"] += 1
                    offers = sold_payload.get("data") if isinstance(sold_payload.get("data"), list) else []
                    for offer in offers:
                        if not isinstance(offer, Mapping):
                            continue
                        stats["sale_candidates"] += 1
                        result = _insert_sale(
                            cur,
                            provider_source_id=source_ids["cmapi"],
                            ebay_source_id=source_ids["ebay"],
                            source_record_id=record_id,
                            payload_sha256=payload_sha,
                            retrieved_at=retrieved_at,
                            tcgdex_id=tcgdex_id,
                            canonical_en=canonical_en,
                            offer=offer,
                        )
                        if result == "INSERTED":
                            stats["sales_inserted"] += 1
                        elif result == "REPLAY":
                            stats["sales_replayed"] += 1
                        elif result == "REJECTED_IDENTITY":
                            stats["sales_rejected_identity"] += 1
                        else:
                            stats["sales_rejected_incomplete"] += 1
                stats["cards"] += 1
        conn.commit()
    return stats


def main() -> int:
    connection_string = os.getenv("NEON_DATABASE_URL", "").strip()
    if not connection_string:
        print("CMAPI_NEON_INGEST skipped: NEON_DATABASE_URL not configured")
        return 0
    if not EVIDENCE_PATH.exists():
        print("CMAPI_NEON_INGEST skipped: evidence sidecar not found")
        return 0
    stats = ingest(connection_string)
    print("CMAPI_NEON_INGEST " + " ".join(f"{key}={value}" for key, value in stats.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
