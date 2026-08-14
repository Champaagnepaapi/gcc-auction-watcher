"""Failure-isolated orchestration for collector, normalization, and storage."""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from .models import (
    CollectionResult,
    NormalizationBatch,
    RawSourceRecord,
    ShadowDiagnostics,
)
from .normalizers import normalize_gcc, normalize_tcgdex
from .persistence import ShadowKnowledgePersistence


class ShadowSidecar:
    """Run independent shadow source jobs; failures never escape to V4."""

    def __init__(
        self,
        persistence: ShadowKnowledgePersistence,
        *,
        normalizers: Optional[
            Mapping[
                str,
                Callable[[RawSourceRecord], NormalizationBatch],
            ]
        ] = None,
    ) -> None:
        self.persistence = persistence
        self.normalizers = dict(
            normalizers
            or {
                "gcc": normalize_gcc,
                "tcgdex": normalize_tcgdex,
            }
        )
        self.diagnostics = ShadowDiagnostics()

    def run_source(
        self,
        source_name: str,
        collect: Callable[[], CollectionResult],
    ) -> None:
        """Run one source boundary and continue after any source-local error."""

        try:
            result = collect()
        except Exception as error:
            self.diagnostics.record_failure(source_name, error)
            return
        self.diagnostics.rejected_malformed_records += (
            result.rejected_malformed_records
        )
        self.diagnostics.source_records_fetched += len(result.records)
        if result.crawl_truncated:
            self.diagnostics.crawl_batches_truncated += 1

        for record in result.records:
            try:
                normalizer = self.normalizers[record.source_code]
                batch = normalizer(record)
                self.persistence.ingest(
                    record, batch.observations, self.diagnostics
                )
                self.diagnostics.sale_candidates_rejected += (
                    batch.sale_candidates_rejected
                )
                self.diagnostics.ambiguous_sale_records += (
                    batch.ambiguous_sale_records
                )
                self.diagnostics.metric_alias_conflicts += (
                    batch.metric_alias_conflicts
                )
                self.diagnostics.monetary_facts_rejected += (
                    batch.monetary_facts_rejected
                )
                if batch.rejected_record:
                    self.diagnostics.rejected_malformed_records += 1
            except Exception as error:
                self.diagnostics.record_failure(source_name, error)

    def run_sources(
        self,
        jobs: Sequence[tuple[str, Callable[[], CollectionResult]]],
    ) -> ShadowDiagnostics:
        for source_name, collect in jobs:
            self.run_source(source_name, collect)
        return self.diagnostics
