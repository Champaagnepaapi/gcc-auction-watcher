"""Durable fair queueing for marketplace-first bootstrap/retries.

Each still-pending listing gets a bounded attempt counter in discovery state.
Unattempted inventory is always drained before retrying transient provider rows,
while known GCC SOLD discounts keep economic priority inside the same attempt
round. This prevents one outage/pending provider from starving the rest of the
marketplace bootstrap.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

import v4_global_marketplace_discovery as discovery
import v4_global_marketplace_hardening as hardening
import v4_global_marketplace_notify as marketplace
from v4_global_market_core import AUCTION_SNAPSHOT_LE5, FIXED_ASK


_ORIGINAL_LOAD = discovery.load_discovery_state
_ORIGINAL_RECONCILE = discovery.reconcile_inventory
_INSTALLED = False


def load_discovery_state_with_attempts(path, *, strict: bool):
    state, status = _ORIGINAL_LOAD(path, strict=strict)
    attempts: dict[str, int] = {}
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            candidate = raw.get("attempts") if isinstance(raw, Mapping) else None
            if isinstance(candidate, Mapping):
                valid_keys = set(state.get("listings", {}))
                for key, value in candidate.items():
                    if str(key) not in valid_keys:
                        continue
                    try:
                        count = max(0, int(value))
                    except (TypeError, ValueError):
                        continue
                    attempts[str(key)] = min(count, 1_000_000)
        except Exception:
            # The canonical loader already owns corruption/fail-closed semantics.
            # Optional attempt metadata must never weaken that gate.
            pass
    state["attempts"] = attempts
    return state, status


def reconcile_inventory_with_attempts(state, listings, *, observed_at, complete_markets=()):
    output, counters = _ORIGINAL_RECONCILE(
        state,
        listings,
        observed_at=observed_at,
        complete_markets=complete_markets,
    )
    previous_pending = {
        str(key)
        for key in (state.get("pending") if isinstance(state.get("pending"), list) else [])
    }
    previous_attempts = state.get("attempts") if isinstance(state.get("attempts"), Mapping) else {}
    attempts: dict[str, int] = {}
    for raw in output.get("pending", []):
        key = str(raw)
        if key in previous_pending:
            try:
                attempts[key] = max(0, int(previous_attempts.get(key, 0)))
            except (TypeError, ValueError):
                attempts[key] = 0
        else:
            attempts[key] = 0
    output["attempts"] = attempts
    return output, counters


def select_pending_fair_round_robin(state, current, *, limit: int):
    pending = state.get("pending") if isinstance(state.get("pending"), list) else []
    attempts = state.get("attempts")
    if not isinstance(attempts, dict):
        attempts = {}
        state["attempts"] = attempts

    ranked = []
    for index, raw in enumerate(pending):
        key = str(raw or "")
        listing = current.get(key)
        if listing is None:
            continue
        try:
            attempt_count = max(0, int(attempts.get(key, 0)))
        except (TypeError, ValueError):
            attempt_count = 0
        actionable = listing.evidence_type in {FIXED_ASK, AUCTION_SNAPSHOT_LE5}
        fair = hardening._LAST_FAIR.get(listing.identity.strict_key)
        known_discount = None
        if fair is not None and fair > 0 and listing.currency.upper() == "EUR" and listing.price > 0:
            known_discount = (float(fair) - float(listing.price)) / float(fair) * 100.0
        bucket = 0 if actionable and known_discount is not None else 1 if actionable else 2
        discount_sort = -(known_discount if known_discount is not None else -10_000.0)
        price_sort = float(listing.price) if listing.currency.upper() == "EUR" else 10**12
        ranked.append(((attempt_count, bucket, discount_sort, price_sort, index), key, listing))

    ranked.sort(key=lambda row: row[0])
    chosen = ranked[: max(0, int(limit))]
    for _priority, key, _listing in chosen:
        attempts[key] = max(0, int(attempts.get(key, 0))) + 1
    return [row[2] for row in chosen], [row[1] for row in chosen]


def install_marketplace_queue_hardening() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    marketplace.load_discovery_state = load_discovery_state_with_attempts
    marketplace.reconcile_inventory = reconcile_inventory_with_attempts
    marketplace.select_pending_listings = select_pending_fair_round_robin
    _INSTALLED = True
