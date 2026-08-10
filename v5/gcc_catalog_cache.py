from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

import watcher

from .market_values.gcc_history.identity import canonicalize_collectible
from .market_values.gcc_history.models import CanonicalCollectible


GCC_CATALOG_SCHEMA_VERSION = 1
DEFAULT_CATALOG_PATH = Path(
    os.getenv("GCC_CATALOG_INDEX_FILE", "gcc_catalog_index.json")
)


def canonical_from_gcc_lot(lot: watcher.Lot) -> CanonicalCollectible:
    """Build the V5 canonical identity from GCC-only listing/page metadata."""

    parsed = watcher.extract_card_identity(lot)
    core = parsed.get("core") or lot.title
    set_name = lot.card_set or parsed.get("series") or ""
    card_number = lot.card_number or parsed.get("ref") or ""
    return canonicalize_collectible(
        CanonicalCollectible(
            card_name=core or None,
            set_name=set_name or None,
            card_number=card_number or None,
            language=(lot.language or parsed.get("language") or None),
            variant=lot.variant or None,
            year=lot.year,
            set_family=lot.set_family or set_name or None,
            category="pokemon",
        )
    )


@dataclass(frozen=True)
class GCCCatalogCandidate:
    identity: CanonicalCollectible
    lot: watcher.Lot


class GCCCatalogIndex:
    """Persistent cumulative index containing GCC collectible identity only.

    It intentionally stores no eBay identifier, listing URL/title/price, seller,
    image, aspects or API payload. The only URL stored is the GCC item page used
    as a future representative for GCC sales-history lookup.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_CATALOG_PATH
        self._items: dict[str, dict[str, object]] = {}
        self._by_name: dict[str, list[str]] = {}
        self.entries_loaded = 0
        self.added_this_run = 0
        self.updated_this_run = 0
        self.lookup_hits = 0
        self.load_failures = 0
        self.save_failures = 0
        self._dirty = False
        self._load()

    @property
    def current_entries(self) -> int:
        return len(self._items)

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, Mapping):
                raise ValueError("catalog root is not an object")
            if raw.get("schema_version") != GCC_CATALOG_SCHEMA_VERSION:
                raise ValueError("unsupported catalog schema")
            items = raw.get("items")
            if not isinstance(items, Mapping):
                raise ValueError("catalog items are not an object")
            for url, entry in items.items():
                if not isinstance(url, str) or not isinstance(entry, Mapping):
                    continue
                normalized = dict(entry)
                normalized["url"] = url
                identity = self._identity_from_entry(normalized)
                if not identity.card_name or not (
                    identity.card_number or identity.set_name
                ):
                    continue
                self._items[url] = normalized
            self.entries_loaded = len(self._items)
            self._rebuild_name_index()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.load_failures += 1
            self._items = {}
            self._by_name = {}

    def _rebuild_name_index(self) -> None:
        by_name: dict[str, list[str]] = {}
        for url, entry in self._items.items():
            identity = self._identity_from_entry(entry)
            if identity.card_name:
                by_name.setdefault(identity.card_name, []).append(url)
        self._by_name = by_name

    @staticmethod
    def _identity_from_entry(entry: Mapping[str, object]) -> CanonicalCollectible:
        year = entry.get("year")
        if not isinstance(year, int):
            year = None
        return canonicalize_collectible(
            CanonicalCollectible(
                card_name=str(entry.get("card_name") or "") or None,
                set_name=str(entry.get("set_name") or "") or None,
                card_number=str(entry.get("card_number") or "") or None,
                language=str(entry.get("language") or "") or None,
                variant=str(entry.get("variant") or "") or None,
                year=year,
                set_family=str(entry.get("set_family") or "") or None,
                category="pokemon",
            )
        )

    @staticmethod
    def _lot_from_entry(entry: Mapping[str, object]) -> watcher.Lot:
        return watcher.Lot(
            url=str(entry.get("url") or ""),
            title=str(entry.get("card_name") or ""),
            current_price=None,
            source_type="catalog_cache",
            grader=str(entry.get("grader") or ""),
            grade=(
                str(entry.get("grade"))
                if entry.get("grade") is not None
                else None
            ),
            card_set=str(entry.get("set_name") or ""),
            card_number=str(entry.get("card_number") or ""),
            language=str(entry.get("language") or ""),
            year=(
                entry.get("year")
                if isinstance(entry.get("year"), int)
                else None
            ),
            variant=str(entry.get("variant") or ""),
            set_family=str(entry.get("set_family") or ""),
        )

    def candidates(self, card_name: str | None) -> tuple[GCCCatalogCandidate, ...]:
        name = canonicalize_collectible(
            CanonicalCollectible(card_name=card_name, category="pokemon")
        ).card_name
        if not name:
            return ()
        urls = self._by_name.get(name, ())
        if urls:
            self.lookup_hits += 1
        result = []
        for url in urls:
            entry = self._items.get(url)
            if not isinstance(entry, Mapping):
                continue
            result.append(
                GCCCatalogCandidate(
                    identity=self._identity_from_entry(entry),
                    lot=self._lot_from_entry(entry),
                )
            )
        return tuple(result)

    def upsert(
        self,
        identity: CanonicalCollectible,
        lot: watcher.Lot,
        *,
        source: str,
        seen_at: Optional[datetime] = None,
    ) -> bool:
        identity = canonicalize_collectible(identity)
        url = (lot.url or "").strip()
        if not url or not identity.card_name or not (
            identity.card_number or identity.set_name
        ):
            return False

        now = (seen_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        timestamp = now.isoformat()
        previous = self._items.get(url)
        previous_name = (
            self._identity_from_entry(previous).card_name
            if isinstance(previous, Mapping)
            else None
        )
        first_seen = (
            str(previous.get("first_seen"))
            if isinstance(previous, Mapping) and previous.get("first_seen")
            else timestamp
        )
        sources = []
        if isinstance(previous, Mapping):
            raw_sources = previous.get("sources")
            if isinstance(raw_sources, Sequence) and not isinstance(
                raw_sources, str
            ):
                sources.extend(str(value) for value in raw_sources if value)
        if source and source not in sources:
            sources.append(source)

        entry: dict[str, object] = {
            "url": url,
            "card_name": identity.card_name,
            "set_name": identity.set_name,
            "card_number": identity.card_number,
            "language": identity.language,
            "variant": identity.variant,
            "year": identity.year,
            "set_family": identity.set_family,
            "grader": (lot.grader or "").strip().upper() or None,
            "grade": str(lot.grade).strip() if lot.grade is not None else None,
            "sources": sources,
            "first_seen": first_seen,
            "last_seen": timestamp,
        }

        if previous is None:
            self.added_this_run += 1
        else:
            comparable_previous = dict(previous)
            comparable_previous.pop("last_seen", None)
            comparable_entry = dict(entry)
            comparable_entry.pop("last_seen", None)
            if comparable_previous != comparable_entry:
                self.updated_this_run += 1

        self._items[url] = entry
        if previous_name and previous_name != identity.card_name:
            old_bucket = self._by_name.get(previous_name, [])
            if url in old_bucket:
                old_bucket.remove(url)
            if not old_bucket:
                self._by_name.pop(previous_name, None)
        bucket = self._by_name.setdefault(identity.card_name, [])
        if url not in bucket:
            bucket.append(url)
        self._dirty = True
        return True

    def add_lots(
        self,
        lots: Iterable[watcher.Lot],
        *,
        source: str,
        identity_builder: Callable[
            [watcher.Lot], CanonicalCollectible
        ] = canonical_from_gcc_lot,
    ) -> int:
        accepted = 0
        for lot in lots:
            if self.upsert(identity_builder(lot), lot, source=source):
                accepted += 1
        return accepted

    def save(self) -> None:
        if not self._dirty and self.path.exists():
            return
        payload = {
            "schema_version": GCC_CATALOG_SCHEMA_VERSION,
            "items": self._items,
        }
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(self.path)
            self._dirty = False
        except OSError:
            self.save_failures += 1
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def refresh_catalog_from_public_inventory(
    *,
    path: Path | str | None = None,
) -> GCCCatalogIndex:
    index = GCCCatalogIndex(path)
    diagnostics = watcher.RunDiagnostics()
    lots = watcher.collect_fixed_lots_from_api(
        diagnostics,
        min_price=0.0,
        max_price=None,
    )
    index.add_lots(lots, source="on_sale")
    index.save()
    print("=== V5 GCC CATALOG REFRESH ===")
    print(f"inventory pages requested: {diagnostics.fixed_coverage.pages_requested}")
    print(f"GCC entries loaded: {index.entries_loaded}")
    print(f"GCC entries current: {index.current_entries}")
    print(f"GCC entries added this run: {index.added_this_run}")
    print(f"GCC entries updated this run: {index.updated_this_run}")
    print(f"catalog load failures: {index.load_failures}")
    print(f"catalog save failures: {index.save_failures}")
    print("Persisted eBay records: 0")
    return index


if __name__ == "__main__":
    refresh_catalog_from_public_inventory()
