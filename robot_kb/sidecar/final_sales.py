"""Read-only GCC completed-sale collection for Robot KB.

This module only retrieves rows explicitly returned by GCC under status=SOLD.
It does not infer that an ended auction sold. The existing GCC normalizer remains
responsible for requiring an explicit final sale price + sale timestamp before a
SALE_TRANSACTION can be persisted.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from .collectors import (
    GCC_MAX_PAGES,
    GCC_MAX_PAGE_SIZE,
    GCC_MAX_RECORDS,
    GCCMarketplaceCollector,
    SourceCollectionError,
    _record_id,
    _source_updated_at,
)
from .models import CollectionResult, RawSourceRecord


class GCCCompletedSalesCollector:
    """Collect recent GCC auction rows from the explicit SOLD source scope."""

    def __init__(self, collector: Optional[GCCMarketplaceCollector] = None) -> None:
        self.collector = collector or GCCMarketplaceCollector()

    def collect(
        self,
        *,
        page_size: int = 50,
        max_pages: int = 10,
        max_records: int = 500,
    ) -> CollectionResult:
        for name, value, ceiling in (
            ("page_size", page_size, GCC_MAX_PAGE_SIZE),
            ("max_pages", max_pages, GCC_MAX_PAGES),
            ("max_records", max_records, GCC_MAX_RECORDS),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not 1 <= value <= ceiling
            ):
                raise ValueError(f"GCC SOLD {name} must be between 1 and {ceiling}")

        records: list[RawSourceRecord] = []
        rejected = 0
        seen_ids: set[str] = set()
        page = 1

        for _ in range(max_pages):
            params: dict[str, Any] = {
                "sellingTypeGroup": "AUCTION",
                "status": "SOLD",
                "page": page,
                "limit": page_size,
                "includeCounts": "true" if page == 1 else "false",
            }
            try:
                payload = self.collector._request_page(params)
            except Exception as error:
                raise SourceCollectionError(
                    f"GCC SOLD page {page} failed"
                ) from error

            if not isinstance(payload, Mapping):
                raise SourceCollectionError(f"GCC SOLD page {page} is not an object")
            info = payload.get("info")
            results = payload.get("results")
            if not isinstance(info, Mapping) or not isinstance(results, list):
                raise SourceCollectionError(f"GCC SOLD page {page} lacks info/results")
            if info.get("currentPage") != page:
                raise SourceCollectionError("GCC SOLD pagination did not advance")

            retrieved_at = self.collector.clock()
            new_ids = 0
            for row in results:
                if not isinstance(row, Mapping):
                    rejected += 1
                    continue
                native_id = _record_id(row)
                if native_id is None:
                    rejected += 1
                    continue
                if native_id in seen_ids:
                    continue
                if len(records) >= max_records:
                    return CollectionResult(tuple(records), rejected, True)
                seen_ids.add(native_id)
                new_ids += 1
                records.append(
                    RawSourceRecord(
                        source_code="gcc",
                        source_name="GCC Marketplace",
                        source_role="LISTING_PLATFORM",
                        source_native_record_id=native_id,
                        payload=dict(row),
                        retrieved_at=retrieved_at,
                        source_updated_at=_source_updated_at(row),
                        object_type="LISTING",
                        external_native_id=native_id,
                    )
                )

            if results and new_ids == 0:
                raise SourceCollectionError(f"GCC SOLD page {page} made no progress")

            next_page = info.get("nextPage")
            if next_page is None:
                return CollectionResult(tuple(records), rejected)
            if len(records) >= max_records:
                return CollectionResult(tuple(records), rejected, True)
            if (
                not isinstance(next_page, int)
                or isinstance(next_page, bool)
                or next_page <= page
            ):
                raise SourceCollectionError("GCC SOLD nextPage is invalid")
            page = next_page

        return CollectionResult(tuple(records), rejected, True)
