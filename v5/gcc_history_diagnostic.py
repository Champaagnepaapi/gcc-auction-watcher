"""Deterministic GCC History V5 diagnostic using synthetic offline fixtures only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Sequence

from .market_values.gcc_history.models import (
    GCCMarketResult,
    Grader,
    MatchClass,
    ValuationType,
)
from .market_values.gcc_history.provider import (
    GCCHistoryProvider,
    GCCProviderConfig,
    OfflineGCCSource,
)
from .models import CardIdentity


FIXTURE_PATH = (
    Path(__file__).parent
    / "market_values"
    / "gcc_history"
    / "fixtures"
    / "offline_sales.json"
)


@dataclass(frozen=True)
class GCCHistoryDiagnosticSummary:
    enabled: bool
    mode: str
    access_type: str
    provider_queries: int
    cache_hits: int
    records_received: int
    exact_matches: int
    strong_matches: int
    ambiguous_matches: int
    rejected_matches: int
    raw_direct_values: int
    psa9_direct_values: int
    psa10_direct_values: int
    cross_grader_proxies: int
    insufficient_market_data: int
    no_exact_matches: int
    identity_conflicts: int
    duplicates_removed: int
    outliers_flagged: int
    direct_raw_comps: int
    direct_psa9_comps: int
    direct_psa10_comps: int
    pca10_comps: int
    bgs10_comps: int
    cgc10_comps: int
    direct_valuations: int
    valuation_ranges: int
    high_confidence: int
    medium_confidence: int
    low_confidence: int
    ratio_observations: int
    supported_ratio_segments: int
    unsupported_conversions: int
    explainability: Sequence[str]
    live_calls: int = 0


def load_offline_records() -> Sequence[Mapping[str, object]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return tuple(payload["records"])


def diagnostic_targets() -> tuple[CardIdentity, ...]:
    return (
        CardIdentity(
            game="Pokemon",
            card_name="Charizard",
            set="Base Set",
            card_number="4/102",
            year=1999,
            language="English",
            finish="Holo",
            edition="Unlimited",
        ),
        CardIdentity(
            game="Pokemon",
            card_name="Pikachu",
            set="Jungle",
            card_number="60/64",
            year=1999,
            language="English",
            finish="Non Holo",
            edition="Unlimited",
        ),
        CardIdentity(
            game="Pokemon",
            card_name="Venusaur",
            set="Base Set",
            card_number="15/102",
            language="English",
        ),
        CardIdentity(
            game="Pokemon",
            card_name="Mew",
            set="Black Star Promo",
            card_number="8",
            language="English",
        ),
        CardIdentity(
            game="Pokemon",
            card_name="Eevee",
            set="Jungle",
            card_number="51/64",
            year=1999,
            language="English",
        ),
        CardIdentity(
            game="Pokemon",
            card_name="Pidgey",
            set="Base Set",
            card_number="57/102",
            year=1999,
            language="English",
        ),
    )


def _explain(result: GCCMarketResult) -> str:
    values = []
    for label, key in (
        ("RAW", (Grader.RAW, None)),
        ("PSA9", (Grader.PSA, Decimal("9"))),
        ("PSA10", (Grader.PSA, Decimal("10"))),
        ("PCA10", (Grader.PCA, Decimal("10"))),
        ("BGS10", (Grader.BGS, Decimal("10"))),
        ("CGC10", (Grader.CGC, Decimal("10"))),
    ):
        valuation = result.valuations.get(key)
        if valuation is None:
            values.append(f"{label}=ABSENT")
        else:
            values.append(
                f"{label}={valuation.valuation_type.value}/{valuation.confidence.value}"
            )
    return (
        f"identity={result.identity.card_name}|{result.identity.set_name}|"
        f"{result.identity.card_number}; "
        + "; ".join(values)
    )


def run_diagnostic() -> GCCHistoryDiagnosticSummary:
    source = OfflineGCCSource(load_offline_records())
    provider = GCCHistoryProvider(
        GCCProviderConfig(enabled=True),
        source=source,
    )
    results = tuple(provider.market_for(target, "USD") for target in diagnostic_targets())

    def valuation_count(grader: Grader, grade: Decimal | None) -> int:
        return sum(
            result.valuation(grader, grade) is not None
            and result.valuation(grader, grade).valuation_type
            is ValuationType.DIRECT_MARKET_VALUE
            for result in results
        )

    proxies = sum(
        valuation.valuation_type is ValuationType.CROSS_GRADER_PROXY
        for result in results
        for valuation in result.valuations.values()
    )
    insufficient = sum(
        valuation.valuation_type is ValuationType.INSUFFICIENT_MARKET_DATA
        for result in results
        for valuation in result.valuations.values()
    )
    return GCCHistoryDiagnosticSummary(
        enabled=provider.counters.enabled,
        mode=provider.mode,
        access_type="STATIC_SYNTHETIC_FIXTURES / MEMORY_ONLY",
        provider_queries=provider.counters.queries,
        cache_hits=provider.counters.cache_hits,
        records_received=provider.counters.records_received,
        exact_matches=provider.counters.exact_matches,
        strong_matches=provider.counters.strong_matches,
        ambiguous_matches=provider.counters.ambiguous_matches,
        rejected_matches=provider.counters.rejected_matches,
        raw_direct_values=valuation_count(Grader.RAW, None),
        psa9_direct_values=valuation_count(Grader.PSA, Decimal("9")),
        psa10_direct_values=valuation_count(Grader.PSA, Decimal("10")),
        cross_grader_proxies=proxies,
        insufficient_market_data=insufficient,
        no_exact_matches=sum(
            result.match_counts.get(MatchClass.EXACT_MATCH, 0) == 0
            for result in results
        ),
        identity_conflicts=provider.counters.rejected_matches,
        duplicates_removed=provider.counters.duplicates_removed,
        outliers_flagged=provider.counters.outliers_flagged,
        direct_raw_comps=provider.counters.direct_raw_comps,
        direct_psa9_comps=provider.counters.direct_psa9_comps,
        direct_psa10_comps=provider.counters.direct_psa10_comps,
        pca10_comps=provider.counters.pca10_comps,
        bgs10_comps=provider.counters.bgs10_comps,
        cgc10_comps=provider.counters.cgc10_comps,
        direct_valuations=provider.counters.direct_values,
        valuation_ranges=provider.counters.valuation_ranges,
        high_confidence=provider.counters.high_confidence,
        medium_confidence=provider.counters.medium_confidence,
        low_confidence=provider.counters.low_confidence,
        ratio_observations=provider.counters.ratio_observations,
        supported_ratio_segments=provider.counters.supported_ratio_segments,
        unsupported_conversions=provider.counters.unsupported_conversions,
        explainability=tuple(_explain(result) for result in results),
        live_calls=provider.counters.live_calls,
    )


def render_summary(summary: GCCHistoryDiagnosticSummary) -> str:
    lines = [
        "=== V5 GCC HISTORY SUMMARY ===",
        "",
        "GCC History:",
        f"enabled: {str(summary.enabled).lower()}",
        f"mode: {summary.mode}",
        f"access type: {summary.access_type}",
        f"queries: {summary.provider_queries}",
        f"query cache hits: {summary.cache_hits}",
        f"records received: {summary.records_received}",
        "",
        "IDENTITY MATCHING:",
        f"exact matches: {summary.exact_matches}",
        f"strong matches: {summary.strong_matches}",
        f"ambiguous rejected: {summary.ambiguous_matches}",
        f"conflicting rejected: {summary.rejected_matches}",
        "",
        "COMPARABLE SALES:",
        f"raw direct comps: {summary.direct_raw_comps}",
        f"PSA9 direct comps: {summary.direct_psa9_comps}",
        f"PSA10 direct comps: {summary.direct_psa10_comps}",
        f"PCA10 comps: {summary.pca10_comps}",
        f"BGS10 comps: {summary.bgs10_comps}",
        f"CGC10 comps: {summary.cgc10_comps}",
        f"duplicates removed: {summary.duplicates_removed}",
        f"outliers flagged: {summary.outliers_flagged}",
        "",
        "VALUATION:",
        f"direct market values: {summary.direct_valuations}",
        f"direct RAW values found: {summary.raw_direct_values}",
        f"direct PSA9 values found: {summary.psa9_direct_values}",
        f"direct PSA10 values found: {summary.psa10_direct_values}",
        f"cross-grader proxy values: {summary.cross_grader_proxies}",
        f"valuation ranges: {summary.valuation_ranges}",
        f"high confidence: {summary.high_confidence}",
        f"medium confidence: {summary.medium_confidence}",
        f"low confidence: {summary.low_confidence}",
        f"insufficient: {summary.insufficient_market_data}",
        f"NO_EXACT_MATCH: {summary.no_exact_matches}",
        f"IDENTITY_CONFLICT: {summary.identity_conflicts}",
        "",
        "CROSS-GRADER:",
        f"ratio observations: {summary.ratio_observations}",
        f"supported ratio segments: {summary.supported_ratio_segments}",
        f"unsupported conversions rejected: {summary.unsupported_conversions}",
        "",
        "Explainability:",
        *summary.explainability,
        "",
        "SAFETY:",
        "CardGrader calls: 0",
        "Purchases: 0",
        "Bids: 0",
        "Checkout: 0",
        "Persisted eBay records: 0",
        f"Live GCC calls: {summary.live_calls}",
    ]
    return "\n".join(lines)


def main() -> int:
    print(render_summary(run_diagnostic()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
