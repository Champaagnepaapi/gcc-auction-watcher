from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from statistics import median
from typing import Callable, Mapping, Optional, Protocol, Sequence, Tuple

try:
    import requests
except ModuleNotFoundError:  # Offline tests inject a session.
    requests = None  # type: ignore[assignment]

from ..models import (
    POKETRACE_PROVIDER,
    TCGDEX_EXACT_ENGLISH_TWIN,
    CardIdentity,
    ProviderSearchAlias,
)
from ..poketrace_matching import (
    _candidate_evidence,
    _normalize,
    _normalize_card_name,
    _normalize_card_number,
)
from ..poketrace_set_bridge import (
    SET_BRIDGE_AMBIGUOUS,
    SET_BRIDGE_COLLISION,
    DeterministicSetBridgeRegistry,
    PokeTraceSetCollisionIndex,
    SetBridgeDecision,
    TCGdexSetProvenance,
    collision_index,
)
from .models import MarketValues


POKETRACE_BASE_URL = "https://api.poketrace.com/v1"
POKETRACE_DISABLED = "POKETRACE_DISABLED"
POKETRACE_MATCHED = "POKETRACE_MATCHED"
POKETRACE_NO_MATCH = "POKETRACE_NO_MATCH"
POKETRACE_RATE_LIMITED = "POKETRACE_RATE_LIMITED"

MARKET_SEARCH_MATCHED = "MATCHED"
MARKET_SEARCH_CLEAN_NO_MATCH = "CLEAN_NO_MATCH"
MARKET_SEARCH_AMBIGUOUS = "AMBIGUOUS"
MARKET_SEARCH_ERROR = "ERROR"
MARKET_SEARCH_RATE_LIMITED = "RATE_LIMITED"

PRO_MIN_REQUEST_INTERVAL_SECONDS = 0.40

RATE_LIMIT_SHORT_RETRYABLE = "SHORT_RETRYABLE"
RATE_LIMIT_LONG_NON_RETRYABLE = "LONG_NON_RETRYABLE"
RATE_LIMIT_UNCLASSIFIED = "UNCLASSIFIED"

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
    max_retry_after_seconds: float = 30.0
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
            max_retry_after_seconds=max(
                0.0,
                float(os.getenv("POKETRACE_MAX_RETRY_AFTER_SECONDS", "30")),
            ),
            cardmarket_discount_threshold=Decimal(
                os.getenv("POKETRACE_CARDMARKET_DISCOUNT_THRESHOLD", "0.20")
            ),
            falling_market_threshold=Decimal(
                os.getenv("POKETRACE_FALLING_MARKET_THRESHOLD", "0.10")
            ),
        )


def pro_tier_config_from_env() -> PokeTraceConfig:
    """Build the generic Pro config with margin below the 30/10s burst."""

    config = PokeTraceConfig.from_env()
    return replace(
        config,
        minimum_request_interval_seconds=max(
            config.minimum_request_interval_seconds,
            PRO_MIN_REQUEST_INTERVAL_SECONDS,
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
    retryable_429: int = 0
    long_429: int = 0
    unclassified_429: int = 0
    terminal_429_detected: int = 0
    rate_limit_retry_attempts: int = 0
    circuit_breaker_opened: int = 0
    calls_avoided_after_breaker: int = 0
    primed_market_calls_avoided: int = 0
    cardmarket_snapshots: int = 0
    cardmarket_discount_signals: int = 0
    cardmarket_falling_market_guards: int = 0
    provider_alias_market_searches: int = 0
    alias_market_matches: int = 0
    provider_alias_market_searches_us: int = 0
    provider_alias_market_searches_eu: int = 0
    alias_market_matches_us: int = 0
    alias_market_matches_eu: int = 0
    us_clean_no_matches: int = 0
    eu_clean_no_matches: int = 0
    us_raw_available: int = 0
    us_psa8_available: int = 0
    us_psa9_available: int = 0
    us_psa10_available: int = 0
    eu_cardmarket_aggregated_available: int = 0
    eu_active_ask_available: int = 0
    market_record_cache_hits: int = 0
    market_mismatch_rejections: int = 0
    candidates_name_number_bridged_set: int = 0
    candidates_all_three_before_bridge: int = 0
    candidates_all_three_after_bridge: int = 0
    candidates_all_three_variant_compatible_after_bridge: int = 0


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
    us_record_id: Optional[str] = None
    eu_record_id: Optional[str] = None


@dataclass(frozen=True)
class PokeTraceMarketSearchResult:
    market: str
    status: str
    card: Optional[Mapping[str, object]] = None


@dataclass(frozen=True)
class PokeTraceRateLimitDecision:
    classification: str
    retry_after_seconds: Optional[float] = None

    @property
    def retryable(self) -> bool:
        return self.classification == RATE_LIMIT_SHORT_RETRYABLE


def classify_poketrace_429(
    response: object,
    *,
    max_retry_after_seconds: float,
    now: Optional[datetime] = None,
) -> PokeTraceRateLimitDecision:
    """Classify a 429 from Retry-After only, without reading provider data."""

    headers = getattr(response, "headers", None)
    raw_retry_after = None
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if str(key).casefold() == "retry-after":
                raw_retry_after = value
                break
    if raw_retry_after is None:
        return PokeTraceRateLimitDecision(RATE_LIMIT_UNCLASSIFIED)

    raw_text = str(raw_retry_after).strip()
    try:
        seconds = float(raw_text)
        if not math.isfinite(seconds):
            raise ValueError
        seconds = max(0.0, seconds)
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(raw_text)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            seconds = max(0.0, (retry_at - reference).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return PokeTraceRateLimitDecision(RATE_LIMIT_UNCLASSIFIED)

    classification = (
        RATE_LIMIT_SHORT_RETRYABLE
        if seconds <= max(0.0, max_retry_after_seconds)
        else RATE_LIMIT_LONG_NON_RETRYABLE
    )
    return PokeTraceRateLimitDecision(classification, seconds)


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
        self._market_cache: dict[
            Tuple[str, ...], PokeTraceMarketSearchResult
        ] = {}
        self._identity_primed_market_keys: set[Tuple[str, ...]] = set()
        self._search_aliases: dict[Tuple[str, ...], ProviderSearchAlias] = {}
        self.set_bridge_registry = DeterministicSetBridgeRegistry()
        self._circuit_open = False

    @property
    def circuit_open(self) -> bool:
        return self._circuit_open

    @property
    def supports_eu_market(self) -> bool:
        return True

    def _record_call_avoided_after_breaker(self) -> None:
        self.counters.calls_avoided_after_breaker += 1

    def _record_rate_limit(
        self,
        response: object,
        *,
        retry_exhausted: bool = False,
    ) -> PokeTraceRateLimitDecision:
        decision = classify_poketrace_429(
            response,
            max_retry_after_seconds=self.config.max_retry_after_seconds,
        )
        self.counters.rate_limited += 1
        if decision.classification == RATE_LIMIT_SHORT_RETRYABLE:
            self.counters.retryable_429 += 1
        elif decision.classification == RATE_LIMIT_LONG_NON_RETRYABLE:
            self.counters.long_429 += 1
        else:
            self.counters.unclassified_429 += 1

        terminal = retry_exhausted or not decision.retryable
        if terminal:
            self.counters.terminal_429_detected += 1
            if not self._circuit_open:
                self._circuit_open = True
                self.counters.circuit_breaker_opened += 1
        return decision

    def _rate_limit_wait_seconds(
        self, decision: PokeTraceRateLimitDecision
    ) -> float:
        retry_after = decision.retry_after_seconds or 0.0
        return max(
            self.config.minimum_request_interval_seconds,
            retry_after + 0.25,
        )

    def values_for(self, identity: CardIdentity) -> Optional[MarketValues]:
        return self.snapshot_for(identity).us_values

    def register_search_alias(
        self, identity: CardIdentity, alias: ProviderSearchAlias
    ) -> bool:
        """Register one exact, provider-only alias for this full identity key."""

        if not (
            alias.provider == POKETRACE_PROVIDER
            and alias.provenance == TCGDEX_EXACT_ENGLISH_TWIN
            and alias.search_card_name.strip()
            and alias.search_set_name.strip()
            and alias.catalog_card_id.strip()
            and alias.catalog_set_id.strip()
            and alias.catalog_local_id.strip()
        ):
            return False
        key = _identity_key(identity)
        previous = self._search_aliases.get(key)
        if previous is not None and previous != alias:
            return False
        self._search_aliases[key] = alias
        return True

    def register_set_provenance(
        self, identity: CardIdentity, provenance: TCGdexSetProvenance
    ) -> bool:
        """Attach exact TCGdex set coordinates without changing the identity."""

        return self.set_bridge_registry.register(_identity_key(identity), provenance)

    def has_set_provenance(self, identity: CardIdentity) -> bool:
        return (
            self.set_bridge_registry.provenance_for(_identity_key(identity))
            is not None
        )

    def evaluate_set_bridge(
        self,
        identity: CardIdentity,
        candidate: Mapping[str, object],
        *,
        provider_alias: Optional[ProviderSearchAlias],
        core_identity_exact: bool,
        collisions: PokeTraceSetCollisionIndex,
    ) -> SetBridgeDecision:
        return self.set_bridge_registry.evaluate(
            _identity_key(identity),
            candidate,
            provider_alias=provider_alias,
            core_identity_exact=core_identity_exact,
            collisions=collisions,
        )

    def search_alias_for(
        self, identity: CardIdentity
    ) -> Optional[ProviderSearchAlias]:
        return self._search_aliases.get(_identity_key(identity))

    def has_search_alias(self, identity: CardIdentity) -> bool:
        return self.search_alias_for(identity) is not None

    def identity_for_search(
        self, identity: CardIdentity
    ) -> tuple[CardIdentity, Optional[ProviderSearchAlias]]:
        alias = self.search_alias_for(identity)
        if alias is None:
            return identity, None
        return replace(
            identity,
            card_name=alias.search_card_name,
            set=alias.search_set_name,
        ), alias

    def _snapshot_key(self, identity: CardIdentity) -> Tuple[str, ...]:
        alias = self.search_alias_for(identity)
        suffix = (
            (
                "provider-alias",
                _normalize_card_name(alias.search_card_name),
                _normalize(alias.search_set_name),
                _normalize(alias.provenance),
                alias.catalog_card_id,
                alias.catalog_set_id,
                alias.catalog_local_id,
            )
            if alias is not None
            else ("provider-alias", "none")
        )
        bridge_suffix = (
            "set-bridge",
            *self.set_bridge_registry.cache_key(_identity_key(identity)),
        )
        return _identity_key(identity) + suffix + bridge_suffix

    def _market_cache_key(
        self, identity: CardIdentity, market: str
    ) -> Tuple[str, ...]:
        return ("market-record", market.upper()) + self._snapshot_key(identity)

    def _prime_market_match(
        self,
        identity: CardIdentity,
        market: str,
        card: Mapping[str, object],
        *,
        count_match: bool = True,
    ) -> bool:
        normalized_market = market.upper()
        returned_market = str(card.get("market") or "").strip().upper()
        if returned_market and returned_market != normalized_market:
            self.counters.market_mismatch_rejections += 1
            return False
        key = self._market_cache_key(identity, normalized_market)
        self._market_cache[key] = PokeTraceMarketSearchResult(
            normalized_market,
            MARKET_SEARCH_MATCHED,
            card,
        )
        self._identity_primed_market_keys.add(key)
        if count_match:
            self._count_market_match(normalized_market)
            if self.has_search_alias(identity):
                self._count_alias_market_match(normalized_market)
        return True

    def _prime_market_no_match(
        self, identity: CardIdentity, market: str
    ) -> None:
        normalized_market = market.upper()
        key = self._market_cache_key(identity, normalized_market)
        self._market_cache[key] = PokeTraceMarketSearchResult(
            normalized_market,
            MARKET_SEARCH_CLEAN_NO_MATCH,
        )
        self._identity_primed_market_keys.add(key)

    def _count_market_match(self, market: str) -> None:
        if market == "US":
            self.counters.us_matches += 1
        else:
            self.counters.eu_matches += 1

    def _count_alias_market_search(self, market: str) -> None:
        self.counters.provider_alias_market_searches += 1
        if market == "US":
            self.counters.provider_alias_market_searches_us += 1
        else:
            self.counters.provider_alias_market_searches_eu += 1

    def _count_alias_market_match(self, market: str) -> None:
        self.counters.alias_market_matches += 1
        if market == "US":
            self.counters.alias_market_matches_us += 1
        else:
            self.counters.alias_market_matches_eu += 1

    def snapshot_for(self, identity: CardIdentity) -> PokeTraceSnapshot:
        if not self.config.enabled or not self.config.api_key:
            return PokeTraceSnapshot(POKETRACE_DISABLED)

        key = self._snapshot_key(identity)
        cached = self._cached_snapshot(key)
        if cached is not None:
            return cached

        us_result = self._search_exact_result(identity, "US")
        if (
            self.circuit_open
            and us_result.status == MARKET_SEARCH_RATE_LIMITED
        ):
            # A Pro snapshot would otherwise proceed to its EU request.
            self._record_call_avoided_after_breaker()
            result = PokeTraceSnapshot(POKETRACE_RATE_LIMITED)
            self._cache[key] = result
            return result

        eu_result = self._search_exact_result(identity, "EU")
        us = us_result.card if us_result.status == MARKET_SEARCH_MATCHED else None
        eu = eu_result.card if eu_result.status == MARKET_SEARCH_MATCHED else None
        if us is None and eu is None:
            clean_no_match = bool(
                us_result.status == MARKET_SEARCH_CLEAN_NO_MATCH
                and eu_result.status == MARKET_SEARCH_CLEAN_NO_MATCH
            )
            result = PokeTraceSnapshot(
                POKETRACE_RATE_LIMITED
                if self.circuit_open
                else (
                    POKETRACE_NO_MATCH
                    if clean_no_match
                    else POKETRACE_DISABLED
                )
            )
            if clean_no_match:
                self.counters.no_match += 1
            self._cache[key] = result
            return result

        us_values = _us_market_values(identity, us) if us is not None else None
        cardmarket = (
            _cardmarket_opportunity(eu, self.config) if eu is not None else None
        )
        if us_values is not None:
            self.counters.us_raw_available += int(
                us_values.ungraded_value is not None
            )
            self.counters.us_psa8_available += int(
                us_values.grade8_generic_value is not None
            )
            self.counters.us_psa9_available += int(
                us_values.grade9_generic_value is not None
            )
            self.counters.us_psa10_available += int(
                us_values.psa10_value is not None
            )
        if eu is not None:
            aggregated, active_asks = _eu_cardmarket_availability(eu)
            self.counters.eu_cardmarket_aggregated_available += int(aggregated)
            self.counters.eu_active_ask_available += int(active_asks)
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
            us_record_id=_provider_record_id(us),
            eu_record_id=_provider_record_id(eu),
        )
        self._cache[key] = result
        return result

    def _search_exact(
        self, identity: CardIdentity, market: str
    ) -> Optional[Mapping[str, object]]:
        result = self._search_exact_result(identity, market)
        return result.card if result.status == MARKET_SEARCH_MATCHED else None

    def _search_exact_result(
        self, identity: CardIdentity, market: str
    ) -> PokeTraceMarketSearchResult:
        normalized_market = market.upper()
        cache_key = self._market_cache_key(identity, normalized_market)
        cached = self._market_cache.get(cache_key)
        if cached is not None:
            self.counters.market_record_cache_hits += 1
            if cache_key in self._identity_primed_market_keys:
                self.counters.primed_market_calls_avoided += 1
                self._identity_primed_market_keys.discard(cache_key)
            return cached

        search_identity, alias = self.identity_for_search(identity)
        if alias is not None:
            self._count_alias_market_search(normalized_market)
        payload, request_status = self._request_cards(
            search_identity, normalized_market
        )
        if payload is None:
            result = PokeTraceMarketSearchResult(
                normalized_market,
                request_status,
            )
            self._market_cache[cache_key] = result
            return result
        raw_data = payload.get("data")
        if not isinstance(raw_data, Sequence) or isinstance(raw_data, (str, bytes)):
            result = PokeTraceMarketSearchResult(
                normalized_market,
                MARKET_SEARCH_ERROR,
            )
            self._market_cache[cache_key] = result
            return result
        candidates = tuple(
            item
            for item in raw_data
            if isinstance(item, Mapping)
            and _candidate_market_compatible(item, normalized_market)
        )
        self.counters.market_mismatch_rejections += sum(
            1
            for item in raw_data
            if isinstance(item, Mapping)
            and not _candidate_market_compatible(item, normalized_market)
        )
        collisions = collision_index(candidates)
        matches = []
        bridge_blocked = False
        identity_key = _identity_key(identity)
        for item in candidates:
            evidence = _candidate_evidence(search_identity, item)
            set_payload = item.get("set")
            provider_collision = bool(
                isinstance(set_payload, Mapping)
                and collisions.conflicts(
                    set_payload.get("name"),
                    set_payload.get("slug"),
                    set_payload.get("id"),
                )
            )
            should_evaluate_bridge = bool(
                evidence.name_matched
                and evidence.number_exact
                and (
                    not evidence.set_matched
                    or provider_collision
                    or self.has_set_provenance(identity)
                )
            )
            if should_evaluate_bridge:
                decision = self.set_bridge_registry.evaluate(
                    identity_key,
                    item,
                    provider_alias=alias,
                    core_identity_exact=True,
                    collisions=collisions,
                )
                bridge_blocked = bool(
                    bridge_blocked
                    or decision.status
                    in {SET_BRIDGE_AMBIGUOUS, SET_BRIDGE_COLLISION}
                )
                if not evidence.set_matched:
                    evidence = _candidate_evidence(
                        search_identity, item, set_bridge=decision
                    )
                if decision.status in {
                    SET_BRIDGE_AMBIGUOUS,
                    SET_BRIDGE_COLLISION,
                }:
                    continue
            all_three_before_bridge = bool(
                evidence.name_matched
                and evidence.set_matched_before_bridge
                and evidence.card_number_matched
            )
            all_three_after_bridge = bool(
                evidence.name_matched
                and evidence.set_matched
                and evidence.card_number_matched
            )
            self.counters.candidates_name_number_bridged_set += int(
                evidence.name_matched
                and evidence.number_exact
                and evidence.set_bridged
            )
            self.counters.candidates_all_three_before_bridge += int(
                all_three_before_bridge
            )
            self.counters.candidates_all_three_after_bridge += int(
                all_three_after_bridge
            )
            self.counters.candidates_all_three_variant_compatible_after_bridge += int(
                all_three_after_bridge and evidence.variant_compatible
            )
            if evidence.rejection is None:
                matches.append(item)
        matches = tuple(matches)
        if bridge_blocked:
            self.counters.ambiguous += 1
            result = PokeTraceMarketSearchResult(
                normalized_market,
                MARKET_SEARCH_AMBIGUOUS,
            )
            self._market_cache[cache_key] = result
            return result
        if len(matches) > 1:
            self.counters.ambiguous += 1
            result = PokeTraceMarketSearchResult(
                normalized_market,
                MARKET_SEARCH_AMBIGUOUS,
            )
            self._market_cache[cache_key] = result
            return result
        if not matches:
            if normalized_market == "US":
                self.counters.us_clean_no_matches += 1
            else:
                self.counters.eu_clean_no_matches += 1
            result = PokeTraceMarketSearchResult(
                normalized_market,
                MARKET_SEARCH_CLEAN_NO_MATCH,
            )
        else:
            self._count_market_match(normalized_market)
            if alias is not None:
                self._count_alias_market_match(normalized_market)
            result = PokeTraceMarketSearchResult(
                normalized_market,
                MARKET_SEARCH_MATCHED,
                matches[0],
            )
        self._market_cache[cache_key] = result
        return result

    def _request_cards(
        self, identity: CardIdentity, market: str
    ) -> tuple[Optional[Mapping[str, object]], str]:
        if self.circuit_open:
            self._record_call_avoided_after_breaker()
            return None, MARKET_SEARCH_RATE_LIMITED
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

        response = self._request_cards_once(headers, params)
        if response is None:
            return None, MARKET_SEARCH_ERROR
        status = getattr(response, "status_code", None)
        if status == 429:
            decision = self._record_rate_limit(response)
            if not decision.retryable:
                return None, MARKET_SEARCH_RATE_LIMITED
            self.counters.rate_limit_retry_attempts += 1
            self.sleeper(self._rate_limit_wait_seconds(decision))
            response = self._request_cards_once(headers, params)
            if response is None:
                return None, MARKET_SEARCH_ERROR
            status = getattr(response, "status_code", None)
            if status == 429:
                self._record_rate_limit(response, retry_exhausted=True)
                return None, MARKET_SEARCH_RATE_LIMITED
        if status != 200:
            self.counters.request_failures += 1
            return None, MARKET_SEARCH_ERROR
        try:
            payload = response.json()
        except Exception:
            self.counters.request_failures += 1
            return None, MARKET_SEARCH_ERROR
        if not isinstance(payload, Mapping):
            self.counters.request_failures += 1
            return None, MARKET_SEARCH_ERROR
        return payload, "OK"

    def _request_cards_once(
        self,
        headers: Mapping[str, str],
        params: Mapping[str, str],
    ) -> Optional[object]:
        if self.circuit_open:
            self._record_call_avoided_after_breaker()
            return None
        self._respect_rate_limit()
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
        return response

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
        _normalize(identity.game),
        _normalize_card_name(identity.card_name),
        _normalize(identity.set),
        _normalize_card_number(identity.card_number),
        str(identity.year or ""),
        _normalize(identity.language),
        _normalize(identity.variant),
        _normalize(identity.rarity),
        _normalize(identity.finish),
        _normalize(identity.edition),
        _normalize(identity.illustrator),
        "|".join(_normalize(value) for value in identity.ambiguities),
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


def _candidate_market_compatible(
    candidate: Mapping[str, object], market: str
) -> bool:
    candidate_market = str(candidate.get("market") or "").strip().upper()
    return not candidate_market or candidate_market == market.upper()


def _provider_record_id(
    card: Optional[Mapping[str, object]],
) -> Optional[str]:
    if card is None:
        return None
    return str(card.get("id") or "").strip() or None


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


def _eu_cardmarket_availability(
    card: Mapping[str, object],
) -> tuple[bool, bool]:
    prices = card.get("prices")
    if not isinstance(prices, Mapping):
        return False, False
    cardmarket = prices.get("cardmarket")
    active = prices.get("cardmarket_unsold")
    aggregated_available = bool(
        isinstance(cardmarket, Mapping)
        and isinstance(cardmarket.get("AGGREGATED"), Mapping)
    )
    active_ask_available = bool(
        isinstance(active, Mapping)
        and any(isinstance(value, Mapping) for value in active.values())
    )
    return aggregated_available, active_ask_available


def render_poketrace_counters(provider: PokeTraceProvider) -> str:
    counters = provider.counters
    bridge = provider.set_bridge_registry.counters
    return "\n".join(
        (
            "=== V5 POKETRACE / CARDMARKET MARKET DATA ===",
            f"enabled: {str(provider.config.enabled).lower()}",
            "role: primary market-data provider for V5 when enabled",
            "plan mode: PRO_OR_HIGHER",
            "enforced minimum interval: >=0.40s",
            "US sources: eBay sold + TCGPlayer",
            "EU role: separate EUR validation/opportunity diagnostic only",
            "EU sources: CardMarket Price Trend + active asking inventory",
            "EU active asks classified as completed sales: NO",
            f"live calls: {counters.live_calls}",
            f"cache hits: {counters.cache_hits}",
            f"US exact market matches: {counters.us_matches}",
            f"EU exact market matches: {counters.eu_matches}",
            f"US market clean no-matches: {counters.us_clean_no_matches}",
            f"EU market clean no-matches: {counters.eu_clean_no_matches}",
            (
                "deterministic-alias market searches US/EU: "
                f"{counters.provider_alias_market_searches_us}/"
                f"{counters.provider_alias_market_searches_eu}"
            ),
            (
                "deterministic-alias market matches US/EU: "
                f"{counters.alias_market_matches_us}/"
                f"{counters.alias_market_matches_eu}"
            ),
            f"US RAW available: {counters.us_raw_available}",
            f"US PSA8 available: {counters.us_psa8_available}",
            f"US PSA9 available: {counters.us_psa9_available}",
            f"US PSA10 available: {counters.us_psa10_available}",
            (
                "EU CardMarket AGGREGATED available: "
                f"{counters.eu_cardmarket_aggregated_available}"
            ),
            f"EU active-ask data available: {counters.eu_active_ask_available}",
            f"market-qualified record cache hits: {counters.market_record_cache_hits}",
            f"cross-market candidate rejections: {counters.market_mismatch_rejections}",
            (
                "market candidates name+number+bridged_set: "
                f"{counters.candidates_name_number_bridged_set}"
            ),
            (
                "market candidates all_three_before_bridge: "
                f"{counters.candidates_all_three_before_bridge}"
            ),
            (
                "market candidates all_three_after_bridge: "
                f"{counters.candidates_all_three_after_bridge}"
            ),
            (
                "market candidates all_three_variant_compatible_after_bridge: "
                f"{counters.candidates_all_three_variant_compatible_after_bridge}"
            ),
            "--- deterministic TCGdex -> PokeTrace set bridge ---",
            f"set_bridge_attempts: {bridge.set_bridge_attempts}",
            f"set_bridge_exact: {bridge.set_bridge_exact}",
            f"set_bridge_no_mapping: {bridge.set_bridge_no_mapping}",
            f"set_bridge_ambiguous: {bridge.set_bridge_ambiguous}",
            f"set_bridge_collision: {bridge.set_bridge_collision}",
            (
                "set_bridge_via_tcgdex_alias: "
                f"{bridge.set_bridge_via_tcgdex_alias}"
            ),
            (
                "set_bridge_via_english_twin: "
                f"{bridge.set_bridge_via_english_twin}"
            ),
            (
                "set_bridge_via_versioned_mapping: "
                f"{bridge.set_bridge_via_versioned_mapping}"
            ),
            (
                "set_bridge_via_observed_exact: "
                f"{bridge.set_bridge_via_observed_exact}"
            ),
            *(
                f"set_bridge remaining no-match {reason}: {count}"
                for reason, count in sorted(bridge.no_match_reasons.items())
            ),
            "provider US/EU record IDs kept separate: YES",
            "USD/EUR values silently mixed: NO",
            f"no match: {counters.no_match}",
            f"ambiguous: {counters.ambiguous}",
            f"request failures: {counters.request_failures}",
            f"rate limited: {counters.rate_limited}",
            f"429 short/retryable: {counters.retryable_429}",
            f"429 long/non-retryable: {counters.long_429}",
            f"429 unclassified: {counters.unclassified_429}",
            f"terminal 429 detected: {counters.terminal_429_detected}",
            f"429 retry attempts: {counters.rate_limit_retry_attempts}",
            f"circuit breaker opened: {counters.circuit_breaker_opened}",
            (
                "calls avoided after breaker: "
                f"{counters.calls_avoided_after_breaker}"
            ),
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
