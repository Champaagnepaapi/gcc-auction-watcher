from __future__ import annotations

import hashlib
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
from .ebay import (
    RAW_CONDITION_ID,
    identity_aspect_audit,
    parse_ebay_item,
    resolve_card_identity,
)
from .ebay_live_diagnostic import MarketplaceAggregate, OAuthAggregate
from .gcc_live_adapter import V4GCCBrowserSession
from .image_detection import (
    BACK_IMAGE_CANDIDATE,
    BACK_IMAGE_CONFIRMED,
)
from .live_raw_pipeline import (
    LiveRawPipelineConfig,
    LiveRawPipelineDiagnostic,
    LiveRawPipelineSummary,
    PipelineIdentityAggregate,
    PipelineImageAggregate,
    _DiscoveryRecord,
    _PipelineCandidate,
    identity_status,
    render_live_raw_pipeline_summary,
    IDENTITY_AMBIGUOUS,
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
from .models import StructuredGradingStatus
from .poketrace_identity import (
    PokeTraceIdentityResolver,
    render_poketrace_identity_counters,
)
from .visual_identity import (
    LocalVisualIdentityResolver,
    render_visual_identity_counters,
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
    """V5 pipeline with hybrid catalogue + local visual identity rescue.

    Normal identity chain remains TCGdex -> PokeTrace -> Pokemon TCG API. RAW
    records that are still ambiguous/incomplete then receive one conservative
    local visual pass against PokeTrace canonical scans. The final IDENTITY_OK
    gate is unchanged: visual evidence must resolve the ambiguity before any
    valuation happens.
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
        visual_identity_resolver: Optional[LocalVisualIdentityResolver] = None,
    ) -> None:
        self.card_catalog_resolver = card_catalog_resolver
        self.poketrace = poketrace_provider or _build_poketrace_provider()
        self.poketrace_market_source = _PokeTracePrimaryMarketSource(self.poketrace)
        self._identity_records_seen = 0
        self._sample_item_ids: set[str] = set()
        super().__init__(
            client_id,
            client_secret,
            config=config,
            set_number_resolver=card_catalog_resolver,
            gcc_history_provider=gcc_history_provider,
            offline_market_sources=(self.poketrace_market_source,),
        )
        if visual_identity_resolver is not None:
            self.visual_identity = visual_identity_resolver
        elif isinstance(card_catalog_resolver, HybridPokemonCardResolver):
            self.visual_identity = LocalVisualIdentityResolver(
                card_catalog_resolver.poketrace_identity,
                ebay_image_fetcher=self.discovery._image_fetcher,
            )
        else:
            self.visual_identity = None

    def sample_fingerprint(self) -> str:
        """Anonymous in-log fingerprint to detect whether two runs saw one sample."""

        if not self._sample_item_ids:
            return "EMPTY"
        digest = hashlib.sha256(
            "\n".join(sorted(self._sample_item_ids)).encode("utf-8")
        ).hexdigest()
        return digest[:16]

    def _candidate_from_record(
        self,
        record: _DiscoveryRecord,
        identity_counts: PipelineIdentityAggregate,
        image_counts: PipelineImageAggregate,
    ) -> Tuple[object, bool]:
        self._identity_records_seen += 1
        if record.item_id:
            self._sample_item_ids.add(record.item_id)

        initial = resolve_card_identity(
            record.enriched,
        )
        identity = initial.identity
        aspect_audit = identity_aspect_audit(record.enriched)
        identity_counts.unmapped_name_like_aspect_labels += int(
            aspect_audit.unmapped_name_like_label
        )
        identity_counts.unmapped_number_like_aspect_labels += int(
            aspect_audit.unmapped_number_like_label
        )
        source = "eBay structured identity"

        resolved = self.card_catalog_resolver.resolve_identity(identity)
        if resolved.matched and not resolved.ambiguous:
            identity = resolved.identity
            source = resolved.source
        elif resolved.ambiguous and not identity.ambiguities:
            identity = replace(identity, ambiguities=("catalog_identity_ambiguous",))

        try:
            listing = parse_ebay_item(record.enriched)
        except Exception:
            _progress(
                f"identity record {self._identity_records_seen}: listing parse failed"
            )
            # Keep identity accounting coherent even when listing parsing fails.
            self._count_identity(identity, identity_counts)
            return None, False

        raw = bool(
            listing.condition_id == RAW_CONDITION_ID
            and listing.grading_status is StructuredGradingStatus.RAW
        )

        image_counts.front_available += int(listing.primary_image_url is not None)
        back_state, _ = self.discovery._back_image_state(record.enriched)
        if back_state == BACK_IMAGE_CONFIRMED:
            image_counts.back_confirmed += 1
        elif back_state == BACK_IMAGE_CANDIDATE:
            image_counts.back_candidate += 1
        else:
            image_counts.back_unknown += 1

        status_before_visual = identity_status(identity)
        if (
            raw
            and listing.primary_image_url is not None
            and status_before_visual != IDENTITY_OK
            and self.visual_identity is not None
        ):
            _progress(
                f"identity record {self._identity_records_seen}: local visual rescue"
            )
            visual = self.visual_identity.resolve_identity(
                identity,
                listing.image_urls,
            )
            if visual.matched:
                identity = visual.identity
                source = "VISUAL_POKETRACE"
                _progress(
                    f"identity record {self._identity_records_seen}: visual rescue accepted"
                )

        status = self._count_identity(identity, identity_counts)

        if not raw:
            _progress(f"identity record {self._identity_records_seen}: not eligible")
            return None, False

        if status != IDENTITY_OK or listing.primary_image_url is None:
            reason = "ambiguous" if status == IDENTITY_AMBIGUOUS else "raw but unresolved"
            if status == IDENTITY_OK and listing.primary_image_url is None:
                reason = "usable identity but missing front image"
            _progress(f"identity record {self._identity_records_seen}: {reason}")
            return None, True

        _progress(
            f"identity record {self._identity_records_seen}: usable via {source}"
        )
        return _PipelineCandidate(listing, identity, back_state), True

    @staticmethod
    def _count_identity(
        identity,
        identity_counts: PipelineIdentityAggregate,
    ) -> str:
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
        return status


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
    diagnostic = None
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
    if diagnostic is not None and diagnostic.visual_identity is not None:
        print(render_visual_identity_counters(diagnostic.visual_identity))
    print(_render_poketrace(poketrace))
    print("=== V5 LIVE SAMPLE ===")
    print(
        "sample fingerprint: "
        + (diagnostic.sample_fingerprint() if diagnostic is not None else "UNAVAILABLE")
    )
    print(
        "sample item ids printed/persisted: 0"
    )
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
