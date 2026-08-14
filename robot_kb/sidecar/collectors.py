"""Read-only collectors for GCC inventory and TCGdex card payloads."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import quote

import requests

from .models import CollectionResult, RawSourceRecord


GCC_ON_SALE_ITEMS_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
TCGDEX_BASE_URL = "https://api.tcgdex.net/v2"


class SourceCollectionError(RuntimeError):
    """A source failed without affecting any other source batch."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _payload_from_response(response: Any) -> Any:
    response.raise_for_status()
    return response.json()


def _record_id(row: Mapping[str, Any]) -> Optional[str]:
    value = row.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _source_updated_at(row: Mapping[str, Any]) -> Optional[str]:
    value = row.get("updatedAt") or row.get("sourceUpdatedAt")
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return text


class GCCMarketplaceCollector:
    """Collect the same public inventory shapes used by GCC's web client.

    This collector has no price/opportunity filters. It only retrieves source
    rows. It never imports or calls V4 decision code.
    """

    def __init__(
        self,
        *,
        http_get: Optional[Callable[..., Any]] = None,
        timeout_seconds: float = 15.0,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.http_get = http_get or requests.get
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def collect(
        self,
        mode: str,
        *,
        page_size: int = 100,
        max_pages: int = 500,
    ) -> CollectionResult:
        normalized_mode = mode.strip().lower()
        if normalized_mode not in {"fixed", "auction"}:
            raise ValueError("GCC mode must be 'fixed' or 'auction'")
        if page_size <= 0 or max_pages <= 0:
            raise ValueError("GCC page_size and max_pages must be positive")

        records = []
        rejected = 0
        page = 1
        seen_ids: set[str] = set()
        for _ in range(max_pages):
            params: dict[str, Any] = {
                "page": page,
                "limit": page_size,
                "includeCounts": "true" if page == 1 else "false",
            }
            if normalized_mode == "fixed":
                params.update(
                    {
                        "sellingTypes": "FIXED_PRICE",
                        "categories": "Pokemon",
                        "itemTypes": "CARDS",
                    }
                )
            else:
                params.update(
                    {
                        "sellingTypeGroup": "AUCTION",
                        "sortType": "ENDING_SOON",
                        "status": "ON_SALE",
                        "includeSavedSearchMatch": "true",
                    }
                )
            try:
                response = self.http_get(
                    GCC_ON_SALE_ITEMS_API_URL,
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "x-device-platform": "web",
                    },
                    timeout=self.timeout_seconds,
                )
                payload = _payload_from_response(response)
            except Exception as error:
                raise SourceCollectionError(
                    f"GCC {normalized_mode} page {page} failed"
                ) from error

            if not isinstance(payload, Mapping):
                raise SourceCollectionError(
                    f"GCC {normalized_mode} page {page} is not an object"
                )
            info = payload.get("info")
            results = payload.get("results")
            if not isinstance(info, Mapping) or not isinstance(results, list):
                raise SourceCollectionError(
                    f"GCC {normalized_mode} page {page} lacks info/results"
                )
            if info.get("currentPage") != page:
                raise SourceCollectionError(
                    f"GCC {normalized_mode} pagination did not advance"
                )

            retrieved_at = self.clock()
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
                raise SourceCollectionError(
                    f"GCC {normalized_mode} page {page} made no progress"
                )

            next_page = info.get("nextPage")
            if next_page is None:
                break
            if (
                not isinstance(next_page, int)
                or isinstance(next_page, bool)
                or next_page <= page
            ):
                raise SourceCollectionError(
                    f"GCC {normalized_mode} nextPage is invalid"
                )
            page = next_page
        else:
            raise SourceCollectionError(
                f"GCC {normalized_mode} reached the {max_pages}-page safety limit"
            )
        return CollectionResult(tuple(records), rejected)


class TCGdexCollector:
    """Fetch one TCGdex card response; pricing normalization is separate."""

    def __init__(
        self,
        *,
        http_get: Optional[Callable[..., Any]] = None,
        timeout_seconds: float = 10.0,
        clock: Callable[[], str] = utc_now,
    ) -> None:
        self.http_get = http_get or requests.get
        self.timeout_seconds = timeout_seconds
        self.clock = clock

    def collect_card(self, language_code: str, card_id: str) -> CollectionResult:
        if not language_code.strip() or not card_id.strip():
            raise ValueError("TCGdex language and card ID are required")
        url = (
            f"{TCGDEX_BASE_URL}/{quote(language_code.strip(), safe='')}/cards/"
            f"{quote(card_id.strip(), safe='')}"
        )
        try:
            response = self.http_get(
                url,
                headers={"Accept": "application/json"},
                timeout=self.timeout_seconds,
            )
            payload = _payload_from_response(response)
        except Exception as error:
            raise SourceCollectionError(f"TCGdex card request failed: {card_id}") from error
        if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
            payload = payload["data"]
        if not isinstance(payload, Mapping):
            raise SourceCollectionError("TCGdex card response is not an object")
        returned_id = _record_id(payload)
        if returned_id is None:
            raise SourceCollectionError("TCGdex card response has no stable returned ID")
        return CollectionResult(
            (
                RawSourceRecord(
                    source_code="tcgdex",
                    source_name="TCGdex",
                    source_role="PROVIDER",
                    source_native_record_id=returned_id,
                    payload=dict(payload),
                    retrieved_at=self.clock(),
                    object_type="CARD",
                    external_native_id=returned_id,
                ),
            )
        )


def load_gcc_fixture(path: Path, *, retrieved_at: str) -> CollectionResult:
    """Load a replay file containing a GCC page, row, or row list."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("results"), list):
        rows: Sequence[Any] = payload["results"]
    elif isinstance(payload, list):
        rows = payload
    else:
        rows = (payload,)
    records = []
    rejected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        native_id = _record_id(row)
        if native_id is None:
            rejected += 1
            continue
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
    return CollectionResult(tuple(records), rejected)


def load_tcgdex_fixture(path: Path, *, retrieved_at: str) -> CollectionResult:
    """Load one or more TCGdex card responses for deterministic replay."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, Mapping) and isinstance(payload.get("data"), Mapping):
        payload = payload["data"]
    rows: Sequence[Any] = payload if isinstance(payload, list) else (payload,)
    records = []
    rejected = 0
    for row in rows:
        if not isinstance(row, Mapping):
            rejected += 1
            continue
        native_id = _record_id(row)
        if native_id is None:
            rejected += 1
            continue
        records.append(
            RawSourceRecord(
                source_code="tcgdex",
                source_name="TCGdex",
                source_role="PROVIDER",
                source_native_record_id=native_id,
                payload=dict(row),
                retrieved_at=retrieved_at,
                object_type="CARD",
                external_native_id=native_id,
            )
        )
    return CollectionResult(tuple(records), rejected)
