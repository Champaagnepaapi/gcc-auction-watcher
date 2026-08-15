from __future__ import annotations

from typing import Any, Mapping

import psycopg

from . import neon_cmapi_ingest as base
from . import neon_source_scout_ingest as kb


_ORIGINAL_INSERT_METRIC = base._insert_metric


def _safe_insert_metric(cur: psycopg.Cursor[Any], **kwargs: Any) -> bool:
    metric_name = str(kwargs.get("metric_name") or "")
    # CMAPI history returns tcg_player_market values but the history payload does
    # not carry a per-point currency. Do not inherit/guess one from another
    # field. Preserve the raw payload; ingest this series only once currency is
    # explicitly proven by the provider contract.
    if metric_name.startswith("CMAPI_TCGPLAYER_HISTORY_MARKET:"):
        return False
    return _ORIGINAL_INSERT_METRIC(cur, **kwargs)


def _insert_sale_day_precision(
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
    amount_minor = base._minor(offer.get("price"))
    if not (item_id and ended_at and len(currency) == 3 and grader and grade and amount_minor is not None):
        return "REJECTED_INCOMPLETE"
    if not base._sale_offer_matches_card(canonical_en, offer):
        return "REJECTED_IDENTITY"

    extobj_id = base._ensure_external_object(
        cur,
        source_id=provider_source_id,
        object_type="EBAY_SOLD_LISTING",
        source_native_id=f"ebay:{item_id}",
        upstream_source_id=ebay_source_id,
        upstream_native_id=item_id,
    )
    source_native = f"cmapi:ebay-sold:{item_id}:tcgdex:{tcgdex_id}:PSA:10"
    idempotency_key = f"obskey_{kb._digest(['cmapi-ebay-sale', item_id, ended_at, amount_minor, currency, tcgdex_id, grader, grade])}"
    observation_id = kb._id("observation", idempotency_key)
    content_sha = kb._digest(
        {
            "item_id": item_id,
            "ended_at": ended_at,
            "event_time_precision": "DAY",
            "amount_minor": amount_minor,
            "currency": currency,
            "tcgdex_id": tcgdex_id,
            "grader": grader,
            "grade": grade,
            "payload_sha256": payload_sha256,
        }
    )
    created_at = kb._now()
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
            'DAY', %s, %s, NULL,
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
    price_id = kb._id("price", observation_id, "ITEM_PRICE")
    cur.execute(
        """
        INSERT INTO price_component (
            id, observation_id, component_type, amount_minor, currency,
            knowledge_state, inclusion_state, created_at
        ) VALUES (%s, %s, 'ITEM_PRICE', %s, %s, 'KNOWN', 'INCLUDED', %s)
        ON CONFLICT (observation_id, component_type) DO NOTHING
        """,
        (price_id, observation_id, amount_minor, currency, kb._now()),
    )
    cur.execute(
        "UPDATE market_observation SET lifecycle_state = 'SEALED', sealed_at = %s WHERE id = %s AND lifecycle_state = 'DRAFT'",
        (kb._now(), observation_id),
    )
    return "INSERTED"


def main() -> int:
    base._insert_metric = _safe_insert_metric
    base._insert_sale = _insert_sale_day_precision
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
