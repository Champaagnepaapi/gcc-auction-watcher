from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence

import requests


POKETRACE_BASE = "https://api.poketrace.com/v1"
PPT_BASE = "https://www.pokemonpricetracker.com/api/v2"
SCHEMA_VERSION = 1
DEFAULT_PAID_UNTIL = "2026-09-12T00:00:00Z"
POKETRACE_LANES = (
    ("US", "pokemon"),
    ("US", "pokemon-japanese"),
    ("EU", "pokemon"),
    ("EU", "pokemon-japanese"),
)
POKETRACE_PRIORITIES = {"PSA_10": 0, "AGGREGATED": 0, "PSA_9": 1, "PSA_8": 2, "PSA_8_5": 3, "NEAR_MINT": 4}
PRICE_KEYS = {"avg", "low", "high", "price", "market", "marketprice", "medianprice", "averageprice", "median3d", "median7d", "median30d", "avg1d", "avg7d", "avg30d", "topprice"}


@dataclass(frozen=True)
class Metric:
    provider: str
    native_id: str
    name: str
    amount_minor: int
    currency: str
    observed_at: str
    event_at: Optional[str]
    precision: str
    sample_size: Optional[int]
    evidence_class: str
    card_id: str
    claims: tuple[tuple[str, str], ...]
    market: str = ""
    approximate_count: Optional[bool] = None


@dataclass
class Diagnostics:
    marketplace_seen: int = 0
    marketplace_stored: int = 0
    marketplace_unchanged: int = 0
    poketrace_http: int = 0
    poketrace_cards: int = 0
    poketrace_metrics: int = 0
    poketrace_history_pages: int = 0
    poketrace_remaining: Optional[int] = None
    ppt_http: int = 0
    ppt_sets: int = 0
    ppt_cards: int = 0
    ppt_metrics: int = 0
    ppt_remaining: Optional[int] = None
    source_failures: int = 0
    notes: list[str] | None = None

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []

    def payload(self) -> dict[str, Any]:
        value = asdict(self)
        value.update({
            "automatic_purchase": False,
            "automatic_bid": False,
            "automatic_checkout": False,
            "automatic_payment": False,
            "marketplace_ask_is_sold": False,
            "provider_aggregate_is_item_level_sold": False,
        })
        return value


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now().isoformat()


def parse_time(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    if len(candidate) == 10:
        candidate += "T00:00:00+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def minor(value: object) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not number.is_finite() or number < 0:
        return None
    return int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def nonnegative_int(value: object) -> Optional[int]:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def text(*values: object) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (Mapping, Sequence)):
            candidate = str(value).strip()
            if candidate:
                return candidate
    return ""


def mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def norm(value: object) -> str:
    return "".join(ch for ch in str(value or "").casefold() if ch.isalnum())


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part or "") for part in parts).encode()).hexdigest()


def fingerprint(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def evidence_class(source: str) -> str:
    key = source.strip().casefold()
    if key == "ebay":
        return "SOLD_AGGREGATED"
    if key == "cardmarket_unsold":
        return "FIXED_ASK_AGGREGATED"
    if key in {"cardmarket", "tcgplayer"}:
        return "MARKET_AGGREGATED"
    return "PROVIDER_AGGREGATED"


def currency(market: str, source: str) -> str:
    return "EUR" if market.upper() == "EU" or source.casefold().startswith("cardmarket") else "USD"


def claims(card: Mapping[str, Any], provider: str) -> tuple[tuple[str, str], ...]:
    set_data = mapping(card.get("set"))
    rows = (
        (f"{provider}_card_id", text(card.get("id"), card.get("cardId"))),
        ("external_catalog_id", text(card.get("externalCatalogId"))),
        ("tcgplayer_id", text(card.get("tcgPlayerId"), card.get("tcgplayerId"))),
        ("card_name", text(card.get("name"), card.get("cardName"))),
        ("collector_number", text(card.get("cardNumber"), card.get("number"), card.get("localId"))),
        ("set_id", text(card.get("setId"), card.get("set_id"), set_data.get("id"))),
        ("set", text(card.get("setName"), card.get("set_name"), set_data.get("name"))),
        ("language", text(card.get("language"), card.get("game"))),
        ("variant", text(card.get("variant"), card.get("printing"))),
        ("market", text(card.get("market"))),
    )
    return tuple((key, value) for key, value in rows if value)


def walk_prices(value: object, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], int]]:
    if not isinstance(value, Mapping):
        return
    for raw_key, child in value.items():
        key = str(raw_key)
        current = path + (key,)
        if isinstance(child, Mapping):
            yield from walk_prices(child, current)
        elif not isinstance(child, (str, bytes, Sequence)) and norm(key) in PRICE_KEYS:
            amount = minor(child)
            if amount is not None:
                yield current, amount
        elif isinstance(child, str) and norm(key) in PRICE_KEYS:
            amount = minor(child)
            if amount is not None:
                yield current, amount


def nested_context(root: Mapping[str, Any], path: tuple[str, ...]) -> Mapping[str, Any]:
    current: object = root
    for segment in path[:-1]:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(segment)
    return current if isinstance(current, Mapping) else {}


def poketrace_current_metrics(card: Mapping[str, Any], observed_at: str) -> list[Metric]:
    if norm(card.get("productType") or card.get("product_type")) not in {"", "single"}:
        return []
    card_id = text(card.get("id"), card.get("cardId"))
    prices = card.get("prices")
    if not card_id or not isinstance(prices, Mapping):
        return []
    card_market = text(card.get("market"))
    base_claims = claims(card, "poketrace")
    rows: list[Metric] = []
    for path, amount in walk_prices(prices):
        if len(path) < 2:
            continue
        source, tier = path[0], path[1]
        context = nested_context(prices, path)
        count = nonnegative_int(context.get("saleCount"))
        approximate = context.get("approxSaleCount") if isinstance(context.get("approxSaleCount"), bool) else None
        updated = text(context.get("updatedAt"), context.get("updated"), card.get("updatedAt"))
        event = parse_time(updated)
        rows.append(Metric(
            "poketrace",
            "pt_current_" + digest(card_market, card_id, *path, amount, count, updated),
            "POKETRACE_CURRENT:" + ":".join(part.upper() for part in path),
            amount,
            currency(card_market, source),
            observed_at,
            event.isoformat() if event else None,
            "EXACT" if event else "UNKNOWN",
            count,
            evidence_class(source),
            card_id,
            base_claims + (("market_tier", tier),),
            source,
            approximate,
        ))
    return rows


def poketrace_history_metrics(payload: Mapping[str, Any], card_id: str, tier: str, card_market: str, observed_at: str, base_claims: Sequence[tuple[str, str]] = ()) -> list[Metric]:
    data = payload.get("data")
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        return []
    output: list[Metric] = []
    for row in data:
        if not isinstance(row, Mapping):
            continue
        source = text(row.get("source")) or ("cardmarket" if card_market.upper() == "EU" else "ebay")
        date = text(row.get("date"), row.get("updatedAt"))
        event = parse_time(date)
        count = nonnegative_int(row.get("saleCount"))
        approximate = row.get("approxSaleCount") if isinstance(row.get("approxSaleCount"), bool) else None
        for path, amount in walk_prices(row):
            output.append(Metric(
                "poketrace",
                "pt_history_" + digest(card_market, card_id, tier, source, date, *path, amount, count),
                f"POKETRACE_HISTORY:{source.upper()}:{tier.upper()}:" + ":".join(part.upper() for part in path),
                amount,
                currency(card_market, source),
                observed_at,
                event.isoformat() if event else None,
                "DAY" if event and len(date) == 10 else ("EXACT" if event else "UNKNOWN"),
                count,
                evidence_class(source),
                card_id,
                tuple(base_claims) + (("market_tier", tier),),
                source,
                approximate,
            ))
    return output


def ppt_card_id(card: Mapping[str, Any]) -> str:
    return text(card.get("externalCatalogId"), card.get("tcgPlayerId"), card.get("tcgplayerId"), card.get("id"), card.get("cardId")) or digest(card.get("name"), card.get("setId"), card.get("cardNumber"))[:20]


def grade_claims(key: str) -> tuple[tuple[str, str], ...]:
    compact = key.strip().replace("_", ".")
    upper = compact.upper()
    for grader in ("PSA", "BGS", "CGC", "SGC", "ACE", "TAG"):
        if upper.startswith(grader):
            grade = compact[len(grader):].strip(" ._-")
            return (("grader", grader), ("grade", grade)) if grade else (("grader", grader),)
    return (("grade_bucket", key),) if key else ()


def ppt_card_metrics(card: Mapping[str, Any], observed_at: str) -> list[Metric]:
    card_id = ppt_card_id(card)
    base_claims = claims(card, "ppt")
    rows: list[Metric] = []

    def add_history(variant: str, condition: str, row: Mapping[str, Any]) -> None:
        amount = minor(row.get("price") if row.get("price") is not None else row.get("market"))
        if amount is None:
            return
        date = text(row.get("date"))
        event = parse_time(date)
        label = ":".join(part for part in (variant, condition) if part) or "GENERIC"
        extra = tuple(pair for pair in (("printing", variant), ("condition", condition)) if pair[1])
        rows.append(Metric("ppt", "ppt_history_" + digest(card_id, variant, condition, date, amount), f"PPT_HISTORY:RAW:{label.upper()}", amount, "USD", observed_at, event.isoformat() if event else None, "DAY" if event else "UNKNOWN", None, "MARKET_HISTORY_AGGREGATED", card_id, base_claims + extra, "tcgplayer"))

    history = mapping(card.get("priceHistory"))
    for condition, values in mapping(history.get("conditions")).items():
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
            for row in values:
                if isinstance(row, Mapping):
                    add_history("", str(condition), row)
    for variant, conditions in mapping(history.get("variants")).items():
        if not isinstance(conditions, Mapping):
            continue
        for condition, value in conditions.items():
            history_rows = value.get("history") if isinstance(value, Mapping) else value
            if isinstance(history_rows, Sequence) and not isinstance(history_rows, (str, bytes)):
                for row in history_rows:
                    if isinstance(row, Mapping):
                        add_history(str(variant), str(condition), row)

    for grade_key, raw_bucket in mapping(mapping(card.get("ebay")).get("salesByGrade")).items():
        if not isinstance(raw_bucket, Mapping):
            continue
        count = nonnegative_int(raw_bucket.get("count"))
        last_sale = text(raw_bucket.get("lastSaleDate"), raw_bucket.get("lastSaleAt"))
        event = parse_time(last_sale)
        candidates = {"MEDIAN": raw_bucket.get("medianPrice"), "AVERAGE": raw_bucket.get("averagePrice")}
        smart = mapping(raw_bucket.get("smartMarketPrice"))
        if smart:
            candidates["SMART_MARKET"] = smart.get("price")
        for label, value in candidates.items():
            amount = minor(value)
            if amount is None:
                continue
            rows.append(Metric("ppt", "ppt_ebay_" + digest(card_id, grade_key, label, amount, count, last_sale), f"PPT_EBAY_GRADED:{str(grade_key).upper()}:{label}", amount, "USD", observed_at, event.isoformat() if event else None, "EXACT" if event else "UNKNOWN", count, "SOLD_AGGREGATED", card_id, base_claims + grade_claims(str(grade_key)), "ebay"))

    for container_name, source, unit in (("cardmarket", "cardmarket", "EUR"), ("tcgplayer", "tcgplayer", "USD"), ("prices", "provider", "USD")):
        container = card.get(container_name)
        if not isinstance(container, Mapping):
            continue
        for path, amount in walk_prices(container):
            rows.append(Metric("ppt", "ppt_current_" + digest(card_id, container_name, *path, amount), f"PPT_CURRENT:{container_name.upper()}:" + ":".join(part.upper() for part in path), amount, unit, observed_at, None, "UNKNOWN", None, "MARKET_AGGREGATED", card_id, base_claims, source))
    return rows


def empty_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "marketplace_fingerprints": {},
        "poketrace": {
            "lanes": {f"{market}:{game}": {"market": market, "game": game, "cursor": "", "complete": False} for market, game in POKETRACE_LANES},
            "lane_index": 0,
            "catalog_cycle": 0,
            "cards": {},
            "history_tasks": {},
            "queues": {str(i): [] for i in range(10)},
            "positions": {str(i): 0 for i in range(10)},
        },
        "ppt": {"sets": {"english": [], "japanese": []}, "positions": {"english": 0, "japanese": 0}, "language_index": 0, "cycle": 0},
    }


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return empty_state()
    return dict(state) if isinstance(state, Mapping) and state.get("schema_version") == SCHEMA_VERSION else empty_state()


def save_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(dict(state), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def runtime():
    from robot_kb.domain import InclusionState, ObservationType, SourceKind
    from robot_kb.repository import KnowledgeBase, PriceComponent
    from robot_kb.sidecar.models import IdentityClaim, NormalizedObservation, RawSourceRecord, ShadowDiagnostics
    from robot_kb.sidecar.persistence import ShadowKnowledgePersistence
    return InclusionState, ObservationType, SourceKind, KnowledgeBase, PriceComponent, IdentityClaim, NormalizedObservation, RawSourceRecord, ShadowDiagnostics, ShadowKnowledgePersistence


def observation_exists(kb: Any, source: str, native: str, observation_type: str) -> bool:
    row = kb.connection.execute("""SELECT 1 FROM market_observation o JOIN source_system s ON s.id=o.source_system_id WHERE s.code=? AND o.source_native_record_id=? AND o.observation_type=? LIMIT 1""", (source, native, observation_type)).fetchone()
    return row is not None


def persist_metrics(kb: Any, metrics: Sequence[Metric], raw: Mapping[str, Any], raw_id: str, source: str, observed_at: str) -> int:
    _InclusionState, ObservationType, SourceKind, _KnowledgeBase, _PriceComponent, IdentityClaim, NormalizedObservation, RawSourceRecord, ShadowDiagnostics, ShadowKnowledgePersistence = runtime()
    source_name = "PokeTrace" if source == "poketrace" else "PokemonPriceTracker"
    observations = []
    for metric in metrics:
        if observation_exists(kb, source, metric.native_id, ObservationType.PROVIDER_METRIC_OBSERVATION.value):
            continue
        observations.append(NormalizedObservation(
            observation_type=ObservationType.PROVIDER_METRIC_OBSERVATION,
            source_native_record_id=metric.native_id,
            observed_at=metric.observed_at,
            source_updated_at=metric.event_at,
            event_at=metric.event_at,
            event_time_precision=metric.precision,
            fact={"metric_name": metric.name, "metric_value_minor": metric.amount_minor, "currency": metric.currency, "window_started_at": None, "window_ended_at": metric.event_at, "sample_size": metric.sample_size, "evidence_class": metric.evidence_class, "approximate_count": metric.approximate_count, "item_level_sold": False},
            upstream_market_code=metric.market or None,
            upstream_market_name=metric.market or None,
            identity_subject_type=f"{source.upper()}_MARKET_METRIC",
            identity_subject_label=f"{source_name} {metric.card_id} {metric.name}",
            identity_namespace=f"{source.upper()}_CARD_ID",
            identity_identifier_value=metric.card_id,
            unresolved_dimensions=("canonical_identity", "commercial_microvariant"),
            claims=tuple(IdentityClaim(key, value, SourceKind.PROVIDER) for key, value in metric.claims if value),
            exact_identity_eligible=False,
            genuine_sale_evidence=False,
        ))
    record = RawSourceRecord(source_code=source, source_name=source_name, source_role="PROVIDER", source_native_record_id=raw_id, payload=dict(raw), retrieved_at=observed_at, object_type="PROVIDER_RESPONSE", external_native_id=raw_id)
    ShadowKnowledgePersistence(kb).ingest(record, tuple(observations), ShadowDiagnostics())
    return len(observations)


def marketplace_payload(listing: Any) -> dict[str, Any]:
    identity = listing.identity
    return {"market": listing.market, "source_id": listing.source_id, "source_url": listing.source_url, "title": listing.title, "identity": {"name": identity.name, "set_name": identity.set_name, "number": identity.number, "language": identity.language, "grader": identity.grader, "grade": identity.grade, "edition": identity.edition, "finish": identity.finish, "variant": identity.variant}, "evidence_type": listing.evidence_type, "price": listing.price, "currency": listing.currency, "observed_at": listing.observed_at.isoformat(), "identity_proven": bool(listing.identity_proven), "end_at": listing.end_at.isoformat() if listing.end_at else None, "note": listing.note, "sale_evidence": False}


def persist_listing(kb: Any, listing: Any) -> None:
    InclusionState, ObservationType, SourceKind, _KnowledgeBase, PriceComponent, IdentityClaim, NormalizedObservation, RawSourceRecord, ShadowDiagnostics, ShadowKnowledgePersistence = runtime()
    payload = marketplace_payload(listing)
    identity = payload["identity"]
    native = str(listing.source_id or listing.source_url or listing.stable_key)
    amount = minor(listing.price)
    prices = () if amount is None else (PriceComponent("ITEM_PRICE", amount, str(listing.currency).upper(), inclusion_state=InclusionState.UNKNOWN),)
    claim_rows = tuple((key, str(value)) for key, value in (("card_name", identity["name"]), ("set", identity["set_name"]), ("collector_number", identity["number"]), ("language", identity["language"]), ("grader", identity["grader"]), ("grade", identity["grade"]), ("edition", identity["edition"]), ("finish", identity["finish"]), ("variant", identity["variant"]), ("listing_url", payload["source_url"]), ("evidence_type", payload["evidence_type"])) if value not in (None, ""))
    record = RawSourceRecord(source_code=str(listing.market).casefold(), source_name=str(listing.market), source_role="LISTING_PLATFORM", source_native_record_id=native, payload=payload, retrieved_at=listing.observed_at.isoformat(), object_type="LISTING", external_native_id=native)
    observation = NormalizedObservation(observation_type=ObservationType.LISTING_SNAPSHOT, source_native_record_id=native, observed_at=listing.observed_at.isoformat(), fact={"listing_started_at": None, "snapshot_status": str(listing.evidence_type), "quantity": 1, "provider_sale_evidence": False}, prices=prices, identity_subject_type="MARKETPLACE_LISTING_OBSERVATION", identity_subject_label=f"{listing.market} listing {native}", identity_namespace="COMMERCIAL_IDENTITY_STRICT_KEY", identity_identifier_value=listing.identity.strict_key, unresolved_dimensions=() if listing.identity_proven else ("commercial_identity",), claims=tuple(IdentityClaim(key, value, SourceKind.LISTING) for key, value in claim_rows), exact_identity_eligible=bool(listing.identity_proven), genuine_sale_evidence=False)
    ShadowKnowledgePersistence(kb).ingest(record, (observation,), ShadowDiagnostics())


def install_scan_stack() -> None:
    import v4_global_marketplace_notify_resilient as r
    r.install_marketplace_first_hardening(); r.install_global_marketplace_fanatics_language_proof(); r.install_global_marketplace_unicode_identity(); r.install_global_marketplace_magi_native_identity(); r.install_global_marketplace_magi_detail_coordinate(); r.install_global_marketplace_magi_detail_retry(); r.install_global_marketplace_magi_promo_source_proof(); r.install_global_marketplace_magi_standard_source_proof(); r.install_global_marketplace_magi_set_code_proof(); r.install_global_marketplace_magi_japanese_native_identity(); r.install_global_marketplace_magi_recovery_budget(); r.install_global_marketplace_magi_unique_full_number(); r.install_global_marketplace_magi_unique_name_among_full_number(); r.install_global_marketplace_magi_set_name_unique_card(); r.install_global_marketplace_magi_set_name_rarity_unique_card(); r.install_global_marketplace_magi_rumble_source_proof(); r.install_global_marketplace_magi_sensitive_variant_source_proof(); r.install_global_cardova_public_inventory(); r.install_global_marketplace_identity_dimension_hardening()


def harvest_markets(kb: Any, state: dict[str, Any], diag: Diagnostics) -> None:
    import argparse as ap
    import v4_global_marketplace_notify as marketplace
    install_scan_stack()
    args = ap.Namespace(gcc_sold_pages=int(os.getenv("ROBOT_KB_MARKET_GCC_SOLD_PAGES", "80")), gcc_live_pages=int(os.getenv("ROBOT_KB_MARKET_GCC_LIVE_PAGES", "100")), cardova_fixed_json="", cardova_auction_json="", no_browser_sources=False, browser_detail_cap=int(os.getenv("ROBOT_KB_MARKET_BROWSER_DETAIL_CAP", "300")), browser_scroll_rounds=int(os.getenv("ROBOT_KB_MARKET_BROWSER_SCROLL_ROUNDS", "30")), comc_pages=int(os.getenv("ROBOT_KB_MARKET_COMC_PAGES", "30")))
    listings, statuses, _fair, catalog = marketplace._scan(args, observed_at=now())
    diag.notes.append(f"catalog={catalog}")
    diag.notes.extend(f"{row.market}:{row.status}:{row.exact}/{row.candidates}:complete={row.complete}" for row in statuses)
    fingerprints = state["marketplace_fingerprints"]
    for listing in listings:
        diag.marketplace_seen += 1
        if str(listing.market).casefold() == "gcc":
            continue
        payload = marketplace_payload(listing)
        current = fingerprint(payload)
        if fingerprints.get(listing.stable_key) == current:
            diag.marketplace_unchanged += 1
            continue
        persist_listing(kb, listing)
        fingerprints[listing.stable_key] = current
        diag.marketplace_stored += 1


def header_int(headers: Mapping[str, Any], name: str) -> Optional[int]:
    for key, value in headers.items():
        if str(key).casefold() == name.casefold():
            try:
                return int(str(value).strip())
            except ValueError:
                return None
    return None


def response_rows(payload: object) -> list[Mapping[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return [row for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Sequence) and not isinstance(data, (str, bytes)):
            return [row for row in data if isinstance(row, Mapping)]
        if isinstance(data, Mapping):
            return [data]
    return []


def request_json(session: requests.Session, url: str, headers: Mapping[str, str], params: Mapping[str, Any], timeout: float, diag: Diagnostics, provider: str) -> tuple[int, object, Mapping[str, Any]]:
    try:
        response = session.get(url, headers=dict(headers), params=dict(params), timeout=timeout)
    except requests.RequestException as error:
        diag.source_failures += 1; diag.notes.append(f"{provider}:request-error:{type(error).__name__}"); return 0, {}, {}
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    return int(response.status_code), payload, response.headers


def available_tiers(card: Mapping[str, Any]) -> list[str]:
    prices = mapping(card.get("prices")); card_market = text(card.get("market")).upper(); found: set[str] = set()
    for source in (("cardmarket", "cardmarket_unsold") if card_market == "EU" else ("ebay", "tcgplayer")):
        data = prices.get(source)
        if isinstance(data, Mapping):
            found.update(str(key).upper() for key in data)
    return [tier for tier in POKETRACE_PRIORITIES if tier in found]


def enqueue_history(state: dict[str, Any], card: Mapping[str, Any]) -> None:
    pt = state["poketrace"]; card_id = text(card.get("id"), card.get("cardId")); card_market = text(card.get("market")) or "US"
    if not card_id: return
    card_key = f"{card_market.upper()}|{card_id}"; pt["cards"][card_key] = {"market": card_market, "claims": list(claims(card, "poketrace"))}
    for tier in available_tiers(card):
        key = f"{card_market.upper()}|{card_id}|{tier}"
        if key in pt["history_tasks"]: continue
        priority = POKETRACE_PRIORITIES[tier]; pt["history_tasks"][key] = {"card_id": card_id, "tier": tier, "market": card_market, "cursor": "", "status": "PENDING", "priority": priority}; pt["queues"][str(priority)].append(key)


def next_task(state: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    pt = state["poketrace"]
    for priority in range(10):
        queue = pt["queues"][str(priority)]; pos = int(pt["positions"].get(str(priority), 0))
        while pos < len(queue):
            key = queue[pos]; pt["positions"][str(priority)] = pos + 1; task = pt["history_tasks"].get(key)
            if isinstance(task, Mapping) and task.get("status") == "PENDING": return key, dict(task)
            pos += 1
    return None


def pending_task(state: dict[str, Any]) -> bool:
    return any(isinstance(task, Mapping) and task.get("status") == "PENDING" for task in state["poketrace"]["history_tasks"].values())


def requeue(state: dict[str, Any], key: str, task: Mapping[str, Any], cursor: str) -> None:
    updated = dict(task); updated.update({"cursor": cursor, "status": "PENDING", "priority": 9}); state["poketrace"]["history_tasks"][key] = updated; state["poketrace"]["queues"]["9"].append(key)


def complete_task(state: dict[str, Any], key: str, task: Mapping[str, Any]) -> None:
    updated = dict(task); updated.update({"cursor": "", "status": "DONE", "completed_at": iso_now()}); state["poketrace"]["history_tasks"][key] = updated


def next_lane(state: dict[str, Any]) -> Optional[tuple[str, dict[str, Any]]]:
    pt = state["poketrace"]; keys = list(pt["lanes"]); start = int(pt.get("lane_index", 0)) % len(keys)
    for offset in range(len(keys)):
        index = (start + offset) % len(keys); key = keys[index]; lane = pt["lanes"][key]
        if not lane.get("complete"): pt["lane_index"] = (index + 1) % len(keys); return key, lane
    return None


def reset_pt_cycle(state: dict[str, Any]) -> None:
    pt = state["poketrace"]
    for lane in pt["lanes"].values(): lane.update({"cursor": "", "complete": False}); lane.pop("completed_at", None)
    pt["lane_index"] = 0; pt["catalog_cycle"] = int(pt.get("catalog_cycle", 0)) + 1


def harvest_poketrace(kb: Any, state: dict[str, Any], key: str, diag: Diagnostics, deadline: float) -> None:
    reserve = int(os.getenv("ROBOT_KB_POKETRACE_REMAINING_RESERVE", "1500")); max_calls = int(os.getenv("ROBOT_KB_POKETRACE_MAX_CALLS_PER_PAID_RUN", "6000")); pacing = float(os.getenv("ROBOT_KB_POKETRACE_PACING_SECONDS", "0.42")); session = requests.Session(); catalog_streak = 0
    try:
        while diag.poketrace_http < max_calls and time.monotonic() < deadline:
            if diag.poketrace_remaining is not None and diag.poketrace_remaining <= reserve: diag.notes.append("poketrace:daily-reserve-reached"); break
            lane_info = next_lane(state); use_catalog = lane_info is not None and (catalog_streak < 3 or not pending_task(state))
            time.sleep(pacing)
            if use_catalog and lane_info:
                lane_key, lane = lane_info; params = {"market": lane["market"], "game": lane["game"], "product_type": "single", "limit": 20};
                if lane.get("cursor"): params["cursor"] = lane["cursor"]
                status, payload, headers = request_json(session, f"{POKETRACE_BASE}/cards", {"X-API-Key": key, "Accept": "application/json"}, params, 20, diag, "poketrace"); diag.poketrace_http += 1; diag.poketrace_remaining = header_int(headers, "X-RateLimit-Remaining")
                if status in {401, 403, 429}: diag.notes.append(f"poketrace:catalog-http-{status}"); break
                if status != 200 or not isinstance(payload, Mapping): diag.source_failures += 1; diag.notes.append(f"poketrace:catalog-http-{status}"); break
                observed = iso_now()
                for card in response_rows(payload):
                    if norm(card.get("productType") or card.get("product_type")) not in {"", "single"}: continue
                    card_id = text(card.get("id"), card.get("cardId"));
                    if not card_id: continue
                    metrics = poketrace_current_metrics(card, observed); diag.poketrace_metrics += persist_metrics(kb, metrics, card, f"poketrace-card:{text(card.get('market')) or lane['market']}:{card_id}", "poketrace", observed); diag.poketrace_cards += 1; enqueue_history(state, card)
                pagination = mapping(payload.get("pagination")); next_cursor = text(pagination.get("nextCursor"))
                if pagination.get("hasMore") and next_cursor: lane["cursor"] = next_cursor
                else: lane.update({"cursor": "", "complete": True, "completed_at": iso_now()})
                state["poketrace"]["lanes"][lane_key] = lane; catalog_streak += 1; continue
            task_info = next_task(state)
            if not task_info:
                if lane_info is None: reset_pt_cycle(state); diag.notes.append(f"poketrace:cycle-{state['poketrace']['catalog_cycle']}-complete"); catalog_streak = 0; continue
                catalog_streak = 0; continue
            task_key, task = task_info; params = {"period": "all", "limit": 365};
            if task.get("cursor"): params["cursor"] = task["cursor"]
            status, payload, headers = request_json(session, f"{POKETRACE_BASE}/cards/{task['card_id']}/prices/{task['tier']}/history", {"X-API-Key": key, "Accept": "application/json"}, params, 25, diag, "poketrace"); diag.poketrace_http += 1; diag.poketrace_remaining = header_int(headers, "X-RateLimit-Remaining")
            if status in {401, 403, 429}: requeue(state, task_key, task, text(task.get("cursor"))); diag.notes.append(f"poketrace:history-http-{status}"); break
            if status == 404: complete_task(state, task_key, task); catalog_streak = 0; continue
            if status != 200 or not isinstance(payload, Mapping): requeue(state, task_key, task, text(task.get("cursor"))); diag.source_failures += 1; break
            meta = state["poketrace"]["cards"].get(f"{str(task['market']).upper()}|{task['card_id']}", {}); base_claims = tuple(tuple(pair) for pair in meta.get("claims", []) if isinstance(pair, list) and len(pair) == 2); observed = iso_now(); metrics = poketrace_history_metrics(payload, task["card_id"], task["tier"], task["market"], observed, base_claims); raw_cursor = text(task.get("cursor")) or "first"; diag.poketrace_metrics += persist_metrics(kb, metrics, payload, f"poketrace-history:{task['market']}:{task['card_id']}:{task['tier']}:{raw_cursor}", "poketrace", observed); diag.poketrace_history_pages += 1
            pagination = mapping(payload.get("pagination")); next_cursor = text(pagination.get("nextCursor")); requeue(state, task_key, task, next_cursor) if pagination.get("hasMore") and next_cursor else complete_task(state, task_key, task); catalog_streak = 0
    finally: session.close()


def ppt_get(session: requests.Session, key: str, endpoint: str, params: Mapping[str, Any], diag: Diagnostics) -> tuple[int, object, Mapping[str, Any]]:
    time.sleep(float(os.getenv("ROBOT_KB_PPT_PACING_SECONDS", "1.05"))); status, payload, headers = request_json(session, f"{PPT_BASE}/{endpoint.lstrip('/')}", {"Authorization": f"Bearer {key}", "Accept": "application/json"}, params, 30, diag, "ppt"); diag.ppt_http += 1; diag.ppt_remaining = header_int(headers, "X-Ratelimit-Daily-Remaining"); return status, payload, headers


def refresh_ppt_sets(state: dict[str, Any], session: requests.Session, key: str, diag: Diagnostics) -> bool:
    for language in ("english", "japanese"):
        status, payload, _ = ppt_get(session, key, "sets", {"language": language}, diag)
        if status != 200: diag.notes.append(f"ppt:sets-{language}-http-{status}"); diag.source_failures += int(status not in {401, 403, 429}); return False
        rows = []
        for row in response_rows(payload):
            set_id = text(row.get("id"), row.get("setId"), row.get("set_id"));
            if set_id: rows.append({"id": set_id, "name": text(row.get("name"), row.get("setName"))})
        if not rows: diag.source_failures += 1; return False
        state["ppt"]["sets"][language] = rows; state["ppt"]["positions"][language] = 0
    state["ppt"]["language_index"] = 0; return True


def next_ppt_set(state: dict[str, Any]) -> Optional[tuple[str, Mapping[str, str]]]:
    ppt = state["ppt"]; languages = ("english", "japanese")
    for _ in range(2):
        language = languages[int(ppt.get("language_index", 0)) % 2]; rows = ppt["sets"][language]; pos = int(ppt["positions"][language]); ppt["language_index"] = (languages.index(language) + 1) % 2
        if pos < len(rows): ppt["positions"][language] = pos + 1; return language, rows[pos]
    return None


def harvest_ppt(kb: Any, state: dict[str, Any], key: str, diag: Diagnostics, deadline: float) -> None:
    reserve = int(os.getenv("ROBOT_KB_PPT_REMAINING_RESERVE", "2500")); margin = int(os.getenv("ROBOT_KB_PPT_PREFLIGHT_MARGIN", "1000")); max_sets = int(os.getenv("ROBOT_KB_PPT_MAX_SETS_PER_PAID_RUN", "500")); session = requests.Session()
    try:
        if not refresh_ppt_sets(state, session, key, diag): return
        while diag.ppt_sets < max_sets and time.monotonic() < deadline:
            if diag.ppt_remaining is not None and diag.ppt_remaining <= reserve + margin: diag.notes.append("ppt:daily-reserve-margin-reached"); break
            item = next_ppt_set(state)
            if not item: state["ppt"]["cycle"] = int(state["ppt"].get("cycle", 0)) + 1; break
            language, set_row = item; params = {"setId": set_row["id"], "fetchAllInSet": "true", "includeHistory": "true", "days": 180, "maxDataPoints": 180, "includeEbay": "true", "includeCardmarket": "true", "limit": 200, "language": language}; status, payload, headers = ppt_get(session, key, "cards", params, diag)
            if status in {401, 403, 429}: diag.notes.append(f"ppt:cards-http-{status}"); break
            if status != 200: diag.source_failures += 1; continue
            if diag.ppt_remaining is None: diag.notes.append("ppt:missing-daily-remaining-header-stop"); break
            observed = iso_now()
            for card in response_rows(payload):
                product_type = norm(card.get("productType") or card.get("product_type"));
                if product_type and product_type not in {"single", "card", "singlecard", "tradingcard"}: continue
                card_id = ppt_card_id(card); metrics = ppt_card_metrics(card, observed); diag.ppt_metrics += persist_metrics(kb, metrics, card, f"ppt-card:{language}:{set_row['id']}:{card_id}", "ppt", observed); diag.ppt_cards += 1
            diag.ppt_sets += 1; consumed = header_int(headers, "X-Api-Calls-Consumed");
            if consumed is not None: diag.notes.append(f"ppt:set={set_row['id']}:credits={consumed}")
    finally: session.close()


def paid_open() -> bool:
    cutoff = parse_time(os.getenv("ROBOT_KB_PAID_HARVEST_UNTIL", DEFAULT_PAID_UNTIL)); return cutoff is None or now() < cutoff


def run_paid(kb: Any, state: dict[str, Any], diag: Diagnostics) -> None:
    if not paid_open(): diag.notes.append("paid:configured-access-window-ended"); return
    deadline = time.monotonic() + max(60, int(os.getenv("ROBOT_KB_PAID_MAX_RUNTIME_SECONDS", "5100"))); ppt_key = os.getenv("POKEMON_PRICE_TRACKER_API_KEY", "").strip(); pt_key = os.getenv("POKETRACE_API_KEY", "").strip()
    if ppt_key: harvest_ppt(kb, state, ppt_key, diag, deadline)
    else: diag.notes.append("ppt:key-not-configured")
    if pt_key and time.monotonic() < deadline: harvest_poketrace(kb, state, pt_key, diag, deadline)
    elif not pt_key: diag.notes.append("poketrace:key-not-configured")


def run(mode: str, state_path: Path) -> dict[str, Any]:
    _a, _b, _c, KnowledgeBase, _d, _e, _f, _g, _h, _i = runtime(); database = os.getenv("ROBOT_KB_DATABASE_URL", "").strip()
    if not database: raise RuntimeError("ROBOT_KB_DATABASE_URL is required")
    state = load_state(state_path); diag = Diagnostics()
    with KnowledgeBase.open(database) as kb:
        if mode in {"markets", "all"}: harvest_markets(kb, state, diag); save_state(state_path, state)
        if mode in {"paid", "all"}: run_paid(kb, state, diag); save_state(state_path, state)
    return diag.payload()


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only multi-source Robot KB harvester"); parser.add_argument("mode", choices=("markets", "paid", "all")); parser.add_argument("--state", required=True); args = parser.parse_args(argv); result = run(args.mode, Path(args.state)); print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 1 if result.get("source_failures") else 0


if __name__ == "__main__":
    raise SystemExit(main())
