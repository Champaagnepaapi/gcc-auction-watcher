from __future__ import annotations

from typing import Any

import psycopg

from . import neon_source_scout_ingest as base


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
    source_updated_at: str | None,
    amount_minor: int | None = None,
    currency: str | None = None,
    sample_size: int | None = None,
    event_at: str | None = None,
    window_started_at: str | None = None,
    window_ended_at: str | None = None,
) -> bool:
    """Insert a provider metric using the KB's required DRAFT -> fact -> SEALED lifecycle."""
    if amount_minor is None:
        currency = None

    metric_content = {
        "source_record_id": source_record_id,
        "source_native_record_id": source_native_record_id,
        "metric_name": metric_name,
        "amount_minor": amount_minor,
        "currency": currency,
        "sample_size": sample_size,
        "event_at": event_at,
        "window_started_at": window_started_at,
        "window_ended_at": window_ended_at,
        "payload_sha256": payload_sha256,
    }
    content_sha = base._digest(metric_content)
    idempotency_key = f"obskey_{base._digest(['pokemonpricetracker', source_native_record_id, payload_sha256])}"
    observation_id = base._id("observation", idempotency_key)
    created_at = base._now()
    event_value = event_at or source_updated_at or observed_at

    # The database explicitly requires observations to begin as unsealed DRAFTs.
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
            'EXACT', %s, %s, %s,
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
            observed_at,
            created_at,
            source_updated_at,
            created_at,
        ),
    )
    inserted = cur.rowcount > 0

    cur.execute(
        "SELECT id, lifecycle_state FROM market_observation WHERE idempotency_key = %s",
        (idempotency_key,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"market_observation missing after upsert: {source_native_record_id}")
    observation_id, lifecycle_state = str(row[0]), str(row[1])

    # Add the typed fact while the parent observation is still mutable only by sealing.
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

    # Seal only after the typed fact exists, as enforced by the KB trigger.
    if lifecycle_state == "DRAFT":
        cur.execute(
            """
            UPDATE market_observation
               SET lifecycle_state = 'SEALED', sealed_at = %s
             WHERE id = %s AND lifecycle_state = 'DRAFT'
            """,
            (base._now(), observation_id),
        )

    return inserted


def main() -> int:
    base._insert_metric = _insert_metric
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
