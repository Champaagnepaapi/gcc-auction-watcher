#!/usr/bin/env python3
"""Memory-only Cardova canonical-card + exact SALE_TRANSACTION persistence dry-run.

This module composes existing proven capabilities only:

- #204 exact Cardova commercial-identity rows;
- #205 exact identity -> Cardova P3 SOLD candidate gate;
- #194 Robot KB canonical hierarchy primitives;
- #199 P3 Cardova SALE_TRANSACTION builder/persistence semantics.

It deliberately does NOT write the user's PostgreSQL database. Every canonical
set/card, PROVEN Cardova identifier link and exact sale is created only inside a
fresh ``KnowledgeBase.open(':memory:')`` database.

A Cardova identity can be exact while still being unrepresentable by the current
P3 variant registry. In particular, P3 currently has no printing dimension/value
that can encode ``no_rarity_symbol`` or the positively-proven ordinary-vs-No-
Rarity distinction. Those rows remain blocked instead of being collapsed into a
finish-only canonical card.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Optional, Sequence


ROOT = Path(__file__).resolve().parents[2]
LOCAL_DIR = Path(__file__).resolve().parent
for candidate in (ROOT, LOCAL_DIR):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_exact_sale_candidate_dry_run as exact_sale  # noqa: E402
import robot_kb_cardova_sale_transaction_dry_run as sale_dry  # noqa: E402

from robot_kb.domain import ResolutionState  # noqa: E402
from robot_kb.repository import KnowledgeBase  # noqa: E402
from robot_kb.sidecar.models import ShadowDiagnostics  # noqa: E402
from robot_kb.sidecar.persistence import ShadowKnowledgePersistence  # noqa: E402


_FINISH = {
    "holo": "HOLO",
    "non_holo": "NON_HOLO",
    "normal": "NON_HOLO",
    "reverse": "REVERSE_HOLO",
}
_EDITION = {
    "first_edition": "FIRST_EDITION",
    "unlimited": "NO_FIRST_EDITION_STAMP",
}
_SPECIAL_FINISH = {
    "poke_ball": "POKE_BALL",
    "master_ball": "MASTER_BALL",
    "cosmos": "COSMOS",
    "galaxy": "GALAXY",
    "cracked_ice": "CRACKED_ICE",
}
_SHADOW = {
    "shadowless": "SHADOWLESS",
    "shadowed": "SHADOWED",
}
_SUPPORTED_SOURCE_DIMENSIONS = frozenset(
    {"finish", "edition", "special_finish", "shadow", "printing"}
)
_PRINTING_SCHEMA_GAP_REASON = "P3_SCHEMA_PRINTING_AXIS_UNREPRESENTABLE"


@dataclass(frozen=True)
class CanonicalPlan:
    source_native_record_id: str
    tcgdex_card_id: str
    tcgdex_set_id: str
    tcgdex_local_id: str
    canonical_set_key: str
    canonical_set_name: str
    family_name: str
    language_code: str
    profile_assignments: Mapping[str, str]
    applicability: Mapping[str, str]


class CanonicalDryRunError(RuntimeError):
    pass


def _norm(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _language_code(value: object) -> str:
    token = _norm(value).casefold()
    return {
        "ja": "ja",
        "jp": "ja",
        "japanese": "ja",
        "en": "en",
        "english": "en",
    }.get(token, "")


def _printing_material(identity: Mapping[str, Any]) -> bool:
    dims = identity.get("pinned_source_variant_dimensions")
    if isinstance(dims, Mapping) and _norm(dims.get("printing")):
        return True
    if _norm(identity.get("printing")):
        return True
    return _norm(identity.get("printing_applicability_reason")) == (
        "NO_RARITY_EXCLUDED_BY_REVIEWED_VISIBLE_RARITY_SYMBOL"
    )


def canonical_plan(
    identity: Mapping[str, Any],
    sale: Mapping[str, Any],
) -> tuple[Optional[CanonicalPlan], str]:
    if identity.get("macro_identity_exact") is not True:
        return None, "MACRO_IDENTITY_NOT_EXACT"
    if identity.get("microvariant_exact") is not True:
        return None, "MICROVARIANT_NOT_EXACT"
    if identity.get("exact_identity_link_candidate") is not True:
        return None, "EXACT_IDENTITY_LINK_CANDIDATE_FALSE"
    if identity.get("canonical_link_written") is True:
        return None, "CANONICAL_LINK_ALREADY_WRITTEN"
    if identity.get("remaining_unproven_axes") not in (None, [], ()):
        return None, "IDENTITY_AXES_STILL_UNPROVEN"

    source_id = _norm(identity.get("source_native_record_id"))
    if not source_id or source_id != _norm(sale.get("source_native_record_id")):
        return None, "SOURCE_NATIVE_ID_CONFLICT"

    set_id = _norm(identity.get("tcgdex_set_id"))
    local_id = _norm(identity.get("tcgdex_local_id"))
    card_id = _norm(identity.get("tcgdex_card_id"))
    if not set_id or not local_id or card_id != f"{set_id}-{local_id}":
        return None, "TCGDEX_COORDINATE_CONFLICT"

    set_name = _norm(identity.get("provider_set_label"))
    family_name = _norm(
        identity.get("card_name_provider_claim") or identity.get("card_name")
    )
    if not set_name or not family_name:
        return None, "CANONICAL_NAME_FIELDS_MISSING"

    language = _language_code(identity.get("language") or sale.get("language"))
    if language != "ja":
        return None, "CARDOVA_LEGACY_CANONICAL_LANGUAGE_UNSUPPORTED"

    dims_raw = identity.get("pinned_source_variant_dimensions")
    if not isinstance(dims_raw, Mapping) or not dims_raw:
        return None, "PINNED_SOURCE_VARIANT_DIMENSIONS_MISSING"
    dims = {
        _norm(key).casefold(): _norm(value).casefold()
        for key, value in dims_raw.items()
        if _norm(key) and _norm(value)
    }
    unknown = sorted(set(dims) - _SUPPORTED_SOURCE_DIMENSIONS)
    if unknown:
        return None, "P3_SCHEMA_SOURCE_DIMENSION_UNSUPPORTED:" + ",".join(unknown)

    # Printing is a material axis in #204. P3's current seed registry contains
    # no equivalent exact dimension/value, so neither No Rarity nor an ordinary
    # variant proven specifically by exclusion of No Rarity may be collapsed.
    if _printing_material(identity):
        return None, _PRINTING_SCHEMA_GAP_REASON

    finish = _FINISH.get(dims.get("finish", ""))
    if not finish:
        return None, "P3_FINISH_MAPPING_UNSUPPORTED"

    assignments: dict[str, str] = {"finish": finish}
    applicability: dict[str, str] = {"finish": "APPLICABLE"}

    edition = dims.get("edition", "")
    if edition:
        mapped = _EDITION.get(edition)
        if not mapped:
            return None, "P3_EDITION_MAPPING_UNSUPPORTED"
        assignments["edition_stamp"] = mapped
        applicability["edition_stamp"] = "APPLICABLE"
    elif (
        identity.get("edition_applicability_exact") is True
        and _norm(identity.get("edition_applicability_reason"))
        == "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT"
    ):
        applicability["edition_stamp"] = "NOT_APPLICABLE"

    special = dims.get("special_finish", "")
    if special:
        mapped = _SPECIAL_FINISH.get(special)
        if not mapped:
            return None, "P3_SPECIAL_FINISH_MAPPING_UNSUPPORTED"
        assignments["foil_pattern"] = mapped
        applicability["foil_pattern"] = "APPLICABLE"
    elif (
        identity.get("special_finish_applicability_exact") is True
        and _norm(identity.get("special_finish_applicability_reason"))
        == "NOT_APPLICABLE_IN_PINNED_SOURCE_VARIANT"
    ):
        applicability["foil_pattern"] = "NOT_APPLICABLE"

    shadow = dims.get("shadow", "")
    if shadow:
        mapped = _SHADOW.get(shadow)
        if not mapped:
            return None, "P3_SHADOW_MAPPING_UNSUPPORTED"
        assignments["shadow_treatment"] = mapped
        applicability["shadow_treatment"] = "APPLICABLE"

    return (
        CanonicalPlan(
            source_native_record_id=source_id,
            tcgdex_card_id=card_id,
            tcgdex_set_id=set_id,
            tcgdex_local_id=local_id,
            canonical_set_key=f"tcgdex:{language}:{set_id}",
            canonical_set_name=set_name,
            family_name=family_name,
            language_code=language,
            profile_assignments=dict(sorted(assignments.items())),
            applicability=dict(sorted(applicability.items())),
        ),
        "P3_CANONICAL_PLAN_READY",
    )


def _family_key(plan: CanonicalPlan) -> tuple[str, str, str]:
    return (plan.canonical_set_key, plan.tcgdex_local_id, plan.family_name.casefold())


def _family_applicability(plans: Sequence[CanonicalPlan]) -> Mapping[tuple[str, str, str], Mapping[str, str]]:
    grouped: dict[tuple[str, str, str], list[CanonicalPlan]] = defaultdict(list)
    for plan in plans:
        grouped[_family_key(plan)].append(plan)

    output: dict[tuple[str, str, str], Mapping[str, str]] = {}
    for key, rows in grouped.items():
        dimensions = sorted({dim for row in rows for dim in row.applicability})
        family: dict[str, str] = {}
        for dimension in dimensions:
            states = {row.applicability.get(dimension) for row in rows if dimension in row.applicability}
            # A dimension is family-level APPLICABLE if any exact variant assigns
            # it. NOT_APPLICABLE is accepted only when every observed exact row
            # with a statement agrees and no row assigns the dimension.
            if "APPLICABLE" in states:
                family[dimension] = "APPLICABLE"
            elif states == {"NOT_APPLICABLE"}:
                family[dimension] = "NOT_APPLICABLE"
            else:
                raise CanonicalDryRunError(
                    f"family applicability conflict for {key}: {dimension}={sorted(states)}"
                )
        output[key] = dict(sorted(family.items()))
    return output


def _persist_canonical_in_memory(
    kb: KnowledgeBase,
    plan: CanonicalPlan,
    family_applicability: Mapping[str, str],
) -> str:
    set_id = kb.create_canonical_set(plan.canonical_set_key, plan.canonical_set_name)
    family_id = kb.create_card_family(set_id, plan.tcgdex_local_id, plan.family_name)
    localized_id = kb.create_localized_card(
        family_id,
        plan.language_code,
        plan.family_name,
        localized_set_name=plan.canonical_set_name,
    )
    for dimension, state in family_applicability.items():
        kb.set_family_variant_applicability(family_id, dimension, state)
    profile_id = kb.create_variant_profile(
        plan.profile_assignments,
        label=f"Cardova exact via TCGdex {plan.tcgdex_card_id}",
    )
    kb.allow_variant_profile(family_id, profile_id)
    return kb.create_canonical_card(localized_id, profile_id)


def _link_cardova_identifier_in_memory(
    kb: KnowledgeBase,
    *,
    source_id: str,
    canonical_card_id: str,
) -> None:
    source_system_id = kb.create_source_system(
        sale_dry.SOURCE_CODE,
        sale_dry.SOURCE_NAME,
        sale_dry.SOURCE_ROLE,
    )
    object_id = kb.create_external_object(
        source_system_id,
        "LISTING",
        source_id,
    )
    identifier_id = kb.add_external_identifier(
        object_id,
        "CARDOVA_AUCTION_ULID",
        source_id,
    )
    kb.link_identifier(
        identifier_id,
        ResolutionState.PROVEN,
        canonical_card_id=canonical_card_id,
    )


def _stored_sale_snapshot(kb: KnowledgeBase, source_id: str) -> Mapping[str, Any]:
    row = kb.connection.execute(
        """
        SELECT observation.id, observation.canonical_card_id,
               resolution.resolution_state
        FROM market_observation AS observation
        LEFT JOIN observation_identity_link AS oil
          ON oil.observation_id = observation.id AND oil.link_role = 'RESOLVED_AS'
        LEFT JOIN identity_resolution AS resolution
          ON resolution.id = oil.identity_resolution_id
        WHERE observation.source_native_record_id = ?
          AND observation.observation_type = 'SALE_TRANSACTION'
          AND observation.lifecycle_state = 'SEALED'
        ORDER BY observation.created_at, observation.id
        """,
        (source_id,),
    ).fetchall()
    if len(row) != 1:
        raise CanonicalDryRunError(
            f"expected one in-memory exact sale for {source_id}; got {len(row)}"
        )
    price = kb.connection.execute(
        """
        SELECT component_type, amount_minor, currency
        FROM price_component
        WHERE observation_id = ?
        """,
        (row[0]["id"],),
    ).fetchall()
    return {
        "observation_id": row[0]["id"],
        "canonical_card_id": row[0]["canonical_card_id"],
        "resolution_state": row[0]["resolution_state"],
        "prices": [tuple(item) for item in price],
    }


def run_memory_dry_run(
    sales: Sequence[Mapping[str, Any]],
    identity_rows: Sequence[Mapping[str, Any]],
    *,
    observed_at: Optional[str] = None,
    replay: bool = True,
) -> Mapping[str, Any]:
    observed = observed_at or datetime.now(timezone.utc).isoformat()

    exact = exact_sale.compose_exact_sale_candidates(
        sales,
        identity_rows,
        observed_at=observed,
    )
    candidate_ids = {
        _norm(row.get("source_native_record_id"))
        for row in exact.get("records", [])
        if _norm(row.get("source_native_record_id"))
    }
    sale_by_id = {
        _norm(row.get("source_native_record_id")): row
        for row in sales
        if _norm(row.get("source_native_record_id")) in candidate_ids
    }
    identity_by_id = {
        _norm(row.get("source_native_record_id")): row
        for row in identity_rows
        if _norm(row.get("source_native_record_id")) in candidate_ids
    }

    blocked: Counter[str] = Counter()
    plans: list[CanonicalPlan] = []
    for source_id in sorted(candidate_ids):
        identity = identity_by_id.get(source_id)
        sale = sale_by_id.get(source_id)
        if identity is None or sale is None:
            blocked["EXACT_CANDIDATE_JOIN_MISSING"] += 1
            continue
        plan, reason = canonical_plan(identity, sale)
        if plan is None:
            blocked[reason] += 1
            continue
        plans.append(plan)

    family_applicability = _family_applicability(plans)
    plan_by_id = {plan.source_native_record_id: plan for plan in plans}

    diagnostics = ShadowDiagnostics()
    replay_diagnostics = ShadowDiagnostics()
    canonical_by_source: dict[str, str] = {}
    exact_sale_rows = 0
    hammer_rows = 0

    with KnowledgeBase.open(":memory:") as kb:
        persistence = ShadowKnowledgePersistence(kb)
        for source_id in sorted(plan_by_id):
            plan = plan_by_id[source_id]
            identity = identity_by_id[source_id]
            sale = sale_by_id[source_id]
            try:
                card_id = _persist_canonical_in_memory(
                    kb,
                    plan,
                    family_applicability[_family_key(plan)],
                )
                _link_cardova_identifier_in_memory(
                    kb,
                    source_id=source_id,
                    canonical_card_id=card_id,
                )
                built, sale_reason = sale_dry.build_p3_sale(
                    sale,
                    observed_at=observed,
                )
                if built is None:
                    raise CanonicalDryRunError(f"P3_SALE_CONTRACT:{sale_reason}")
                raw, observation = built
                exact_observation = replace(
                    observation,
                    unresolved_dimensions=(),
                    exact_identity_eligible=True,
                )
                persistence.ingest(raw, (exact_observation,), diagnostics)
                snap = _stored_sale_snapshot(kb, source_id)
                if snap["canonical_card_id"] != card_id:
                    raise CanonicalDryRunError("EXACT_SALE_CANONICAL_CARD_CONFLICT")
                if snap["resolution_state"] != "PROVEN":
                    raise CanonicalDryRunError("EXACT_SALE_RESOLUTION_NOT_PROVEN")
                if snap["prices"] != [("HAMMER_PRICE", int(sale["final_bid_jpy"]), "JPY")]:
                    raise CanonicalDryRunError("EXACT_SALE_HAMMER_PRICE_CONFLICT")
                canonical_by_source[source_id] = card_id
                exact_sale_rows += 1
                hammer_rows += 1
            except Exception as error:
                blocked[f"MEMORY_PERSIST:{type(error).__name__}:{error}"] += 1

        if replay:
            for source_id in sorted(canonical_by_source):
                sale = sale_by_id[source_id]
                built, sale_reason = sale_dry.build_p3_sale(sale, observed_at=observed)
                if built is None:
                    raise CanonicalDryRunError(f"replay P3_SALE_CONTRACT:{sale_reason}")
                raw, observation = built
                persistence.ingest(
                    raw,
                    (
                        replace(
                            observation,
                            unresolved_dimensions=(),
                            exact_identity_eligible=True,
                        ),
                    ),
                    replay_diagnostics,
                )

        canonical_cards = int(
            kb.connection.execute("SELECT COUNT(*) AS n FROM canonical_card").fetchone()["n"]
        )
        proven_cardova_links = int(
            kb.connection.execute(
                """
                SELECT COUNT(*) AS n
                FROM identifier_link AS link
                JOIN external_identifier AS identifier
                  ON identifier.id = link.external_identifier_id
                WHERE identifier.namespace = 'CARDOVA_AUCTION_ULID'
                  AND link.resolution_state = 'PROVEN'
                """
            ).fetchone()["n"]
        )
        stored_exact_sales = int(
            kb.connection.execute(
                """
                SELECT COUNT(*) AS n FROM market_observation
                WHERE observation_type = 'SALE_TRANSACTION'
                  AND lifecycle_state = 'SEALED'
                  AND canonical_card_id IS NOT NULL
                """
            ).fetchone()["n"]
        )

    return {
        "sales_input_count": len(sales),
        "identity_input_count": len(identity_rows),
        "exact_sale_candidates_from_205": int(exact.get("exact_card_sale_candidate_count", 0)),
        "exact_sale_candidate_blocked_from_205": dict(exact.get("blocked", {})),
        "p3_schema_representable_count": len(plans),
        "p3_schema_blocked_count": len(candidate_ids) - len(plans),
        "blocked": dict(sorted(blocked.items())),
        "canonical_cards_created_in_memory": canonical_cards,
        "proven_cardova_identifier_links_in_memory": proven_cardova_links,
        "exact_sale_transactions_in_memory": stored_exact_sales,
        "exact_sale_rows_verified": exact_sale_rows,
        "hammer_price_jpy_rows_verified": hammer_rows,
        "exact_identity_links_reported": int(diagnostics.exact_identities_linked),
        "sale_transactions_stored_reported": int(diagnostics.sale_transactions_stored),
        "replay_executed": bool(replay),
        "duplicate_sale_replays": int(replay_diagnostics.duplicate_sale_replays),
        "durable_robot_kb_write": False,
        "local_postgres_write": False,
        "canonical_link_written_durably": False,
        "sale_transaction_written_durably": False,
        "v4_economic_use": False,
    }


def safe_summary() -> Mapping[str, Any]:
    return {
        "mode": "MEMORY_ONLY_CARDOVA_CANONICAL_CARD_EXACT_SALE_PERSISTENCE_DRY_RUN",
        "predecessor_194_canonical_pattern_reused": True,
        "predecessor_195_batch_pattern_reused": True,
        "cardova_205_exact_sale_gate_reused": True,
        "p3_sale_builder_reused": True,
        "tcgdex_bare_card_id_link_created": False,
        "printing_schema_gap_fail_closed": True,
        "database": ":memory:",
        "durable_robot_kb_write": False,
        "local_postgres_write": False,
        "v4_economic_use": False,
        "notification_sent": False,
        "automatic_purchase": False,
        "automatic_bid": False,
        "automatic_offer": False,
        "automatic_checkout": False,
        "automatic_payment": False,
    }


def _records(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("records"), list):
        raise ValueError(f"{path} must contain object records[]")
    rows = payload["records"]
    if any(not isinstance(row, Mapping) for row in rows):
        raise ValueError(f"{path} records[] must contain objects")
    return list(rows)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Memory-only Cardova canonical-card + exact SALE_TRANSACTION persistence dry-run"
    )
    parser.add_argument("--sales-input", type=Path, required=True)
    parser.add_argument("--identity-input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observed-at", default="")
    args = parser.parse_args(argv)

    payload = dict(safe_summary())
    code = 1
    try:
        payload.update(
            run_memory_dry_run(
                _records(args.sales_input),
                _records(args.identity_input),
                observed_at=_norm(args.observed_at) or None,
            )
        )
        payload["error"] = None
        code = 0
    except Exception as error:
        payload["error"] = f"{type(error).__name__}: {error}"

    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
