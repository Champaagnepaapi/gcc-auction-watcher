from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

import watcher

from .market_values.gcc_history.identity import canonicalize_collectible
from .market_values.gcc_history.models import CanonicalCollectible


GCC_CATALOG_SCHEMA_VERSION = 1
DEFAULT_GCC_CATALOG_FILE = "gcc_catalog_index.json"


@dataclass(frozen=True)
class GCCCatalogCandidate:
    identity: CanonicalCollectible
    lot: watcher.Lot


class GCCCatalogIndex:
    """Cumulative GCC-only identity lookup cache.

    The file stores only public GCC identity metadata and GCC item URLs. It is
    intentionally unable to store eBay ids, titles, prices, sellers or images.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(
            path
            or os.getenv("GCC_CATALOG_INDEX_FILE", DEFAULT_GCC_CATALOG_FILE)
        )
        self._items: dict[str, dict[str, object]] = {}
        self._by_name: dict[str, list[str]] = {}
        self.entries_loaded = 0
        self.added_this_run = 0
        self.updated_this_run = 0
        self.lookup_hits = 0
        self.load_failures = 0
        self.save_failures = 0
        self._load()

    @property
    def current_entries(self) -> int:
        return len(self._items)

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, Mapping):
                raise ValueError("invalid catalog root")
            if payload.get("schema_version") != GCC_CATALOG_SCHEMA_VERSION:
                raise ValueError("unsupported catalog schema")
            raw_items = payload.get("items")
            if not isinstance(raw_items, list):
                raise ValueError("invalid catalog items")
            for raw in raw_items:
                if not isinstance(raw, Mapping):
                    continue
                url = str(raw.get("url") or "").strip()
                card_name = str(raw.get("card_name") or "").strip()
                if not url or not card_name:
                    continue
                entry = self._safe_entry(raw)
                self._items[url] = entry
            self.entries_loaded = len(self._items)
            self._reindex()
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            self.load_failures += 1
            self._items = {}
            self._by_name = {}

    @staticmethod
    def _safe_entry(raw: Mapping[str, object]) -> dict[str, object]:
        year = raw.get("year")
        return {
            "url": str(raw.get("url") or "").strip(),
            "card_name": str(raw.get("card_name") or "").strip(),
            "set_name": str(raw.get("set_name") or "").strip(),
            "card_number": str(raw.get("card_number") or "").strip(),
            "language": str(raw.get("language") or "").strip(),
            "variant": str(raw.get("variant") or "").strip(),
            "year": year if isinstance(year, int) else None,
            "set_family": str(raw.get("set_family") or "").strip(),
            "grader": str(raw.get("grader") or "").strip(),
            "grade": (
                str(raw.get("grade")) if raw.get("grade") is not None else None
            ),
            "source": str(raw.get("source") or "").strip(),
            "last_seen_at": str(raw.get("last_seen_at") or "").strip(),
        }

    def _reindex(self) -> None:
        by_name: dict[str, list[str]] = {}
        for url, entry in self._items.items():
            identity = self._identity_from_entry(entry)
            if not identity.card_name:
                continue
            by_name.setdefault(identity.card_name, []).append(url)
        self._by_name = by_name

    @staticmethod
    def _identity_from_entry(entry: Mapping[str, object]) -> CanonicalCollectible:
        year = entry.get("year")
        return canonicalize_collectible(
            CanonicalCollectible(
                card_name=str(entry.get("card_name") or "") or None,
                set_name=str(entry.get("set_name") or "") or None,
                card_number=str(entry.get("card_number") or "") or None,
                language=str(entry.get("language") or "") or None,
                variant=str(entry.get("variant") or "") or None,
                year=year if isinstance(year, int) else None,
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
        # This lookup intentionally starts from card name only. The strict
        # set/number/language/variant matcher is applied to returned candidates.
        # CanonicalCollectible requires explicit set/number fields even when
        # absent, so keep them as None rather than constructing an invalid key.
        name = canonicalize_collectible(
            CanonicalCollectible(
                card_name=card_name,
                set_name=None,
                card_number=None,
                category="pokemon",
            )
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
        timestamp = (seen_at or datetime.now(timezone.utc)).isoformat()
        entry = {
            "url": url,
            "card_name": identity.card_name or "",
            "set_name": identity.set_name or "",
            "card_number": identity.card_number or "",
            "language": identity.language or "",
            "variant": identity.variant or "",
            "year": identity.year,
            "set_family": identity.set_family or "",
            "grader": lot.grader or "",
            "grade": lot.grade,
            "source": source,
            "last_seen_at": timestamp,
        }
        previous = self._items.get(url)
        if previous is None:
            self.added_this_run += 1
        elif previous != entry:
            self.updated_this_run += 1
        else:
            return False
        self._items[url] = entry
        self._reindex()
        return True

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema_version": GCC_CATALOG_SCHEMA_VERSION,
                "items": [self._items[key] for key in sorted(self._items)],
            }
            temp = self.path.with_suffix(self.path.suffix + ".tmp")
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            self.save_failures += 1
