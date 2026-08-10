from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Tuple

from ecb_fx import ECBCurrencyConverter

from .card_identity_catalog import (
    MultilingualPokemonCardResolver,
    render_card_catalog_counters,
)
from .ebay_live_diagnostic import MarketplaceAggregate, OAuthAggregate
from .gcc_live_adapter import V4GCCBrowserSession
from .live_raw_pipeline import (
    LiveRawPipelineConfig,
    LiveRawPipelineDiagnostic,
    LiveRawPipelineSummary,
    PipelineIdentityAggregate,
    PipelineImageAggregate,
    _DiscoveryRecord,
    identity_status,
    render_live_raw_pipeline_summary,
    IDENTITY_OK,
)
from .market_values.gcc_history.provider import GCCProviderConfig, GCCHistoryProvider
from .market_values.poketrace import (
    PokeTraceConfig,
    PokeTraceProvider,
    render_poketrace_counters,
)
from .market_values.poketrace_free import (
    FreeTierPokeTraceProvider,
    free_tier_config_from_env,
    render_free_poketrace_counters,
)


class _PokeTracePrimaryMarketSource:
    """Expose only language-safe PokeTrace US values to the USD aggregator."""

    _SUPPORTED_US_LANGUAGES = {
        "english",
        "anglais",
        "en",
        "japanese",
        "japonais",
        "ja",
        "jp",
        "chinese",
        "chinois",
        "zh",
        "thai",
        "th",
        "indonesian",
        "id",
    }

    def __init__(self, provider: PokeTraceProvider) -> None:
        self.provider = provider

    def values_for(self, identity):
        snapshot = self.provider.snapshot_for(identity)
        language = str(identity.language or "").strip().casefold()
        if language not in self._SUPPORTED_US_LANGUAGES:
            return None
        return snapshot.us_values


def _workflow_safe_poketrace_config(config: PokeTraceConfig) -> PokeTraceConfig:
    workflow_authorized = (
        os.getenv("GITHUB_ACTIONS", "").strip().casefold() == "true"
    )
    if not workflow_authorized and config.enabled:
        return replace(config, enabled=False)
    return config


def _build_poketrace_provider() -> PokeTraceProvider:
    plan_mode = os.getenv("POKETRACE_PLAN", "free").strip().casefold()
    if plan_mode == "free":
        config = _workflow_safe_poketrace_config(free_tier_config_from_env())
        return FreeTierPokeTraceProvider(config=config)
    config = _workflow_safe_poketrace_config(PokeTraceConfig.from_env())
    return PokeTraceProvider(config=config)


def _render_poketrace(provider: PokeTraceProvider) -> str:
    if isinstance(provider, FreeTierPokeTraceProvider):
        return render_free_poketrace_counters(provider)
    return render_poketrace_counters(provider)


class CatalogAwareLiveRawPipelineDiagnostic(LiveRawPipelineDiagnostic):
    """V5 pipeline with canonical identity resolution and PokeTrace market data.

    TCGdex remains the multilingual identity resolver, with Pokémon TCG API as
    the English/unknown-language fallback. PokeTrace is the primary V5 market
    data source when configured; GCC remains a complementary graded-history
    source. During FREE_TEST, PokeTrace is deliberately restricted to US RAW
    prices and does not call EU/CardMarket. No listing record is persisted.
    """

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        card_catalog_resolver: MultilingualPokemonCardResolver,
        config: Optional[LiveRawPipelineConfig] = None,
        gcc_history_provider: Optional[GCCHistoryProvider] = None,
        poketrace_provider: Optional[PokeTraceProvider] = None,
    ) -> None:
        self.card_catalog_resolver = card_catalog_resolver
        self.poketrace = poketrace_provider or _build_poketrace_provider()
        self.poketrace_market_source = _PokeTracePrimaryMarketSource(self.poketrace)
        super().__init__(
            client_id,
            client_secret,
            config=config,
            set_number_resolver=card_catalog_resolver,
            gcc_history_provider=gcc_history_provider,
            offline_market_sources=(self.poketrace_market_source,),
        )

    def _candidate_from_record(
        self,
        record: _DiscoveryRecord,
        identity_counts: PipelineIdentityAggregate,
        image_counts: PipelineImageAggregate,
    ) -> Tuple[object, bool]:
        candidate, raw = super()._candidate_from_record(
            record, identity_counts, image_counts
        )
        if candidate is None:
            return None, raw

        # The base resolver already rescues missing card names from set+number.
        # Run the full resolver here as well when eBay supplied a name, so a
        # French listing such as "Ekans" can be canonicalised to the French
        # TCGdex identity without changing its language discriminator.
        resolved = self.card_catalog_resolver.resolve_identity(candidate.identity)
        if (
            resolved.matched
            and not resolved.ambiguous
            and identity_status(resolved.identity) == IDENTITY_OK
        ):
            candidate = replace(candidate, identity=resolved.identity)
        # An external catalogue ambiguity must never turn a previously clean
        # eBay identity into a guessed identity. Keep the original candidate.
        return candidate, raw


def _fallback_summary(config: LiveRawPipelineConfig) -> LiveRawPipelineSummary:
    return LiveRawPipelineSummary(
        OAuthAggregate("INTERNAL_ERROR", False, None),
        tuple(
            MarketplaceAggregate(marketplace_id=value)
            for value in config.marketplaces
        ),
    )


def main() -> int:
    config = LiveRawPipelineConfig.from_env()
    client_id = os.getenv("EBAY_CLIENT_ID", "").strip()
    client_secret = os.getenv("EBAY_CLIENT_SECRET", "").strip()
    resolver = MultilingualPokemonCardResolver()
    poketrace = _build_poketrace_provider()

    workflow_authorized = (
        os.getenv("GITHUB_ACTIONS", "").strip().casefold() == "true"
    )
    try:
        gcc_live_requested = (
            os.getenv("GCC_HISTORY_ENABLED", "false").strip().casefold() == "true"
        )
        session_file = Path("gcc_session.json")
        if gcc_live_requested and workflow_authorized and session_file.is_file():
            with V4GCCBrowserSession(str(session_file)) as source:
                gcc_provider = GCCHistoryProvider(
                    config=GCCProviderConfig.from_env(),
                    source=source,
                    converter=ECBCurrencyConverter(),
                )
                diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
                    client_id,
                    client_secret,
                    config=config,
                    card_catalog_resolver=resolver,
                    gcc_history_provider=gcc_provider,
                    poketrace_provider=poketrace,
                )
                summary = diagnostic.run()
        else:
            diagnostic = CatalogAwareLiveRawPipelineDiagnostic(
                client_id,
                client_secret,
                config=config,
                card_catalog_resolver=resolver,
                poketrace_provider=poketrace,
            )
            summary = diagnostic.run()
    except Exception:
        summary = _fallback_summary(config)

    print(render_card_catalog_counters(resolver))
    print(_render_poketrace(poketrace))
    print("=== V5 EBAY OAUTH OBSERVABILITY ===")
    print(
        "credentials present: "
        f"{str(bool(client_id and client_secret)).lower()}"
    )
    print(f"OAuth HTTP/status: {summary.oauth.http_status}")
    print("secret values printed: 0")
    print(render_live_raw_pipeline_summary(summary))
    return 0 if summary.successful else 1


if __name__ == "__main__":
    sys.exit(main())
