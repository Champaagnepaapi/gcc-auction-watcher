from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import japan_edge_hunter as japan
from v4_global_live_shadow import Seed, global_identity
from v4_global_market_core import (
    ACTIVE_AUCTION,
    AUCTION_SNAPSHOT_LE5,
    FIXED_ASK,
    CommercialIdentity,
    PriceObservation,
    all_in_eur,
)
from v4_market_cardova import parse_auction_payload, parse_fixed_payload


DISCOVERY_STATE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class MarketplaceListing:
    market: str
    source_id: str
    source_url: str
    title: str
    identity: CommercialIdentity
    evidence_type: str
    price: float
    currency: str
    observed_at: datetime
    identity_proven: bool
    buyer_fee_rate: Optional[float] = 0.0
    buyer_fee_flat: float = 0.0
    logistics_cost: float = 0.0
    end_at: Optional[datetime] = None
    note: str = ""

    @property
    def stable_key(self) -> str:
        locator = self.source_id or self.source_url
        return hashlib.sha256(f"{self.market}|{locator}".encode("utf-8")).hexdigest()

    @property
    def economic_signature(self) -> str:
        payload = {
            "identity": self.identity.strict_key,
            "evidence_type": self.evidence_type,
            "price": round(float(self.price), 8),
            "currency": self.currency.upper(),
            "buyer_fee_rate": self.buyer_fee_rate,
            "buyer_fee_flat": round(float(self.buyer_fee_flat), 8),
            "logistics_cost": round(float(self.logistics_cost), 8),
            "end_at": self.end_at.isoformat() if self.end_at is not None else "",
            "identity_proven": bool(self.identity_proven),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def observation(self) -> PriceObservation:
        return PriceObservation(
            source=self.market,
            identity=self.identity,
            evidence_type=self.evidence_type,
            price=self.price,
            currency=self.currency,
            observed_at=self.observed_at,
            identity_proven=self.identity_proven,
            end_at=self.end_at,
            buyer_fee_rate=self.buyer_fee_rate,
            buyer_fee_flat=self.buyer_fee_flat,
            logistics_cost=self.logistics_cost,
            note=self.note,
            source_id=self.source_id or self.source_url,
        )

    def all_in_eur(self, currency_per_eur: Mapping[str, float]) -> Optional[float]:
        return all_in_eur(self.observation(), currency_per_eur)


def empty_discovery_state() -> dict[str, Any]:
    return {
        "schema_version": DISCOVERY_STATE_SCHEMA_VERSION,
        "listings": {},
        "pending": [],
    }


def _valid_listing_state(row: object) -> bool:
    if not isinstance(row, Mapping):
        return False
    return all(
        isinstance(row.get(key), str)
        for key in ("market", "source_id", "source_url", "economic_signature", "first_seen", "last_seen")
    )


def _normalize_pending(value: object, listings: Mapping[str, object]) -> list[str]:
    if not isinstance(value, list):
        return []
    output: list[str] = []
    for raw in value:
        key = str(raw or "").strip()
        if key and key in listings and key not in output:
            output.append(key)
    return output


def load_discovery_state(path: Path, *, strict: bool) -> tuple[dict[str, Any], str]:
    if not path.exists():
        return empty_discovery_state(), "STATE_NEW"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        if strict:
            raise RuntimeError("GLOBAL_MARKETPLACE_DISCOVERY_STATE_INVALID") from error
        return empty_discovery_state(), "STATE_RESET_INVALID_JSON"
    valid = (
        isinstance(raw, Mapping)
        and raw.get("schema_version") == DISCOVERY_STATE_SCHEMA_VERSION
        and isinstance(raw.get("listings"), Mapping)
        and all(isinstance(key, str) and _valid_listing_state(row) for key, row in raw.get("listings", {}).items())
    )
    if not valid:
        if strict:
            raise RuntimeError("GLOBAL_MARKETPLACE_DISCOVERY_STATE_INVALID")
        return empty_discovery_state(), "STATE_RESET_INVALID_SCHEMA"
    listings = {str(key): dict(row) for key, row in raw["listings"].items()}
    state = {
        "schema_version": DISCOVERY_STATE_SCHEMA_VERSION,
        "listings": listings,
        "pending": _normalize_pending(raw.get("pending"), listings),
    }
    return state, "STATE_LOADED"


def save_discovery_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(dict(state), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _seen_row(listing: MarketplaceListing, *, first_seen: str, last_seen: str) -> dict[str, object]:
    return {
        "market": listing.market,
        "source_id": listing.source_id,
        "source_url": listing.source_url,
        "economic_signature": listing.economic_signature,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "last_identity_key": listing.identity.strict_key,
        "last_evidence_type": listing.evidence_type,
        "last_price": float(listing.price),
        "last_currency": listing.currency,
        "missing_since": "",
    }


def reconcile_inventory(
    state: Mapping[str, Any],
    listings: Sequence[MarketplaceListing],
    *,
    observed_at: datetime,
    complete_markets: Iterable[str] = (),
) -> tuple[dict[str, Any], dict[str, int]]:
    """Merge a read-only inventory snapshot into durable discovery state.

    Every listing seen during the first bootstrap is queued immediately, so the
    bootstrap itself already evaluates existing discounts. Later runs queue only
    genuinely new listings or economically meaningful changes. A listing that
    disappears is *never* converted into SOLD evidence.
    """

    now_text = observed_at.astimezone(timezone.utc).isoformat()
    old_listings = state.get("listings") if isinstance(state.get("listings"), Mapping) else {}
    output_listings = {str(key): dict(row) for key, row in old_listings.items() if isinstance(row, Mapping)}
    pending = _normalize_pending(state.get("pending"), output_listings)
    seen_keys: set[str] = set()
    counters = {
        "seen": 0,
        "new": 0,
        "changed": 0,
        "unchanged": 0,
        "missing_not_sold": 0,
        "pending_total": 0,
    }

    for listing in listings:
        key = listing.stable_key
        seen_keys.add(key)
        counters["seen"] += 1
        previous = output_listings.get(key)
        if not isinstance(previous, Mapping):
            output_listings[key] = _seen_row(listing, first_seen=now_text, last_seen=now_text)
            if key not in pending:
                pending.append(key)
            counters["new"] += 1
            continue
        first_seen = str(previous.get("first_seen") or now_text)
        changed = previous.get("economic_signature") != listing.economic_signature
        output_listings[key] = _seen_row(listing, first_seen=first_seen, last_seen=now_text)
        if changed:
            if key not in pending:
                pending.append(key)
            counters["changed"] += 1
        else:
            counters["unchanged"] += 1

    complete = {str(market).strip().casefold() for market in complete_markets if str(market).strip()}
    if complete:
        for key, row in output_listings.items():
            if key in seen_keys or not isinstance(row, Mapping):
                continue
            if str(row.get("market") or "").casefold() not in complete:
                continue
            updated = dict(row)
            if not str(updated.get("missing_since") or ""):
                updated["missing_since"] = now_text
                counters["missing_not_sold"] += 1
            output_listings[key] = updated

    output = {
        "schema_version": DISCOVERY_STATE_SCHEMA_VERSION,
        "listings": output_listings,
        "pending": [key for key in pending if key in output_listings],
    }
    counters["pending_total"] = len(output["pending"])
    return output, counters


def select_pending_listings(
    state: Mapping[str, Any],
    current: Mapping[str, MarketplaceListing],
    *,
    limit: int,
) -> tuple[list[MarketplaceListing], list[str]]:
    pending = state.get("pending") if isinstance(state.get("pending"), list) else []
    selected: list[MarketplaceListing] = []
    selected_keys: list[str] = []
    for raw in pending:
        key = str(raw or "")
        listing = current.get(key)
        if listing is None:
            continue
        selected.append(listing)
        selected_keys.append(key)
        if len(selected) >= max(0, int(limit)):
            break
    return selected, selected_keys


def acknowledge_evaluated(state: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    done = {str(key) for key in keys}
    output = dict(state)
    pending = state.get("pending") if isinstance(state.get("pending"), list) else []
    output["pending"] = [str(key) for key in pending if str(key) not in done]
    return output


def listing_from_observation(
    observation: PriceObservation,
    *,
    source_url: str = "",
    title: str = "",
) -> MarketplaceListing:
    return MarketplaceListing(
        market=observation.source,
        source_id=observation.source_id,
        source_url=source_url or observation.source_id,
        title=title,
        identity=observation.identity,
        evidence_type=observation.evidence_type,
        price=observation.price,
        currency=observation.currency,
        observed_at=observation.observed_at,
        identity_proven=observation.identity_proven,
        buyer_fee_rate=observation.buyer_fee_rate,
        buyer_fee_flat=observation.buyer_fee_flat,
        logistics_cost=observation.logistics_cost,
        end_at=observation.end_at,
        note=observation.note,
    )


def cardova_inventory(
    *,
    fixed_payload: Optional[Mapping[str, Any]],
    auction_payload: Optional[Mapping[str, Any]],
    observed_at: datetime,
    buyer_fee_rate: float = 0.0,
    auction_buyer_premium_rate: Optional[float] = None,
    logistics_jpy: float = 0.0,
) -> list[MarketplaceListing]:
    observations: list[PriceObservation] = []
    if fixed_payload is not None:
        observations.extend(
            parse_fixed_payload(
                fixed_payload,
                observed_at=observed_at,
                buyer_fee_rate=buyer_fee_rate,
                logistics_jpy=logistics_jpy,
            )
        )
    if auction_payload is not None:
        observations.extend(
            parse_auction_payload(
                auction_payload,
                observed_at=observed_at,
                buyer_premium_rate=auction_buyer_premium_rate,
                logistics_jpy=logistics_jpy,
            )
        )
    output = []
    for observation in observations:
        if not observation.identity_proven or not observation.identity.opportunity_language:
            continue
        output.append(listing_from_observation(observation, source_url=observation.source_id))
    return output


def _language(value: object) -> str:
    text = japan.norm(value)
    return {
        "english": "en",
        "anglais": "en",
        "japanese": "ja",
        "japonais": "ja",
    }.get(text, text)


def _grade(value: object) -> str:
    try:
        number = float(str(value or "").strip())
    except (TypeError, ValueError):
        return str(value or "").strip()
    return str(int(number)) if number.is_integer() else f"{number:g}"


def gcc_identity_from_row(row: Mapping[str, Any]) -> Optional[CommercialIdentity]:
    item = row.get("item")
    if not isinstance(item, Mapping):
        return None
    collectible = item.get("collectible")
    if not isinstance(collectible, Mapping):
        return None
    if japan.norm(collectible.get("category")) != "pokemon" or japan.norm(collectible.get("type")) != "cards":
        return None
    language = _language(collectible.get("language"))
    if language not in {"en", "ja"}:
        return None
    grader = str(item.get("gradingCompany") or "").strip().upper()
    grade = _grade(item.get("grade"))
    if grader != "PSA" or grade not in {"8", "8.5", "9", "10"}:
        return None
    character = collectible.get("character")
    name = ""
    if isinstance(character, Mapping):
        name = str(character.get("englishName") or character.get("name") or "").strip()
    set_name = str(collectible.get("set") or "").strip()
    number = japan.number(collectible.get("reference"))
    if not (name and set_name and number):
        return None
    finish = str(collectible.get("attribute") or "").strip()
    variant = " | ".join(
        value
        for value in (
            str(collectible.get("variety") or "").strip(),
            str(collectible.get("rarity") or "").strip(),
        )
        if value
    )
    return CommercialIdentity(
        name=name,
        set_name=set_name,
        number=number,
        language=language,
        grader=grader,
        grade=grade,
        edition=str(collectible.get("edition") or "").strip(),
        finish=finish,
        variant=variant,
    )


def _parse_time(value: object) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _positive_price(row: Mapping[str, Any]) -> Optional[float]:
    cents = row.get("priceInCents")
    if isinstance(cents, int) and not isinstance(cents, bool) and cents > 0:
        return cents / 100.0
    value = row.get("price")
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    return price if price > 0 else None


def gcc_listing_from_row(row: Mapping[str, Any], *, observed_at: datetime) -> Optional[MarketplaceListing]:
    identity = gcc_identity_from_row(row)
    if identity is None:
        return None
    status = str(row.get("status") or "").strip().upper()
    if status and status != "ON_SALE":
        return None
    price = _positive_price(row)
    if price is None:
        return None
    raw_type = str(row.get("sellingTypeGroup") or row.get("sellingType") or "").strip().upper()
    end_at = _parse_time(row.get("endTime") or row.get("endAt"))
    if "AUCTION" in raw_type:
        evidence_type = ACTIVE_AUCTION
        if end_at is not None:
            remaining = (end_at - observed_at.astimezone(timezone.utc)).total_seconds() / 60.0
            if 0 <= remaining <= 5.0:
                evidence_type = AUCTION_SNAPSHOT_LE5
    else:
        evidence_type = FIXED_ASK
    source_id = str(row.get("id") or "").strip()
    source_url = str(row.get("url") or "").strip()
    if not source_url and source_id:
        source_url = f"https://gradedcardcenter.com/item/{source_id}"
    item = row.get("item")
    title = ""
    if isinstance(item, Mapping):
        title = str(item.get("title") or "").strip()
    if not title:
        title = f"{identity.name} {identity.number} {identity.grader} {identity.grade}"
    return MarketplaceListing(
        market="gcc",
        source_id=source_id or source_url,
        source_url=source_url,
        title=title,
        identity=identity,
        evidence_type=evidence_type,
        price=price,
        currency="EUR",
        observed_at=observed_at,
        identity_proven=True,
        buyer_fee_rate=0.0,
        end_at=end_at,
        note="GCC live marketplace observation; ASK/current auction is not SOLD",
    )


def cards_from_listings(
    listings: Sequence[MarketplaceListing],
    *,
    currency_per_eur: Mapping[str, float],
    gcc_fair_by_identity: Mapping[str, float],
    observed_at: datetime,
) -> list[dict[str, object]]:
    grouped: dict[str, list[MarketplaceListing]] = {}
    for listing in listings:
        if not listing.identity_proven or not listing.identity.complete_for_exact_market:
            continue
        grouped.setdefault(listing.identity.strict_key, []).append(listing)
    cards: list[dict[str, object]] = []
    for key, rows in grouped.items():
        identity = rows[0].identity
        offers: list[dict[str, object]] = []
        for listing in rows:
            all_in = listing.all_in_eur(currency_per_eur)
            offers.append(
                {
                    "market": listing.market,
                    "evidence_type": listing.evidence_type,
                    "source_id": listing.source_id,
                    "source_url": listing.source_url,
                    "title": listing.title,
                    "currency": listing.currency,
                    "price": listing.price,
                    "all_in_eur": round(all_in, 2) if all_in is not None else None,
                    "note": listing.note,
                    "ask_is_sold": False,
                }
            )
        card: dict[str, object] = {
            "identity": asdict(identity),
            "offers": offers,
            "observed_at": observed_at.astimezone(timezone.utc).isoformat(),
        }
        gcc_fair = gcc_fair_by_identity.get(key)
        if gcc_fair is not None and gcc_fair > 0:
            card["fair_value_eur"] = round(float(gcc_fair), 2)
        cards.append(card)
    return cards
