from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Callable, Mapping, Optional, Protocol, Sequence, Tuple

try:
    import requests
except ModuleNotFoundError:  # Offline tests inject a session.
    requests = None  # type: ignore[assignment]

from ..models import CardIdentity
from ..poketrace_matching import (
    _candidate_evidence,
    _normalize,
    _normalize_card_name,
    _normalize_card_number,
)
from .models import MarketValues


POKETRACE_BASE_URL = "https://api.poketrace.com/v1"
POKETRACE_DISABLED = "POKETRACE_DISABLED"
POKETRACE_MATCHED = "POKETRACE_MATCHED"
POKETRACE_NO_MATCH = "POKETRACE_NO_MATCH"

CARDMARKET_DISCOUNT = "CARDMARKET_DISCOUNT"
CARDMARKET_FALLING_MARKET = "CARDMARKET_FALLING_MARKET"
CARDMARKET_NO_DISCOUNT = "CARDMARKET_NO_DISCOUNT"
CARDMARKET_INSUFFICIENT = "CARDMARKET_INSUFFICIENT"


class PokeTraceError(RuntimeError):
    pass


class HttpSession(Protocol):
    def get(self, url: str, **kwargs: object) -> object:
        ...


@dataclass(frozen=True)
class PokeTraceConfig:
    enabled: bool = False
    api_key: Optional[str] = field(default=None, repr=False)
    timeout_seconds: float = 15.0
    result_limit: int = 20
    minimum_request_interval_seconds: float = 0.35
    cardmarket_discount_threshold: Decimal = Decimal("0.20")
    falling_market_threshold: Decimal = Decimal("0.10")

    @classmethod
    def from_env(cls) -> "PokeTraceConfig":
        requested = (
            os.getenv("POKETRACE_ENABLED", "false").strip().casefold() == "true"
        )
        key = os.getenv("POKETRACE_API_KEY", "").strip() or None
        return cls(
            enabled=requested and key is not None,
            api_key=key,
            timeout_seconds=float(os.getenv("POKETRACE_TIMEOUT_SECONDS", "15")),
            result_limit=max(
                1, min(20, int(os.getenv("POKETRACE_RESULT_LIMIT", "20")))
            ),
            minimum_request_interval_seconds=float(
                os.getenv("POKETRACE_MIN_REQUEST_INTERVAL_SECONDS", "0.35")
            ),
            cardmarket_discount_threshold=Decimal(
                os.getenv("POKETRACE_CARDMARKET_DISCOUNT_THRESHOLD", "0.20")
            ),
            falling_market_threshold=Decimal(
                os.getenv("POKETRACE_FALLING_MARKET_THRESHOLD", "0.10")
            ),
        )


@dataclass
class PokeTraceCounters:
    live_calls: int = 0
    cache_hits: int = 0
    us_matches: int = 0
    eu_matches: int = 0
    no_match: int = 0
    ambiguous: int = 0
    request_failures: int = 0
    rate_limited: int = 0
    primed_market_calls_avoided: int = 0
    cardmarket_snapshots: int = 0
    cardmarket_discount_signals: int = 0
    cardmarket_falling_market_guards: int = 0


@dataclass(frozen=True)
class CardmarketOpportunity:
    status: str
    currency: str = "EUR"
    cardmarket_id: Optional[str] = None
    lowest_active_ask: Optional[Decimal] = None
    robust_reference: Optional[Decimal] = None
    discount_fraction: Optional[Decimal] = None
    trend_avg1d: Optional[Decimal] = None
    trend_avg7d: Optional[Decimal] = None
    trend_avg30d: Optional[Decimal] = None
    active_median7d: Optional[Decimal] = None
    active_median30d: Optional[Decimal] = None
    falling_market: bool = False


@dataclass(frozen=True)
class PokeTraceSnapshot:
    status: str
    us_values: Optional[MarketValues] = None
    cardmarket: Optional[CardmarketOpportunity] = None


class PokeTraceProvider:
    """PokeTrace Pro market-data provider for V5.

    The US side contributes sold/current market values to the existing V5
    aggregator. The EU side stays separate in EUR and is used as a CardMarket
    opportunity signal, so currencies are never mixed silently.

    CardMarket ``cardmarket_unsold`` data is aggregate active inventory, not a
    listing-level seller/URL feed. This provider therefore never claims that a
    specific CardMarket listing is directly actionable.
    """

    def __init__(
        self,
        config: Optional[PokeTraceConfig] = None,
        session: Optional[HttpSession] = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config or PokeTraceConfig.from_env()
        if session is not None:
            self.session = session
        elif requests is not None:
            self.session = requests.Session()
        else:
            raise PokeTraceError("Le client HTTP PokeTrace n'est pas installe")
        self.monotonic = monotonic
        self.sleeper = sleeper
        self._last_request_started: Optional[float] = None
        self.counters = PokeTraceCounters()
        self._cache: dict[Tuple[str, ...], PokeTraceSnapshot] = {}
        self._identity_primed_keys: set[Tuple[str, ...]] = set()

    def values_for(self, identity: CardIdentity) -> Optional[MarketValues]:
        return self.snapshot_for(identity).us_values

    def snapshot_for(self, identity: CardIdentity) -> PokeTraceSnapshot:
        if not self.config.enabled or not self.config.api_key:
            return PokeTraceSnapshot(POKETRACE_DISABLED)

        key = _identity_key(identity)
        cached = self._cached_snapshot(key)
        if cached is not None:
            return cached

        us = self._search_exact(identity, "US")
        eu = self._search_exact(identity, "EU")
        if us is None and eu is None:
            result = PokeTraceSnapshot(POKETRACE_NO_MATCH)
            self.counters.no_match += 1
            self._cache[key] = result
            return result

        us_values = _us_market_values(identity, us) if us is not None else None
        cardmarket = (
            _cardmarket_opportunity(eu, self.config) if eu is not None else None
        )
        if cardmarket is not None:
            self.counters.cardmarket_snapshots += 1
            if cardmarket.status == CARDMARKET_DISCOUNT:
                self.counters.cardmarket_discount_signals += 1
            if cardmarket.status == CARDMARKET_FALLING_MARKET:
                self.counters.cardmarket_falling_market_guards += 1

        result = PokeTraceSnapshot(
            POKETRACE_MATCHED
            if us_values is not None or cardmarket is not None
            else POKETRACE_NO_MATCH,
            us_values=us_values,
            cardmarket=cardmarket,
        )
        self._cache[key] = result
        return result

    def _search_exact(
        self, identity: CardIdentity, market: str
    ) -> Optional[Mapping[str, object]]:
        payload = self._request_cards(identity, market)
        if payload is None:
            return None
        raw_data = payload.get("data")
        if not isinstance(raw_data, Sequence) or isinstance(raw_data, (str, bytes)):
            return None
        candidates = tuple(item for item in raw_data if isinstance(item, Mapping))
        matches = tuple(
            item for item in candidates if _candidate_matches(identity, item)
        )
        if len(matches) > 1:
            self.counters.ambiguous += 1
            return None
        if not matches:
            return None
        if market == "US":
            self.counters.us_matches += 1
        else:
            self.counters.eu_matches += 1
        return matches[0]

    def _request_cards(
        self, identity: CardIdentity, market: str
    ) -> Optional[Mapping[str, object]]:
        self._respect_rate_limit()
        headers = {
            "Accept": "application/json",
            "X-API-Key": self.config.api_key or "",
        }
        params = {
            "search": _search_query(identity),
            "market": market,
            "limit": str(self.config.result_limit),
            "product_type": "single",
        }
        card_number = _normalize_card_number(identity.card_number)
        if card_number:
            params["card_number"] = card_number
        game = _poketrace_game(identity.language)
        if game:
            params["game"] = game
        try:
            self.counters.live_calls += 1
            response = self.session.get(
                f"{POKETRACE_BASE_URL}/cards",
                headers=headers,
                params=params,
                timeout=self.config.timeout_seconds,
            )
        except Exception:
            self.counters.request_failures += 1
            return None

        status = getattr(response, "status_code", None)
        if status == 429:
            self.counters.rate_limited += 1
            return None
        if status != 200:
            self.counters.request_failures += 1
            return None
        try:
            payload = response.json()
        except Exception:
            self.counters.request_failures += 1
            return None
        return payload if isinstance(payload, Mapping) else None

    def _respect_rate_limit(self) -> None:
        interval = max(0.0, self.config.minimum_request_interval_seconds)
        now = self.monotonic()
        if self._last_request_started is not None:
            elapsed = now - self._last_request_started
            remaining = interval - elapsed
            if remaining > 0:
                self.sleeper(remaining)
                now = self.monotonic()
        self._last_request_started = now

    def _cached_snapshot(
        self, key: Tuple[str, ...]
    ) -> Optional[PokeTraceSnapshot]:
        cached = self._cache.get(key)
        if cached is None:
            return None
        self.counters.cache_hits += 1
        if key in self._identity_primed_keys:
            self.counters.primed_market_calls_avoided += 1
            self._identity_primed_keys.discard(key)
        return cached

    def _prime_snapshot(
        self, key: Tuple[str, ...], snapshot: PokeTraceSnapshot
    ) -> None:
        self._cache[key] = snapshot
        self._identity_primed_keys.add(key)


def _identity_key(identity: CardIdentity) -> Tuple[str, ...]:
    return (
        _normalize_card_name(identity.card_name),
        _normalize(identity.set),
        _normalize_card_number(identity.card_number),
        _normalize(identity.language),
        _normalize(identity.variant),
    )


def _search_query(identity: CardIdentity) -> str:
    for value in (identity.card_name, identity.set, identity.card_number):
        if value and str(value).strip():
            return str(value).strip()
    return ""


def _candidate_matches(
    identity: CardIdentity, candidate: Mapping[str, object]
) -> bool:
    return _candidate_evidence(identity, candidate).rejection is None


def _poketrace_game(language: Optional[str]) -> Optional[str]:
    normalized = _normalize(language)
    if normalized in {"japanese", "japonais", "ja", "jp"}:
        return "pokemon-japanese"
    if normalized in {"chinese", "chinois", "zh", "zh cn", "zh tw"}:
        return "pokemon-chinese"
    if normalized in {"thai", "thailandais", "th"}:
        return "pokemon-thai"
    if normalized in {"indonesian", "indonesien", "id"}:
        return "pokemon-indonesian"
    if normalized:
        return "pokemon"
    return None


def _decimal(value: object) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result >= 0 else None


def _price_point(
    source: Mapping[str, object], tier: str
) -> Optional[Mapping[str, object]]:
    value = source.get(tier)
    return value if isinstance(value, Mapping) else None


def _preferred_market_value(point: Optional[Mapping[str, object]]) -> Optional[Decimal]:
    if point is None:
        return None
    for key in ("median7d", "median30d", "avg7d", "avg30d", "avg"):
        value = _decimal(point.get(key))
        if value is not None:
            return value
    return None


def _median_decimal(values: Sequence[Decimal]) -> Optional[Decimal]:
    if not values:
        return None
    return Decimal(str(median(values)))


def _us_market_values(
    identity: CardIdentity, card: Mapping[str, object]
) -> Optional[MarketValues]:
    prices = card.get("prices")
    if not isinstance(prices, Mapping):
        return None
    ebay = prices.get("ebay")
    tcgplayer = prices.get("tcgplayer")
    ebay = ebay if isinstance(ebay, Mapping) else {}
    tcgplayer = tcgplayer if isinstance(tcgplayer, Mapping) else {}

    raw_candidates = tuple(
        value
        for value in (
            _preferred_market_value(_price_point(ebay, "NEAR_MINT")),
            _preferred_market_value(_price_point(tcgplayer, "NEAR_MINT")),
        )
        if value is not None
    )
    ungraded = _median_decimal(raw_candidates)
    psa8 = _preferred_market_value(_price_point(ebay, "PSA_8"))
    psa9 = _preferred_market_value(_price_point(ebay, "PSA_9"))
    psa10 = _preferred_market_value(_price_point(ebay, "PSA_10"))
    if all(value is None for value in (ungraded, psa8, psa9, psa10)):
        return None

    currency = str(card.get("currency") or "USD").upper()
    if currency != "USD":
        return None
    card_id = str(card.get("id") or "").strip() or None
    freshness = str(card.get("lastUpdated") or "").strip() or None
    return MarketValues(
        source="PokeTrace US: eBay sold + TCGPlayer",
        currency="USD",
        ungraded_value=ungraded,
        grade8_generic_value=psa8,
        grade9_generic_value=psa9,
        psa10_value=psa10,
        matched_identity=identity,
        match_confidence=Decimal("1"),
        matched_product_id=card_id,
        fetched_at=datetime.now(timezone.utc),
        freshness=freshness,
        notes=(
            "Raw value uses the median of available eBay/TCGPlayer robust rolling values",
            "PSA_8/PSA_9/PSA_10 tiers come from PokeTrace eBay sold aggregates",
        ),
        limitations=(
            "eBay saleCount may be approximate",
            "PokeTrace aggregate prices are not listing-level evidence",
        ),
    )


def _cardmarket_opportunity(
    card: Mapping[str, object], config: PokeTraceConfig
) -> Optional[CardmarketOpportunity]:
    if str(card.get("currency") or "EUR").upper() != "EUR":
        return None
    prices = card.get("prices")
    if not isinstance(prices, Mapping):
        return None
    cardmarket = prices.get("cardmarket")
    unsold = prices.get("cardmarket_unsold")
    if not isinstance(cardmarket, Mapping) or not isinstance(unsold, Mapping):
        return CardmarketOpportunity(CARDMARKET_INSUFFICIENT)

    trend = _price_point(cardmarket, "AGGREGATED")
    active = _price_point(unsold, "NEAR_MINT")
    if trend is None or active is None:
        return CardmarketOpportunity(CARDMARKET_INSUFFICIENT)

    avg1d = _decimal(trend.get("avg1d"))
    avg7d = _decimal(trend.get("avg7d"))
    avg30d = _decimal(trend.get("avg30d"))
    current_trend = _decimal(trend.get("avg"))
    median7d = _decimal(active.get("median7d"))
    median30d = _decimal(active.get("median30d"))
    low = _decimal(active.get("low"))

    reference_values = tuple(
        value
        for value in (avg7d, avg30d, current_trend, median7d, median30d)
        if value is not None and value > 0
    )
    reference = _median_decimal(reference_values)
    refs = card.get("refs")
    cardmarket_id = None
    if isinstance(refs, Mapping) and refs.get("cardmarketId") is not None:
        cardmarket_id = str(refs.get("cardmarketId"))

    if low is None or reference is None or reference <= 0:
        return CardmarketOpportunity(
            CARDMARKET_INSUFFICIENT,
            cardmarket_id=cardmarket_id,
            lowest_active_ask=low,
            robust_reference=reference,
            trend_avg1d=avg1d,
            trend_avg7d=avg7d,
            trend_avg30d=avg30d,
            active_median7d=median7d,
            active_median30d=median30d,
        )

    discount = (reference - low) / reference
    falling = False
    if (
        avg1d is not None
        and avg7d is not None
        and avg30d is not None
        and avg30d > 0
        and avg1d < avg7d < avg30d
    ):
        falling = (avg30d - avg1d) / avg30d >= config.falling_market_threshold

    materially_below_current = (
        avg1d is None or avg1d <= 0 or low <= avg1d * Decimal("0.90")
    )
    if discount >= config.cardmarket_discount_threshold and materially_below_current:
        status = CARDMARKET_FALLING_MARKET if falling else CARDMARKET_DISCOUNT
    else:
        status = CARDMARKET_NO_DISCOUNT

    return CardmarketOpportunity(
        status,
        cardmarket_id=cardmarket_id,
        lowest_active_ask=low,
        robust_reference=reference,
        discount_fraction=discount,
        trend_avg1d=avg1d,
        trend_avg7d=avg7d,
        trend_avg30d=avg30d,
        active_median7d=median7d,
        active_median30d=median30d,
        falling_market=falling,
    )


def render_poketrace_counters(provider: PokeTraceProvider) -> str:
    counters = provider.counters
    return "\n".join(
        (
            "=== V5 POKETRACE / CARDMARKET MARKET DATA ===",
            f"enabled: {str(provider.config.enabled).lower()}",
            "role: primary market-data provider for V5 when enabled",
            "US sources: eBay sold + TCGPlayer",
            "EU sources: CardMarket Price Trend + active asking inventory",
            f"live calls: {counters.live_calls}",
            f"cache hits: {counters.cache_hits}",
            f"US exact matches: {counters.us_matches}",
            f"EU exact matches: {counters.eu_matches}",
            f"no match: {counters.no_match}",
            f"ambiguous: {counters.ambiguous}",
            f"request failures: {counters.request_failures}",
            f"rate limited: {counters.rate_limited}",
            f"extra market calls avoided by identity cache: {counters.primed_market_calls_avoided}",
            f"CardMarket snapshots: {counters.cardmarket_snapshots}",
            f"CardMarket discount signals: {counters.cardmarket_discount_signals}",
            (
                "CardMarket falling-market guards: "
                f"{counters.cardmarket_falling_market_guards}"
            ),
            "CardMarket listing-level seller/URL claims: 0",
            "Persisted PokeTrace/CardMarket records: 0",
        )
    )
