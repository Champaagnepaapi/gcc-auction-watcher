"""Failure-isolated orchestration for collector, normalization, and storage."""

from __future__ import annotations

from typing import Callable, Mapping, Optional, Sequence

from .models import (
    CollectionResult,
    NormalizedObservation,
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
                Callable[[RawSourceRecord], Sequence[NormalizedObservation]],
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

        for record in result.records:
            try:
                normalizer = self.normalizers[record.source_code]
                observations = normalizer(record)
                self.persistence.ingest(record, observations, self.diagnostics)
                if not observations:
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
