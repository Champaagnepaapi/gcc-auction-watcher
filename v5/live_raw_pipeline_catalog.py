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
from .identity_observability import (
    CoordinateState,
    UnresolvedIdentityDiagnostic,
    ambiguity_fields,
    VariantDiagnostic,
    analyze_coordinates,
    analyze_variant_blocking,
    determine_reason_code,
    extract_near_matches,
)
from .ebay import (
    RAW_CONDITION_ID,
    identity_aspect_audit,
    is_bundle_or_multi_card_listing,
    is_non_physical_pokemon_listing,
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
    PipelineForensicAggregate,
    PipelineMicrovariantAggregate,
    _DiscoveryRecord,
    _PipelineCandidate,
    identity_status,
    _forensic_state,
    render_live_raw_pipeline_summary,
    IDENTITY_AMBIGUOUS,
    IDENTITY_INSUFFICIENT,
    IDENTITY_OK,
)
from .market_values.gcc_history.provider import GCCProviderConfig, GCCHistoryProvider
from .market_values.poketrace import (
    CARDMARKET_DISCOUNT,
    PokeTraceConfig,
    PokeTraceProvider,
    PokeTraceSnapshot,
    pro_tier_config_from_env,
    render_poketrace_counters,
)
from .market_values.poketrace_free import (
    FreeTierPokeTraceProvider,
    free_tier_config_from_env,
    render_free_poketrace_counters,
)
from .models import StructuredGradingStatus
from .microvariants import (
    LocalMicrovariantValidator,
    MicrovariantApplicability,
    MICROVARIANT_APPLICABILITY_UNKNOWN,
)
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
        self.last_snapshot: Optional[PokeTraceSnapshot] = None

    def values_for(self, identity):
        self.last_snapshot = None
        language = str(identity.language or "").strip().casefold()
        deterministic_alias = self.provider.has_search_alias(identity)
        if (
            isinstance(self.provider, FreeTierPokeTraceProvider)
            and language not in self._SUPPORTED_US_LANGUAGES
            and not deterministic_alias
        ):
            return None
        snapshot = self.provider.snapshot_for(identity)
        self.last_snapshot = snapshot
        if (
            language not in self._SUPPORTED_US_LANGUAGES
            and not deterministic_alias
        ):
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
    config = _workflow_safe_poketrace_config(pro_tier_config_from_env())
    return PokeTraceProvider(config=config)


def _render_poketrace(provider: PokeTraceProvider) -> str:
    if isinstance(provider, FreeTierPokeTraceProvider):
        return render_free_poketrace_counters(provider)
    return render_poketrace_counters(provider)


def _progress(message: str) -> None:
    if os.getenv("V5_PROGRESS_LOGS", "false").strip().casefold() == "true":
        print(f"[V5] {message}", flush=True)


def _refresh_post_macro_applicability(resolver, identity, applicability):
    """Retry exact TCGdex microvariant proof after macro identity is complete.

    This is deliberately narrower than identity resolution: only an exact
    TCGdex catalogue result may replace an UNKNOWN/UNAVAILABLE applicability.
    Provider-market metadata and other fallback sources cannot unblock the
    microvariant gate through this path.
    """

    if applicability.status != MICROVARIANT_APPLICABILITY_UNKNOWN:
        return applicability
    resolve = getattr(resolver, "resolve_microvariant_applicability", None)
    if not callable(resolve):
        return applicability
    refreshed = resolve(identity)
    if not isinstance(refreshed, MicrovariantApplicability):
        return applicability
    if refreshed.source != "TCGDEX_EXACT":
        return applicability
    return refreshed


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
        self.microvariant_validator = LocalMicrovariantValidator()
        self.max_visual_identity_listings = max(
            0,
            min(
                20,
                int(os.getenv("V5_VISUAL_IDENTITY_MAX_LISTINGS_PER_RUN", "20")),
            ),
        )
        self._visual_identity_attempts = 0
        self.unresolved_diagnostics: list[UnresolvedIdentityDiagnostic] = []
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
                post_macro_applicability_resolver=(
                    card_catalog_resolver.resolve_microvariant_applicability
                ),
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

    def _order_records_for_identity(self, records):
        """Prioritize bounded forensic rescue without weakening its proof gate."""

        def priority(indexed_record):
            index, record = indexed_record
            identity = resolve_card_identity(record.enriched).identity
            status = identity_status(identity)
            core_fields = sum(
                bool(value)
                for value in (identity.card_name, identity.set, identity.card_number)
            )
            if status == IDENTITY_INSUFFICIENT and core_fields >= 2:
                rank = 0
            elif status == IDENTITY_AMBIGUOUS:
                rank = 1
            elif status == IDENTITY_INSUFFICIENT:
                rank = 2
            else:
                rank = 3
            return rank, index

        return tuple(
            record
            for _index, record in sorted(
                enumerate(records),
                key=priority,
            )
        )

    def _candidate_from_record(
        self,
        record: _DiscoveryRecord,
        identity_counts: PipelineIdentityAggregate,
        image_counts: PipelineImageAggregate,
        forensic_counts: Optional[PipelineForensicAggregate] = None,
        microvariant_counts: Optional[PipelineMicrovariantAggregate] = None,
    ) -> Tuple[object, bool]:
        self._identity_records_seen += 1
        if record.item_id:
            self._sample_item_ids.add(record.item_id)

        if is_non_physical_pokemon_listing(record.enriched):
            _progress(
                f"identity record {self._identity_records_seen}: early non-physical/digital reject"
            )
            return None, False

        if is_bundle_or_multi_card_listing(record.enriched):
            _progress(
                f"identity record {self._identity_records_seen}: early bundle/multi-card reject"
            )
            return None, False

        initial = resolve_card_identity(
            record.enriched,
        )
        identity = initial.identity
        initial_status = identity_status(identity)
        aspect_audit = identity_aspect_audit(record.enriched)
        identity_counts.unmapped_name_like_aspect_labels += int(
            aspect_audit.unmapped_name_like_label
        )
        identity_counts.unmapped_number_like_aspect_labels += int(
            aspect_audit.unmapped_number_like_label
        )
        source = "eBay structured identity"
        microvariant_applicability = MicrovariantApplicability()
        microvariant = None

        resolved = self.card_catalog_resolver.resolve_identity(identity)
        microvariant_applicability = resolved.microvariant_applicability
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
        visual_eligible = bool(
            raw
            and listing.primary_image_url is not None
            and status_before_visual != IDENTITY_OK
            and self.visual_identity is not None
        )
        visual = None
        if visual_eligible and hasattr(self.visual_identity, "counters"):
            self.visual_identity.counters.forensic_eligible += 1
        if visual_eligible and (
            self._visual_identity_attempts >= self.max_visual_identity_listings
        ):
            if hasattr(self.visual_identity, "counters"):
                self.visual_identity.counters.skipped_run_limit += 1
        elif visual_eligible:
            self._visual_identity_attempts += 1
            _progress(
                f"identity record {self._identity_records_seen}: local visual rescue"
            )
            visual = self.visual_identity.resolve_identity(
                identity,
                listing.image_urls,
                marketplace_id=record.marketplace_id,
                microvariant_applicability=microvariant_applicability,
            )
            if visual.matched:
                identity = visual.identity
                microvariant = visual.microvariant
                source = "VISUAL_POKETRACE"
                _progress(
                    f"identity record {self._identity_records_seen}: visual rescue accepted"
                )

        status = self._count_identity(identity, identity_counts)

        if not raw:
            _progress(f"identity record {self._identity_records_seen}: not eligible")
            return None, False

        forensic_state = _forensic_state(initial_status, status)
        if forensic_counts is not None:
            forensic = forensic_counts.for_state(forensic_state)
            forensic.records += 1

        if status != IDENTITY_OK or listing.primary_image_url is None:
            reason = "ambiguous" if status == IDENTITY_AMBIGUOUS else "raw but unresolved"
            if status == IDENTITY_OK and listing.primary_image_url is None:
                reason = "usable identity but missing front image"
            _progress(f"identity record {self._identity_records_seen}: {reason}")
            if forensic_counts is not None:
                forensic.market_missing += 1
                forensic.economics_deferred += 1

            coords = analyze_coordinates(identity)
            visual_detail = (
                f"attempted=True, matched={visual.matched}, score={visual.score:.3f}, margin={visual.margin:.3f}"
                if visual is not None
                else ("skipped_run_limit" if visual_eligible else "not_attempted")
            )
            tcgdex_detail = f"matched={resolved.matched}, ambiguous={resolved.ambiguous}, source={resolved.source}"
            poketrace_detail = "NO_QUERY"
            f_status = (
                "AMBIGUOUS"
                if status == IDENTITY_AMBIGUOUS
                else ("MISSING_FRONT_IMAGE" if status == IDENTITY_OK else "INSUFFICIENT")
            )
            reason_code, explanation = determine_reason_code(
                f_status,
                identity,
                coords,
                tcgdex_status=tcgdex_detail,
                poketrace_status=poketrace_detail,
                visual_status=visual_detail,
            )
            diag = UnresolvedIdentityDiagnostic(
                record=self._identity_records_seen,
                item_id=record.item_id or listing.item_id,
                title=listing.title if listing else record.title,
                card_name=identity.card_name,
                set_name=identity.set,
                card_number=identity.card_number,
                language=identity.language,
                final_status=f_status,
                coordinates=coords,
                ambiguity_fields=ambiguity_fields(identity),
                tcgdex_detail=tcgdex_detail,
                poketrace_detail=poketrace_detail,
                visual_detail=visual_detail,
                reason_code=reason_code,
                explanation=explanation,
            )
            self.unresolved_diagnostics.append(diag)
            print(diag.format_block())
            return None, True

        if microvariant is None:
            # A structured identity may already be macro-complete even when the
            # first exact set lookup did not prove microvariant applicability.
            # Reuse the deterministic post-macro TCGdex retry before blocking.
            microvariant_applicability = _refresh_post_macro_applicability(
                self.card_catalog_resolver,
                identity,
                microvariant_applicability,
            )
            microvariant = self.microvariant_validator.resolve(
                identity,
                microvariant_applicability,
            )
        if microvariant_counts is not None:
            microvariant_counts.record(microvariant)
        if microvariant.blocks_economics:
            if forensic_counts is not None:
                forensic_counts.for_state(forensic_state).economics_deferred += 1
            _progress(
                f"identity record {self._identity_records_seen}: "
                "microvariant gate blocked before market"
            )
            coords = analyze_coordinates(identity)
            visual_detail = (
                f"attempted=True, matched={visual.matched}, score={visual.score:.3f}, margin={visual.margin:.3f}"
                if visual is not None
                else ("skipped_run_limit" if visual_eligible else "not_attempted")
            )
            tcgdex_detail = f"matched={resolved.matched}, ambiguous={resolved.ambiguous}, source={resolved.source}"
            var_diag = analyze_variant_blocking(
                record=self._identity_records_seen,
                item_id=record.item_id or listing.item_id,
                identity=identity,
                microvariant_applicability=microvariant_applicability,
                microvariant_resolution=microvariant,
            )
            reason_code, explanation = determine_reason_code(
                "BLOCKED_VARIANT",
                identity,
                coords,
                tcgdex_status=tcgdex_detail,
                visual_status=visual_detail,
                microvariant_res=microvariant,
            )
            diag = UnresolvedIdentityDiagnostic(
                record=self._identity_records_seen,
                item_id=record.item_id or listing.item_id,
                title=listing.title if listing else record.title,
                card_name=identity.card_name,
                set_name=identity.set,
                card_number=identity.card_number,
                language=identity.language,
                final_status="BLOCKED_VARIANT",
                coordinates=coords,
                ambiguity_fields=ambiguity_fields(identity),
                tcgdex_detail=tcgdex_detail,
                poketrace_detail="MACRO_RESOLVED",
                visual_detail=visual_detail,
                reason_code=reason_code,
                explanation=explanation,
                variant_diag=var_diag,
            )
            self.unresolved_diagnostics.append(diag)
            print(diag.format_block())
            return None, True

        _progress(
            f"identity record {self._identity_records_seen}: usable via {source}"
        )
        return _PipelineCandidate(
            listing,
            identity,
            back_state,
            record.marketplace_id,
            record.ship_to_ch_eligible,
            forensic_state,
            microvariant,
        ), True

    def _record_market_provenance(
        self,
        candidate: _PipelineCandidate,
        marketplace: MarketplaceAggregate,
    ) -> Tuple[bool, bool, bool]:
        snapshot = self.poketrace_market_source.last_snapshot
        us_values = snapshot.us_values if snapshot is not None else None
        cardmarket = snapshot.cardmarket if snapshot is not None else None
        usable_us = bool(
            us_values is not None
            and str(us_values.currency or "").upper() == "USD"
            and us_values.has_any_value()
        )
        accepted_us = bool(
            usable_us
            and snapshot is not None
            and snapshot.us_record_id is not None
        )
        accepted_eu = bool(
            cardmarket is not None
            and str(cardmarket.currency or "").upper() == "EUR"
            and snapshot is not None
            and snapshot.eu_record_id is not None
        )
        usable_eu = bool(
            accepted_eu
            and (
                cardmarket.robust_reference is not None
                or cardmarket.lowest_active_ask is not None
            )
        )

        marketplace.poketrace_us_usd_accepted += int(accepted_us)
        marketplace.poketrace_eu_eur_accepted += int(accepted_eu)
        marketplace.non_us_with_us_only_snapshot += int(
            candidate.marketplace_id != "EBAY_US"
            and accepted_us
            and not accepted_eu
        )

        if candidate.marketplace_id == "EBAY_US":
            marketplace.us_with_usable_usd_value += int(usable_us)
            marketplace.us_without_usable_usd_value += int(not usable_us)

        if str(candidate.listing.currency or "").upper() == "EUR":
            marketplace.eur_with_usable_eu_value += int(usable_eu)
            marketplace.eur_without_usable_eu_value += int(not usable_eu)
        return (
            usable_us,
            usable_eu,
            bool(cardmarket is not None and cardmarket.status == CARDMARKET_DISCOUNT),
        )

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
