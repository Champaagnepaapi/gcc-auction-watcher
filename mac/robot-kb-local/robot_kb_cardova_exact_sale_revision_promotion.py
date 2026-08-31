#!/usr/bin/env python3
"""Promote an existing unresolved Cardova sale through an append-only revision.

The durable Cardova collector already stored the economic SALE_TRANSACTION while
canonical identity was unresolved.  This module never edits that sealed fact.
Instead it creates a new sealed ``REVISION_OF`` observation with the same source,
event, fact and prices, but with a proven canonical card, then supersedes the
old UNKNOWN identity resolution with a PROVEN resolution.

The helpers are backend-neutral so the behavior can be validated on the pinned
P3 SQLite runtime before any PostgreSQL rollback rehearsal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Mapping, Optional


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_print_run_exact_sale_dry_run as print_run  # noqa: E402

from robot_kb.domain import (  # noqa: E402
    InclusionState,
    ObservationType,
    PriceKnowledge,
    ResolutionState,
)
from robot_kb.repository import KnowledgeBase, PriceComponent  # noqa: E402


class RevisionPromotionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PromotionResult:
    source_native_record_id: str
    original_observation_id: str
    revision_observation_id: str
    canonical_card_id: str
    proven_resolution_id: str
    replayed: bool


def _norm(value: object) -> str:
    return print_run.base._norm(value)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _price_components(kb: KnowledgeBase, observation_id: str) -> tuple[PriceComponent, ...]:
    rows = kb.connection.execute(
        """
        SELECT component_type, amount_minor, currency,
               knowledge_state, inclusion_state
        FROM price_component
        WHERE observation_id = ?
        ORDER BY component_type
        """,
        (observation_id,),
    ).fetchall()
    return tuple(
        PriceComponent(
            row["component_type"],
            row["amount_minor"],
            row["currency"],
            knowledge_state=PriceKnowledge(row["knowledge_state"]),
            inclusion_state=InclusionState(row["inclusion_state"]),
        )
        for row in rows
    )


def _sale_fact(kb: KnowledgeBase, observation_id: str) -> Mapping[str, Any]:
    row = kb.connection.execute(
        """
        SELECT listing_started_at, sale_occurred_at, transaction_status
        FROM sale_transaction WHERE observation_id = ?
        """,
        (observation_id,),
    ).fetchone()
    if row is None:
        raise RevisionPromotionError("existing observation has no SALE_TRANSACTION fact")
    return {
        "listing_started_at": row["listing_started_at"],
        "sale_occurred_at": row["sale_occurred_at"],
        "transaction_status": row["transaction_status"],
    }


def _leaf_unresolved_sale(
    kb: KnowledgeBase,
    source_id: str,
    *,
    expected_event_at: str,
    expected_hammer_jpy: int,
) -> Mapping[str, Any]:
    rows = kb.connection.execute(
        """
        SELECT observation.*
        FROM market_observation AS observation
        JOIN source_system AS source ON source.id = observation.source_system_id
        JOIN sale_transaction AS sale ON sale.observation_id = observation.id
        WHERE source.code = 'cardova'
          AND observation.source_native_record_id = ?
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND observation.lifecycle_state = 'SEALED'
          AND observation.canonical_card_id IS NULL
          AND sale.transaction_status = 'COMPLETED'
          AND NOT EXISTS (
              SELECT 1
              FROM observation_relationship AS relationship
              JOIN market_observation AS revision
                ON revision.id = relationship.from_observation_id
              WHERE relationship.to_observation_id = observation.id
                AND relationship.relationship_type = 'REVISION_OF'
                AND revision.lifecycle_state = 'SEALED'
          )
        ORDER BY observation.created_at, observation.id
        """,
        (source_id,),
    ).fetchall()
    if len(rows) != 1:
        raise RevisionPromotionError(
            f"expected one leaf unresolved Cardova sale for {source_id}; got {len(rows)}"
        )
    row = rows[0]
    if _norm(row["event_at"]) != _norm(expected_event_at):
        raise RevisionPromotionError("existing sale event_at conflicts with proven sale")
    prices = _price_components(kb, row["id"])
    economic = [
        component
        for component in prices
        if component.component_type != "SHIPPING"
    ]
    if len(economic) != 1:
        raise RevisionPromotionError("existing sale does not have one final economic price")
    price = economic[0]
    if (
        price.component_type != "HAMMER_PRICE"
        or price.amount_minor != int(expected_hammer_jpy)
        or price.currency != "JPY"
        or price.knowledge_state != PriceKnowledge.KNOWN
    ):
        raise RevisionPromotionError("existing sale HAMMER_PRICE JPY conflicts with proven sale")
    return row


def _subject_and_latest_resolution(
    kb: KnowledgeBase, observation_id: str
) -> tuple[str, str]:
    rows = kb.connection.execute(
        """
        SELECT resolution.identity_subject_id, resolution.id,
               resolution.resolution_state
        FROM observation_identity_link AS link
        JOIN identity_resolution AS resolution
          ON resolution.id = link.identity_resolution_id
        WHERE link.observation_id = ?
          AND link.link_role = 'SUBJECT'
        ORDER BY resolution.created_at DESC, resolution.id DESC
        """,
        (observation_id,),
    ).fetchall()
    if not rows:
        raise RevisionPromotionError("existing unresolved sale has no SUBJECT identity resolution")
    subject_ids = {row["identity_subject_id"] for row in rows}
    if len(subject_ids) != 1:
        raise RevisionPromotionError("existing sale has multiple identity subjects")
    latest = rows[0]
    if latest["resolution_state"] != "UNKNOWN":
        raise RevisionPromotionError("leaf unresolved sale latest identity is not UNKNOWN")
    return latest["identity_subject_id"], latest["id"]


def _existing_exact_revision(
    kb: KnowledgeBase,
    original_observation_id: str,
    canonical_card_id: str,
    *,
    expected_event_at: str,
    expected_hammer_jpy: int,
) -> Optional[tuple[str, str]]:
    rows = kb.connection.execute(
        """
        SELECT revision.id, resolution.id AS resolution_id
        FROM observation_relationship AS relationship
        JOIN market_observation AS revision
          ON revision.id = relationship.from_observation_id
        JOIN observation_identity_link AS link
          ON link.observation_id = revision.id AND link.link_role = 'RESOLVED_AS'
        JOIN identity_resolution AS resolution
          ON resolution.id = link.identity_resolution_id
        WHERE relationship.to_observation_id = ?
          AND relationship.relationship_type = 'REVISION_OF'
          AND revision.lifecycle_state = 'SEALED'
          AND revision.observation_type = 'SALE_TRANSACTION'
          AND revision.canonical_card_id = ?
          AND link.canonical_card_id = ?
          AND resolution.resolution_state = 'PROVEN'
          AND resolution.canonical_card_id = ?
        ORDER BY revision.created_at, revision.id
        """,
        (
            original_observation_id,
            canonical_card_id,
            canonical_card_id,
            canonical_card_id,
        ),
    ).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise RevisionPromotionError("multiple exact revisions already exist")
    revision_id = rows[0]["id"]
    revision = kb.fetch_observation(revision_id)
    if _norm(revision["event_at"]) != _norm(expected_event_at):
        raise RevisionPromotionError("existing exact revision event conflicts")
    prices = _price_components(kb, revision_id)
    economic = [component for component in prices if component.component_type != "SHIPPING"]
    if len(economic) != 1 or (
        economic[0].component_type != "HAMMER_PRICE"
        or economic[0].amount_minor != int(expected_hammer_jpy)
        or economic[0].currency != "JPY"
    ):
        raise RevisionPromotionError("existing exact revision price conflicts")
    return revision_id, rows[0]["resolution_id"]


def promote_existing_sale(
    kb: KnowledgeBase,
    identity: Mapping[str, Any],
    sale: Mapping[str, Any],
    *,
    ingested_at: Optional[str] = None,
) -> PromotionResult:
    source_id = _norm(sale.get("source_native_record_id"))
    if not source_id or source_id != _norm(identity.get("source_native_record_id")):
        raise RevisionPromotionError("identity/sale source id mismatch")
    event_at = _norm(sale.get("auction_end_at_utc"))
    hammer = sale.get("final_bid_jpy")
    if not event_at or not isinstance(hammer, int) or hammer <= 0:
        raise RevisionPromotionError("proven sale economics are incomplete")

    plan, reason = print_run.canonical_plan(identity, sale)
    if plan is None:
        raise RevisionPromotionError(f"canonical plan blocked: {reason}")

    original = _leaf_unresolved_sale(
        kb,
        source_id,
        expected_event_at=event_at,
        expected_hammer_jpy=hammer,
    )
    subject_id, old_resolution_id = _subject_and_latest_resolution(kb, original["id"])

    family_applicability = print_run.base._family_applicability([plan])
    card_id = print_run.base._persist_canonical_in_memory(
        kb,
        plan,
        family_applicability[print_run.base._family_key(plan)],
    )
    print_run.base._link_cardova_identifier_in_memory(
        kb,
        source_id=source_id,
        canonical_card_id=card_id,
    )

    existing = _existing_exact_revision(
        kb,
        original["id"],
        card_id,
        expected_event_at=event_at,
        expected_hammer_jpy=hammer,
    )
    if existing is not None:
        return PromotionResult(
            source_id,
            original["id"],
            existing[0],
            card_id,
            existing[1],
            True,
        )

    fact = _sale_fact(kb, original["id"])
    prices = _price_components(kb, original["id"])
    revision_id = kb.append_market_observation(
        ObservationType.SALE_TRANSACTION,
        original["source_system_id"],
        original["source_native_record_id"],
        observed_at=original["observed_at"],
        ingested_at=ingested_at or _utc_now(),
        source_updated_at=original["source_updated_at"],
        source_record_id=original["source_record_id"],
        upstream_market_system_id=original["upstream_market_system_id"],
        upstream_event_object_id=original["upstream_event_object_id"],
        canonical_card_id=card_id,
        event_at=original["event_at"],
        event_time_precision=original["event_time_precision"],
        revision_of_observation_id=original["id"],
        fact=fact,
        prices=prices,
    )
    proven_resolution_id = kb.create_identity_resolution(
        subject_id,
        ResolutionState.PROVEN,
        canonical_card_id=card_id,
        unresolved_dimensions=(),
        conflicts=(),
        supersedes_resolution_id=old_resolution_id,
    )
    kb.link_observation_identity(
        revision_id,
        proven_resolution_id,
        canonical_card_id=card_id,
        link_role="RESOLVED_AS",
    )
    return PromotionResult(
        source_id,
        original["id"],
        revision_id,
        card_id,
        proven_resolution_id,
        False,
    )


def leaf_sale_state(kb: KnowledgeBase, source_id: str) -> Mapping[str, int]:
    row = kb.connection.execute(
        """
        SELECT
          SUM(CASE WHEN observation.canonical_card_id IS NULL THEN 1 ELSE 0 END) AS unresolved,
          SUM(CASE WHEN observation.canonical_card_id IS NOT NULL THEN 1 ELSE 0 END) AS exact,
          COUNT(*) AS total
        FROM market_observation AS observation
        JOIN source_system AS source ON source.id = observation.source_system_id
        WHERE source.code = 'cardova'
          AND observation.source_native_record_id = ?
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND observation.lifecycle_state = 'SEALED'
          AND NOT EXISTS (
              SELECT 1
              FROM observation_relationship AS relationship
              JOIN market_observation AS revision
                ON revision.id = relationship.from_observation_id
              WHERE relationship.to_observation_id = observation.id
                AND relationship.relationship_type = 'REVISION_OF'
                AND revision.lifecycle_state = 'SEALED'
          )
        """,
        (source_id,),
    ).fetchone()
    return {
        "unresolved": int(row["unresolved"] or 0),
        "exact": int(row["exact"] or 0),
        "total": int(row["total"] or 0),
    }


def safe_summary() -> Mapping[str, Any]:
    return {
        "mode": "APPEND_ONLY_CARDOVA_EXACT_SALE_REVISION_PROMOTION",
        "sealed_original_updated": False,
        "revision_relationship": "REVISION_OF",
        "economic_fact_changed": False,
        "exact_identity_resolution": "PROVEN",
        "unresolved_leaf_excluded_after_revision": True,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
        "v4_economic_use": False,
    }
