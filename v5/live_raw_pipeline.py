"""Pipeline eBay RAW Production V5, agrege et sans persistance.

Ce module est destine uniquement au workflow manuel V5. Les objets eBay,
leurs identifiants et les requetes conceptuelles Product Research restent en
memoire pendant le run. Seuls des compteurs agreges sont rendus.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, Optional, Protocol, Sequence, Tuple

from .ebay import (
    RAW_CONDITION_ID,
    SetNumberCardNameResolver,
    parse_ebay_item,
    resolve_card_identity,
)
from .ebay_live_diagnostic import (
    MARKETPLACES,
    RESULT_LIMIT,
    EbayLiveDiagnostic,
    MarketplaceAggregate,
    OAuthAggregate,
    _DiscoveryRecord,
)
from .image_detection import (
    BACK_IMAGE_CANDIDATE,
    BACK_IMAGE_CONFIRMED,
    BACK_IMAGE_UNKNOWN,
    LocalPokemonBackDetector,
)
from .market_values.aggregator import MarketValueAggregator
from .market_values.economic import (
    COST_MODEL_INCOMPLETE,
    ECONOMIC_REJECT_EVEN_PSA10,
    GRADE9_PROFITABLE,
    PSA10_DEPENDENT,
    RAW_ARBITRAGE,
    CostModel,
    EconomicThresholds,
    evaluate_economic_pre_filter,
)
from .market_values.gcc_history.models import Grader, ValuationType
from .market_values.gcc_history.provider import (
    GCCProviderConfig,
    GCCHistoryProvider,
)
from .market_values.models import (
    MARKET_VALUE_CONFLICT,
    MARKET_VALUES_MISSING,
    AggregationStatus,
    MarketValues,
    identity_key,
)
from .market_values.pricecharting import PriceChartingConfig, PriceChartingProvider
from .market_values.secondary import (
    MarketplaceInsightsProvider,
    PSASalesProvider,
    active_asking_statistics,
)
from .models import CardIdentity, EbayListing, StructuredGradingStatus


IDENTITY_OK = "IDENTITY_OK"
IDENTITY_AMBIGUOUS = "IDENTITY_AMBIGUOUS"
IDENTITY_INSUFFICIENT = "IDENTITY_INSUFFICIENT"
MANUAL_MARKET_VALIDATION_REQUIRED = "MANUAL_MARKET_VALIDATION_REQUIRED"
PRODUCT_RESEARCH_MODE = "MANUAL_VALIDATION_ONLY"
NO_PERSISTENCE_MODE = "NO_PERSISTENCE / MEMORY_ONLY"
RAW_DISCOVERY_INTERVAL_MINUTES = 10


@dataclass(frozen=True)
class LiveRawPipelineConfig:
    result_limit: int = RESULT_LIMIT
    include_ebay_ch: bool = False

    def __post_init__(self) -> None:
        if not 1 <= self.result_limit <= RESULT_LIMIT:
            raise ValueError(
                f"V5_LIVE_RAW_RESULT_LIMIT doit etre compris entre 1 et {RESULT_LIMIT}"
            )

    @classmethod
    def from_env(cls) -> "LiveRawPipelineConfig":
        return cls(
            result_limit=int(os.getenv("V5_LIVE_RAW_RESULT_LIMIT", str(RESULT_LIMIT))),
            include_ebay_ch=os.getenv("V5_LIVE_INCLUDE_EBAY_CH", "false")
            .strip()
            .casefold()
            == "true",
        )

    @property
    def marketplaces(self) -> Tuple[str, ...]:
        return MARKETPLACES if self.include_ebay_ch else ("EBAY_US",)


class SeenItemStore(Protocol):
    persistence_mode: str

    def mark_first_seen(self, item_id: str) -> bool:
        ...


class MemoryOnlySeenItemStore:
    persistence_mode = NO_PERSISTENCE_MODE

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def mark_first_seen(self, item_id: str) -> bool:
        if item_id in self._seen:
            return False
        self._seen.add(item_id)
        return True


@dataclass(frozen=True, repr=False)
class ManualProductResearchQuery:
    terms: Tuple[str, ...]

    def as_text(self) -> str:
        return " ".join(self.terms)


class ManualProductResearch:
    mode = PRODUCT_RESEARCH_MODE

    def __init__(self) -> None:
        self.automated_calls = 0

    def build_query(
        self, identity: CardIdentity
    ) -> Optional[ManualProductResearchQuery]:
        if not identity.is_unambiguous_pokemon():
            return None
        terms = tuple(
            str(value).strip()
            for value in (
                identity.card_name,
                identity.set,
                identity.card_number,
                identity.variant,
                identity.language,
            )
            if value and str(value).strip()
        )
        return ManualProductResearchQuery(terms) if terms else None


class OfflineMarketValueSource(Protocol):
    def values_for(self, identity: CardIdentity) -> Optional[MarketValues]:
        ...


@dataclass
class PipelineIdentityAggregate:
    ok: int = 0
    ambiguous: int = 0
    insufficient: int = 0
    card_name: int = 0
    set_name: int = 0
    card_number: int = 0


@dataclass
class PipelineImageAggregate:
    front_available: int = 0
    back_confirmed: int = 0
    back_candidate: int = 0
    back_unknown: int = 0
    back_missing_pipeline_continued: int = 0
    grading_visual_confidence_reduced: int = 0


@dataclass
class PipelineMarketAggregate:
    identities_evaluated: int = 0
    values_found: int = 0
    values_missing: int = 0
    value_conflicts: int = 0
    manual_validation_required: int = 0
    manual_product_research_queries_possible: int = 0
    gcc_raw_direct_values: int = 0
    gcc_psa9_direct_values: int = 0
    gcc_psa10_direct_values: int = 0
    gcc_proxy_values: int = 0


@dataclass
class PipelineEconomicAggregate:
    raw_arbitrage: int = 0
    grade9_profitable: int = 0
    psa10_dependent: int = 0
    reject_even_psa10: int = 0
    cost_model_incomplete: int = 0


@dataclass(frozen=True)
class ProviderAggregate:
    pricecharting_enabled: bool
    pricecharting_live_calls: int
    marketplace_insights_enabled: bool
    marketplace_insights_live_calls: int
    psa_sales_status: str
    product_research_mode: str
    product_research_automated_calls: int
    gcc_history_enabled: bool = False
    gcc_history_mode: str = "LIVE_UNAVAILABLE"
    gcc_history_live_calls: int = 0
    gcc_history_queries: int = 0
    gcc_history_cache_hits: int = 0
    gcc_history_records_received: int = 0
    gcc_history_exact_matches: int = 0
    gcc_history_access_mechanism: str = "UNAVAILABLE"
    gcc_live_identities_queried: int = 0
    gcc_inventory_pages_requested: int = 0
    gcc_identity_conflicts: int = 0
    gcc_records_with_grader: int = 0
    gcc_records_with_numeric_grade: int = 0
    gcc_grade_unknown: int = 0
    gcc_grade_ambiguous: int = 0
    gcc_non_grade_numeric_rejected: int = 0
    gcc_invalid_over_ten_tokens: int = 0
    gcc_special_qualifiers_excluded: int = 0
    fx_provider: str = "UNAVAILABLE"
    fx_source_url: str = "UNAVAILABLE"
    fx_rates_fetched: int = 0
    fx_cache_hits: int = 0
    fx_source_currency: str = "EUR"
    fx_target_currency: str = "USD"
    fx_rate: Optional[str] = None
    fx_rate_date: Optional[str] = None
    fx_failures: int = 0


@dataclass(frozen=True)
class LiveRawPipelineSummary:
    oauth: OAuthAggregate
    marketplaces: Tuple[MarketplaceAggregate, ...]
    raw_condition_accepted: int = 0
    duplicates_skipped: int = 0
    identity: PipelineIdentityAggregate = field(default_factory=PipelineIdentityAggregate)
    images: PipelineImageAggregate = field(default_factory=PipelineImageAggregate)
    market: PipelineMarketAggregate = field(default_factory=PipelineMarketAggregate)
    economic: PipelineEconomicAggregate = field(default_factory=PipelineEconomicAggregate)
    providers: ProviderAggregate = field(
        default_factory=lambda: ProviderAggregate(
            pricecharting_enabled=False,
            pricecharting_live_calls=0,
            marketplace_insights_enabled=False,
            marketplace_insights_live_calls=0,
            psa_sales_status="UNAVAILABLE",
            product_research_mode=PRODUCT_RESEARCH_MODE,
            product_research_automated_calls=0,
        )
    )
    seen_item_store_mode: str = NO_PERSISTENCE_MODE

    @property
    def successful(self) -> bool:
        us = next(
            (value for value in self.marketplaces if value.marketplace_id == "EBAY_US"),
            None,
        )
        return bool(
            self.oauth.token_obtained and us is not None and us.http_status == "200"
        )


@dataclass(frozen=True, repr=False)
class _PipelineCandidate:
    listing: EbayListing
    identity: CardIdentity
    back_state: str


class LiveRawPipelineDiagnostic:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        config: Optional[LiveRawPipelineConfig] = None,
        session: Optional[object] = None,
        set_number_resolver: Optional[SetNumberCardNameResolver] = None,
        back_detector: Optional[LocalPokemonBackDetector] = None,
        image_fetcher: Optional[Callable[[str], Optional[bytes]]] = None,
        offline_market_sources: Sequence[OfflineMarketValueSource] = (),
        gcc_history_provider: Optional[GCCHistoryProvider] = None,
        cost_factory: Optional[Callable[[EbayListing], CostModel]] = None,
        seen_store_factory: Callable[[], SeenItemStore] = MemoryOnlySeenItemStore,
    ) -> None:
        self.config = config or LiveRawPipelineConfig.from_env()
        self._workflow_authorized = bool(
            session is not None
            or os.getenv("GITHUB_ACTIONS", "").strip().casefold() == "true"
        )
        self.discovery = EbayLiveDiagnostic(
            client_id,
            client_secret,
            session=session,  # type: ignore[arg-type]
            set_number_resolver=set_number_resolver,
            back_detector=back_detector,
            image_fetcher=image_fetcher,
            result_limit=self.config.result_limit,
            marketplaces=self.config.marketplaces,
        )
        # Ce diagnostic force le fournisseur payant a OFF, meme si
        # l'environnement local contient accidentellement une autre valeur.
        self.pricecharting = PriceChartingProvider(
            PriceChartingConfig(enabled=False, token=None),
            session=session,  # type: ignore[arg-type]
        )
        self.marketplace_insights = MarketplaceInsightsProvider()
        self.psa_sales = PSASalesProvider()
        self.product_research = ManualProductResearch()
        self.gcc_history = gcc_history_provider or GCCHistoryProvider()
        self.aggregator = MarketValueAggregator()
        self.offline_market_sources = tuple(offline_market_sources)
        self.cost_factory = cost_factory or (
            lambda listing: CostModel.from_env(
                listing.currency, raw_purchase_price=listing.price
            )
        )
        self.seen_store_factory = seen_store_factory

    def run(self) -> LiveRawPipelineSummary:
        if not self._workflow_authorized:
            return self._summary(
                OAuthAggregate("WORKFLOW_ONLY", False, None),
                tuple(
                    MarketplaceAggregate(marketplace_id=value)
                    for value in self.config.marketplaces
                ),
            )
        token, oauth = self.discovery._application_token()
        if token is None:
            return self._summary(
                oauth,
                tuple(
                    MarketplaceAggregate(marketplace_id=value)
                    for value in self.config.marketplaces
                ),
            )

        marketplace_by_id: Dict[str, MarketplaceAggregate] = {}
        records = []
        for marketplace_id in self.config.marketplaces:
            aggregate, discovered = self.discovery._discover_marketplace(
                marketplace_id, token
            )
            marketplace_by_id[marketplace_id] = aggregate
            records.extend(discovered)
        self.discovery._enrich_unique_items(records, marketplace_by_id, token)
        first_owner: Dict[str, str] = {}
        successful_ids = set()
        for record in records:
            if record.item_id:
                first_owner.setdefault(record.item_id, record.marketplace_id)
                if record.get_item_success:
                    successful_ids.add(record.item_id)
        for marketplace_id, aggregate in marketplace_by_id.items():
            aggregate.get_item_success = sum(
                1
                for item_id in successful_ids
                if first_owner.get(item_id) == marketplace_id
            )

        seen_store = self.seen_store_factory()
        identity_counts = PipelineIdentityAggregate()
        image_counts = PipelineImageAggregate()
        market_counts = PipelineMarketAggregate()
        economic_counts = PipelineEconomicAggregate()
        candidates = []
        raw_accepted = 0
        duplicates = 0

        for record in records:
            if record.item_id and not seen_store.mark_first_seen(record.item_id):
                duplicates += 1
                continue
            candidate, raw = self._candidate_from_record(
                record, identity_counts, image_counts
            )
            raw_accepted += int(raw)
            if candidate is not None:
                candidates.append(candidate)
                if candidate.back_state != BACK_IMAGE_CONFIRMED:
                    image_counts.back_missing_pipeline_continued += 1
                    image_counts.grading_visual_confidence_reduced += 1
                if self.product_research.build_query(candidate.identity) is not None:
                    market_counts.manual_product_research_queries_possible += 1

        asking_prices: Dict[Tuple[str, ...], list] = {}
        for candidate in candidates:
            key = identity_key(candidate.identity) + (candidate.listing.currency,)
            asking_prices.setdefault(key, []).append(candidate.listing.price)
        # Ces statistiques restent secondaires et ne sont jamais transmises a
        # MarketValueAggregator.
        for key, prices in asking_prices.items():
            active_asking_statistics(prices, key[-1])

        for candidate in candidates:
            self._evaluate_candidate(candidate, market_counts, economic_counts)

        marketplaces = tuple(
            marketplace_by_id[value] for value in self.config.marketplaces
        )
        return self._summary(
            oauth,
            marketplaces,
            raw_accepted,
            duplicates,
            identity_counts,
            image_counts,
            market_counts,
            economic_counts,
            seen_store.persistence_mode,
        )

    def _candidate_from_record(
        self,
        record: _DiscoveryRecord,
        identity_counts: PipelineIdentityAggregate,
        image_counts: PipelineImageAggregate,
    ) -> Tuple[Optional[_PipelineCandidate], bool]:
        resolution = resolve_card_identity(
            record.enriched,
            set_number_resolver=self.discovery._set_number_resolver,
        )
        identity = resolution.identity
        identity_counts.card_name += int(identity.card_name is not None)
        identity_counts.set_name += int(identity.set is not None)
        identity_counts.card_number += int(identity.card_number is not None)
        status = identity_status(identity)
        if status == IDENTITY_OK:
            identity_counts.ok += 1
        elif status == IDENTITY_AMBIGUOUS:
            identity_counts.ambiguous += 1
        else:
            identity_counts.insufficient += 1

        try:
            listing = parse_ebay_item(record.enriched)
        except Exception:
            return None, False
        raw = bool(
            listing.condition_id == RAW_CONDITION_ID
            and listing.grading_status is StructuredGradingStatus.RAW
        )
        if not raw:
            return None, False

        image_counts.front_available += int(listing.primary_image_url is not None)
        back_state, _ = self.discovery._back_image_state(record.enriched)
        if back_state == BACK_IMAGE_CONFIRMED:
            image_counts.back_confirmed += 1
        elif back_state == BACK_IMAGE_CANDIDATE:
            image_counts.back_candidate += 1
        else:
            image_counts.back_unknown += 1

        if status != IDENTITY_OK or listing.primary_image_url is None:
            return None, True
        return _PipelineCandidate(listing, identity, back_state), True

    def _evaluate_candidate(
        self,
        candidate: _PipelineCandidate,
        market_counts: PipelineMarketAggregate,
        economic_counts: PipelineEconomicAggregate,
    ) -> None:
        market_counts.identities_evaluated += 1
        provider_values = []
        pricecharting_result = self.pricecharting.values_for(candidate.identity)
        if pricecharting_result.values is not None:
            provider_values.append(pricecharting_result.values)
        # Interfaces appelees sans reseau. Elles restent vides/desactivees.
        self.marketplace_insights.sold_comparables_for(candidate.identity)
        self.psa_sales.sold_comparables_for(candidate.identity)
        for source in self.offline_market_sources:
            value = source.values_for(candidate.identity)
            if value is not None:
                provider_values.append(value)
        if self.gcc_history.counters.enabled:
            gcc_result = self.gcc_history.market_for(
                candidate.identity,
                candidate.listing.currency,
            )
            if gcc_result.market_values is not None:
                provider_values.append(gcc_result.market_values)
            raw_value = gcc_result.valuation(Grader.RAW, None)
            psa9_value = gcc_result.valuation(Grader.PSA, Decimal("9"))
            psa10_value = gcc_result.valuation(Grader.PSA, Decimal("10"))
            market_counts.gcc_raw_direct_values += int(
                raw_value is not None
                and raw_value.valuation_type is ValuationType.DIRECT_MARKET_VALUE
            )
            market_counts.gcc_psa9_direct_values += int(
                psa9_value is not None
                and psa9_value.valuation_type is ValuationType.DIRECT_MARKET_VALUE
            )
            market_counts.gcc_psa10_direct_values += int(
                psa10_value is not None
                and psa10_value.valuation_type is ValuationType.DIRECT_MARKET_VALUE
            )
            market_counts.gcc_proxy_values += sum(
                valuation.valuation_type is ValuationType.CROSS_GRADER_PROXY
                for valuation in gcc_result.valuations.values()
            )

        aggregate = self.aggregator.aggregate(candidate.identity, provider_values)
        if aggregate.status is AggregationStatus.MISSING:
            market_counts.values_missing += 1
            market_counts.manual_validation_required += 1
            return
        if aggregate.status is AggregationStatus.CONFLICT:
            market_counts.value_conflicts += 1
            market_counts.manual_validation_required += 1
            return

        try:
            costs = self.cost_factory(candidate.listing)
            economic = evaluate_economic_pre_filter(
                aggregate,
                costs,
                candidate.back_state,
                thresholds=EconomicThresholds.from_env(),
            )
        except (ArithmeticError, TypeError, ValueError):
            market_counts.values_found += 1
            economic_counts.cost_model_incomplete += 1
            return

        if MARKET_VALUES_MISSING in economic.signals:
            market_counts.values_missing += 1
            market_counts.manual_validation_required += 1
            return
        if MARKET_VALUE_CONFLICT in economic.signals:
            market_counts.value_conflicts += 1
            market_counts.manual_validation_required += 1
            return

        market_counts.values_found += 1
        economic_counts.raw_arbitrage += int(RAW_ARBITRAGE in economic.signals)
        economic_counts.grade9_profitable += int(
            GRADE9_PROFITABLE in economic.signals
        )
        economic_counts.psa10_dependent += int(PSA10_DEPENDENT in economic.signals)
        economic_counts.reject_even_psa10 += int(
            ECONOMIC_REJECT_EVEN_PSA10 in economic.signals
        )
        economic_counts.cost_model_incomplete += int(
            COST_MODEL_INCOMPLETE in economic.signals
        )

    def _summary(
        self,
        oauth: OAuthAggregate,
        marketplaces: Tuple[MarketplaceAggregate, ...],
        raw_condition_accepted: int = 0,
        duplicates_skipped: int = 0,
        identity: Optional[PipelineIdentityAggregate] = None,
        images: Optional[PipelineImageAggregate] = None,
        market: Optional[PipelineMarketAggregate] = None,
        economic: Optional[PipelineEconomicAggregate] = None,
        seen_mode: str = NO_PERSISTENCE_MODE,
    ) -> LiveRawPipelineSummary:
        gcc_source = self.gcc_history.source
        parsing = getattr(gcc_source, "parsing", None)
        converter = self.gcc_history.converter
        snapshot = getattr(converter, "snapshot", None)
        fx_rate = (
            snapshot.rate("EUR", self.gcc_history.config.default_currency)
            if snapshot is not None
            else None
        )
        return LiveRawPipelineSummary(
            oauth=oauth,
            marketplaces=marketplaces,
            raw_condition_accepted=raw_condition_accepted,
            duplicates_skipped=duplicates_skipped,
            identity=identity or PipelineIdentityAggregate(),
            images=images or PipelineImageAggregate(),
            market=market or PipelineMarketAggregate(),
            economic=economic or PipelineEconomicAggregate(),
            providers=ProviderAggregate(
                pricecharting_enabled=self.pricecharting.config.enabled,
                pricecharting_live_calls=self.pricecharting.live_calls,
                marketplace_insights_enabled=self.marketplace_insights.enabled,
                marketplace_insights_live_calls=self.marketplace_insights.live_calls,
                psa_sales_status=self.psa_sales.status,
                product_research_mode=self.product_research.mode,
                product_research_automated_calls=self.product_research.automated_calls,
                gcc_history_enabled=self.gcc_history.counters.enabled,
                gcc_history_mode=self.gcc_history.mode,
                gcc_history_live_calls=self.gcc_history.counters.live_calls,
                gcc_history_queries=self.gcc_history.counters.queries,
                gcc_history_cache_hits=self.gcc_history.counters.cache_hits,
                gcc_history_records_received=self.gcc_history.counters.records_received,
                gcc_history_exact_matches=self.gcc_history.counters.exact_matches,
                gcc_history_access_mechanism=getattr(
                    gcc_source, "access_mechanism", "UNAVAILABLE"
                ),
                gcc_live_identities_queried=getattr(
                    gcc_source, "identities_queried", 0
                ),
                gcc_inventory_pages_requested=getattr(
                    gcc_source, "inventory_pages_requested", 0
                ),
                gcc_identity_conflicts=getattr(
                    gcc_source, "identity_conflicts", 0
                ),
                gcc_records_with_grader=getattr(
                    parsing, "transactions_with_grader", 0
                ),
                gcc_records_with_numeric_grade=getattr(
                    parsing, "transactions_with_numeric_grade", 0
                ),
                gcc_grade_unknown=getattr(parsing, "grade_absent", 0),
                gcc_grade_ambiguous=getattr(parsing, "grade_ambiguous", 0),
                gcc_non_grade_numeric_rejected=getattr(
                    parsing, "non_grade_numeric_rejected", 0
                ),
                gcc_invalid_over_ten_tokens=getattr(
                    parsing, "invalid_over_ten_tokens", 0
                ),
                gcc_special_qualifiers_excluded=getattr(
                    parsing, "special_qualifiers_excluded", 0
                ),
                fx_provider=(
                    getattr(snapshot, "provider", None)
                    or getattr(converter, "method", "UNAVAILABLE")
                ),
                fx_source_url=getattr(snapshot, "source_url", "UNAVAILABLE"),
                fx_rates_fetched=getattr(converter, "fetches", 0),
                fx_cache_hits=getattr(converter, "cache_hits", 0),
                fx_target_currency=self.gcc_history.config.default_currency,
                fx_rate=(str(fx_rate) if fx_rate is not None else None),
                fx_rate_date=(
                    snapshot.rate_date.isoformat() if snapshot is not None else None
                ),
                fx_failures=getattr(converter, "failures", 0),
            ),
            seen_item_store_mode=seen_mode,
        )


def identity_status(identity: CardIdentity) -> str:
    if identity.ambiguities:
        return IDENTITY_AMBIGUOUS
    if identity.is_unambiguous_pokemon():
        return IDENTITY_OK
    return IDENTITY_INSUFFICIENT


def render_live_raw_pipeline_summary(summary: LiveRawPipelineSummary) -> str:
    us = next(
        (value for value in summary.marketplaces if value.marketplace_id == "EBAY_US"),
        MarketplaceAggregate("EBAY_US"),
    )
    return "\n".join(
        (
            "=== V5 LIVE RAW → GCC MARKET SUMMARY ===",
            "",
            "EBAY:",
            f"OAuth: {'OK' if summary.oauth.token_obtained else 'FAIL'}",
            f"search results: {us.results_received}",
            f"getItem success: {us.get_item_success}",
            f"raw accepted: {summary.raw_condition_accepted}",
            "",
            "IDENTITY:",
            f"identity exact/usable: {summary.identity.ok}",
            f"ambiguous: {summary.identity.ambiguous}",
            f"insufficient: {summary.identity.insufficient}",
            f"card_name coverage: {summary.identity.card_name}",
            f"set coverage: {summary.identity.set_name}",
            f"card_number coverage: {summary.identity.card_number}",
            "",
            "IMAGES:",
            f"front available: {summary.images.front_available}",
            f"back confirmed: {summary.images.back_confirmed}",
            f"back candidate: {summary.images.back_candidate}",
            f"back unknown: {summary.images.back_unknown}",
            (
                "back missing but pipeline continued: "
                f"{summary.images.back_missing_pipeline_continued}"
            ),
            (
                "GRADING_VISUAL_CONFIDENCE_REDUCED: "
                f"{summary.images.grading_visual_confidence_reduced}"
            ),
            "",
            "MARKET VALUES:",
            f"identities evaluated: {summary.market.identities_evaluated}",
            f"market values found: {summary.market.values_found}",
            f"insufficient: {summary.market.values_missing}",
            f"identity conflicts: {summary.providers.gcc_identity_conflicts}",
            (
                "manual market validation required: "
                f"{summary.market.manual_validation_required}"
            ),
            f"RAW direct: {summary.market.gcc_raw_direct_values}",
            f"PSA9 direct: {summary.market.gcc_psa9_direct_values}",
            f"PSA10 direct: {summary.market.gcc_psa10_direct_values}",
            f"cross-grader proxies: {summary.market.gcc_proxy_values}",
            "",
            "GCC HISTORY:",
            (
                "enabled: "
                f"{str(summary.providers.gcc_history_enabled).lower()}"
            ),
            (
                "GCC History enabled: "
                f"{str(summary.providers.gcc_history_enabled).lower()}"
            ),
            f"mode: {summary.providers.gcc_history_mode}",
            (
                "access mechanism: "
                f"{summary.providers.gcc_history_access_mechanism}"
            ),
            (
                "live identities queried: "
                f"{summary.providers.gcc_live_identities_queried}"
            ),
            f"live calls: {summary.providers.gcc_history_live_calls}",
            (
                "public inventory pages requested: "
                f"{summary.providers.gcc_inventory_pages_requested}"
            ),
            f"cache hits: {summary.providers.gcc_history_cache_hits}",
            (
                "historical records received: "
                f"{summary.providers.gcc_history_records_received}"
            ),
            (
                "exact collectible matches: "
                f"{summary.providers.gcc_history_exact_matches}"
            ),
            "",
            "GCC PARSING:",
            f"records with grader: {summary.providers.gcc_records_with_grader}",
            (
                "records with numeric grade: "
                f"{summary.providers.gcc_records_with_numeric_grade}"
            ),
            f"grade unknown: {summary.providers.gcc_grade_unknown}",
            f"grade ambiguous: {summary.providers.gcc_grade_ambiguous}",
            (
                "ambiguous numeric tokens rejected: "
                f"{summary.providers.gcc_non_grade_numeric_rejected}"
            ),
            (
                "invalid >10 tokens ignored as non-grade: "
                f"{summary.providers.gcc_invalid_over_ten_tokens}"
            ),
            (
                "special qualifiers excluded: "
                f"{summary.providers.gcc_special_qualifiers_excluded}"
            ),
            "",
            "FX:",
            f"provider: {summary.providers.fx_provider}",
            f"source: {summary.providers.fx_source_url}",
            f"rates fetched: {summary.providers.fx_rates_fetched}",
            f"cache hits: {summary.providers.fx_cache_hits}",
            (
                f"{summary.providers.fx_source_currency}→"
                f"{summary.providers.fx_target_currency} rate: "
                f"{summary.providers.fx_rate or 'UNAVAILABLE'}"
            ),
            f"rate date: {summary.providers.fx_rate_date or 'UNAVAILABLE'}",
            f"FX failures: {summary.providers.fx_failures}",
            "",
            "ECONOMIC:",
            f"raw arbitrage: {summary.economic.raw_arbitrage}",
            f"grade9 profitable: {summary.economic.grade9_profitable}",
            f"psa10 dependent: {summary.economic.psa10_dependent}",
            f"economic reject even psa10: {summary.economic.reject_even_psa10}",
            f"cost model incomplete: {summary.economic.cost_model_incomplete}",
            (
                "manual validation required: "
                f"{summary.market.manual_validation_required}"
            ),
            "",
            "SAFETY:",
            "CardGrader calls: 0",
            "Purchases: 0",
            "Bids: 0",
            "Checkout: 0",
            "Persisted eBay records: 0",
        )
    )


def main() -> int:
    config = LiveRawPipelineConfig.from_env()
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    try:
        gcc_live_requested = (
            os.getenv("GCC_HISTORY_ENABLED", "false").strip().casefold()
            == "true"
        )
        workflow_authorized = (
            os.getenv("GITHUB_ACTIONS", "").strip().casefold() == "true"
        )
        session_file = Path("gcc_session.json")
        if gcc_live_requested and workflow_authorized and session_file.is_file():
            from ecb_fx import ECBCurrencyConverter
            from .gcc_live_adapter import V4GCCBrowserSession

            with V4GCCBrowserSession(str(session_file)) as source:
                gcc_provider = GCCHistoryProvider(
                    config=GCCProviderConfig.from_env(),
                    source=source,
                    converter=ECBCurrencyConverter(),
                )
                diagnostic = LiveRawPipelineDiagnostic(
                    client_id,
                    client_secret,
                    config=config,
                    gcc_history_provider=gcc_provider,
                )
                summary = diagnostic.run()
        else:
            diagnostic = LiveRawPipelineDiagnostic(
                client_id, client_secret, config=config
            )
            summary = diagnostic.run()
    except Exception:
        summary = LiveRawPipelineSummary(
            OAuthAggregate("INTERNAL_ERROR", False, None),
            tuple(
                MarketplaceAggregate(marketplace_id=value)
                for value in config.marketplaces
            ),
        )
    print(render_live_raw_pipeline_summary(summary))
    return 0 if summary.successful else 1


if __name__ == "__main__":
    sys.exit(main())
