from __future__ import annotations

from typing import Any, Mapping, Sequence


P3_LISTING_FACT_FIELDS = frozenset({"listing_started_at", "snapshot_status", "quantity"})
P3_PROVIDER_METRIC_FACT_FIELDS = frozenset(
    {
        "metric_name",
        "metric_value_minor",
        "currency",
        "window_started_at",
        "window_ended_at",
        "sample_size",
    }
)


def listing_fact(listing: Any) -> dict[str, Any]:
    """Return only fields accepted by the pinned Robot KB P3 LISTING_SNAPSHOT schema."""

    return {
        "listing_started_at": None,
        "snapshot_status": str(listing.evidence_type),
        "quantity": 1,
    }


def provider_metric_fact(metric: Any) -> dict[str, Any]:
    """Return only fields accepted by the pinned P3 PROVIDER_METRIC schema.

    Evidence semantics that P3 has no dedicated columns for remain preserved in
    the immutable raw provider payload and in the metric name/market. They must
    never be promoted into item-level SOLD evidence.
    """

    return {
        "metric_name": metric.name,
        "metric_value_minor": metric.amount_minor,
        "currency": metric.currency,
        "window_started_at": None,
        "window_ended_at": metric.event_at,
        "sample_size": metric.sample_size,
    }


def install(harvest: Any) -> None:
    """Install the narrow compatibility layer required by runtime P3.

    PR #180 deliberately reuses the immutable P3 runtime. The first physical Mac
    run proved that its normalized fact schema is stricter than the new harvester
    payload. This adapter keeps P3 unchanged and strips only unsupported normalized
    columns while retaining raw payload/provenance.
    """

    if getattr(harvest, "_robot_kb_p3_compat_installed", False):
        return

    original_request_json = harvest.request_json

    def strict_request_json(
        session: Any,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, Any],
        timeout: float,
        diag: Any,
        provider: str,
    ) -> tuple[int, object, Mapping[str, Any]]:
        status, payload, response_headers = original_request_json(
            session, url, headers, params, timeout, diag, provider
        )
        # Authentication/entitlement failures must be fail-visible. The original
        # #180 implementation logged 401/403 but returned source_failures=0.
        if status in {401, 403}:
            diag.source_failures += 1
        return status, payload, response_headers

    def persist_metrics(
        kb: Any,
        metrics: Sequence[Any],
        raw: Mapping[str, Any],
        raw_id: str,
        source: str,
        observed_at: str,
    ) -> int:
        (
            _InclusionState,
            ObservationType,
            SourceKind,
            _KnowledgeBase,
            _PriceComponent,
            IdentityClaim,
            NormalizedObservation,
            RawSourceRecord,
            ShadowDiagnostics,
            ShadowKnowledgePersistence,
        ) = harvest.runtime()
        source_name = "PokeTrace" if source == "poketrace" else "PokemonPriceTracker"
        observations = []
        for metric in metrics:
            if harvest.observation_exists(
                kb,
                source,
                metric.native_id,
                ObservationType.PROVIDER_METRIC_OBSERVATION.value,
            ):
                continue
            observations.append(
                NormalizedObservation(
                    observation_type=ObservationType.PROVIDER_METRIC_OBSERVATION,
                    source_native_record_id=metric.native_id,
                    observed_at=metric.observed_at,
                    source_updated_at=metric.event_at,
                    event_at=metric.event_at,
                    event_time_precision=metric.precision,
                    fact=provider_metric_fact(metric),
                    upstream_market_code=metric.market or None,
                    upstream_market_name=metric.market or None,
                    identity_subject_type=f"{source.upper()}_MARKET_METRIC",
                    identity_subject_label=f"{source_name} {metric.card_id} {metric.name}",
                    identity_namespace=f"{source.upper()}_CARD_ID",
                    identity_identifier_value=metric.card_id,
                    unresolved_dimensions=("canonical_identity", "commercial_microvariant"),
                    claims=tuple(
                        IdentityClaim(key, value, SourceKind.PROVIDER)
                        for key, value in metric.claims
                        if value
                    ),
                    exact_identity_eligible=False,
                    genuine_sale_evidence=False,
                )
            )
        record = RawSourceRecord(
            source_code=source,
            source_name=source_name,
            source_role="PROVIDER",
            source_native_record_id=raw_id,
            payload=dict(raw),
            retrieved_at=observed_at,
            object_type="PROVIDER_RESPONSE",
            external_native_id=raw_id,
        )
        ShadowKnowledgePersistence(kb).ingest(
            record, tuple(observations), ShadowDiagnostics()
        )
        return len(observations)

    def persist_listing(kb: Any, listing: Any) -> None:
        (
            InclusionState,
            ObservationType,
            SourceKind,
            _KnowledgeBase,
            PriceComponent,
            IdentityClaim,
            NormalizedObservation,
            RawSourceRecord,
            ShadowDiagnostics,
            ShadowKnowledgePersistence,
        ) = harvest.runtime()
        payload = harvest.marketplace_payload(listing)
        identity = payload["identity"]
        native = str(listing.source_id or listing.source_url or listing.stable_key)
        amount = harvest.minor(listing.price)
        prices = (
            ()
            if amount is None
            else (
                PriceComponent(
                    "ITEM_PRICE",
                    amount,
                    str(listing.currency).upper(),
                    inclusion_state=InclusionState.UNKNOWN,
                ),
            )
        )
        claim_rows = tuple(
            (key, str(value))
            for key, value in (
                ("card_name", identity["name"]),
                ("set", identity["set_name"]),
                ("collector_number", identity["number"]),
                ("language", identity["language"]),
                ("grader", identity["grader"]),
                ("grade", identity["grade"]),
                ("edition", identity["edition"]),
                ("finish", identity["finish"]),
                ("variant", identity["variant"]),
                ("listing_url", payload["source_url"]),
                ("evidence_type", payload["evidence_type"]),
            )
            if value not in (None, "")
        )
        record = RawSourceRecord(
            source_code=str(listing.market).casefold(),
            source_name=str(listing.market),
            source_role="LISTING_PLATFORM",
            source_native_record_id=native,
            payload=payload,
            retrieved_at=listing.observed_at.isoformat(),
            object_type="LISTING",
            external_native_id=native,
        )
        observation = NormalizedObservation(
            observation_type=ObservationType.LISTING_SNAPSHOT,
            source_native_record_id=native,
            observed_at=listing.observed_at.isoformat(),
            fact=listing_fact(listing),
            prices=prices,
            identity_subject_type="MARKETPLACE_LISTING_OBSERVATION",
            identity_subject_label=f"{listing.market} listing {native}",
            identity_namespace="COMMERCIAL_IDENTITY_STRICT_KEY",
            identity_identifier_value=listing.identity.strict_key,
            unresolved_dimensions=()
            if listing.identity_proven
            else ("commercial_identity",),
            claims=tuple(
                IdentityClaim(key, value, SourceKind.LISTING)
                for key, value in claim_rows
            ),
            exact_identity_eligible=bool(listing.identity_proven),
            genuine_sale_evidence=False,
        )
        ShadowKnowledgePersistence(kb).ingest(
            record, (observation,), ShadowDiagnostics()
        )

    harvest.request_json = strict_request_json
    harvest.persist_metrics = persist_metrics
    harvest.persist_listing = persist_listing
    harvest._robot_kb_p3_compat_installed = True
