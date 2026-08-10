from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path
from typing import Optional, Tuple

from ecb_fx import ECBCurrencyConverter

from .card_identity_catalog import (
    HybridPokemonCardResolver,
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
from .poketrace_identity import (
    PokeTraceIdentityResolver,
    render_poketrace_identity_counters,
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
        language = str(identity.language or "").strip().casefold()
        if (
            isinstance(self.provider, FreeTierPokeTraceProvider)
            and language not in self._SUPPORTED_US_LANGUAGES
        ):
            return None
        snapshot = self.provider.snapshot_for(identity)
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


def _progress(message: str) -> None:
    if os.getenv("V5_PROGRESS_LOGS", "false").strip().casefold() == "true":
        print(f"[V5] {message}", flush=True)


class CatalogAwareLiveRawPipelineDiagnostic(LiveRawPipelineDiagnostic):
    """V5 pipeline with hybrid canonical identity and PokeTrace market data.

    Identity chain: TCGdex -> PokeTrace -> Pokemon TCG API. A successful
    PokeTrace identity lookup primes the Free market-data cache from the same
    response, so valuation does not spend another request for that card.
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
        self._identity_records_seen = 0
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
        self._identity_records_seen += 1
        candidate, raw = super()._candidate_from_record(
            record, identity_counts, image_counts
        )
        if candidate is None:
            _progress(
                f"identity record {self._identity_records_seen}: "
                f"{'raw but unresolved' if raw else 'not eligible'}"
            )
            return None, raw

        resolved = self.card_catalog_resolver.resolve_identity(candidate.identity)
        if (
            resolved.matched
            and not resolved.ambiguous
            and identity_status(resolved.identity) == IDENTITY_OK
        ):
            candidate = replace(candidate, identity=resolved.identity)
        _progress(
            f"identity record {self._identity_records_seen}: usable "
            f"via {resolved.source if resolved.matched else 'eBay structured identity'}"
        )
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
    poketrace = _build_poketrace_provider()
    poketrace_identity = PokeTraceIdentityResolver(poketrace)
    resolver = HybridPokemonCardResolver(
        poketrace_identity_resolver=poketrace_identity
    )

    workflow_authorized = (
        os.getenv("GITHUB_ACTIONS", "").strip().casefold() == "true"
    )
    skip_gcc_live = (
        os.getenv(
            "V5_SKIP_GCC_LIVE_FOR_POKETRACE_VALIDATION", "false"
        ).strip().casefold()
        == "true"
    )
    _progress("starting eBay discovery -> identity -> PokeTrace market validation")
    try:
        gcc_live_requested = (
            os.getenv("GCC_HISTORY_ENABLED", "false").strip().casefold() == "true"
            and not skip_gcc_live
        )
        session_file = Path("gcc_session.json")
        if gcc_live_requested and workflow_authorized and session_file.is_file():
            _progress("GCC live history enabled for this run")
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
            if skip_gcc_live:
                _progress("GCC live fallback intentionally skipped for PokeTrace validation")
            else:
                _progress("GCC live fallback unavailable for this run")
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

    _progress("diagnostic completed")
    print(render_card_catalog_counters(resolver))
    print(render_poketrace_identity_counters(poketrace_identity))
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
