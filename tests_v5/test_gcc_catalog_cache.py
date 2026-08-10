from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import watcher

from v5.gcc_catalog_cache import GCCCatalogIndex
from v5.market_values.gcc_history.models import CanonicalCollectible


class GCCCatalogIndexTests(unittest.TestCase):
    def _lot(self, url: str = "https://gradedcardcenter.com/item/abc") -> watcher.Lot:
        return watcher.Lot(
            url=url,
            title="PSA 10 Charizard",
            current_price=500.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Base Set",
            card_number="4/102",
            language="English",
            year=1999,
            set_family="Base Set",
        )

    def _identity(self) -> CanonicalCollectible:
        return CanonicalCollectible(
            card_name="Charizard",
            set_name="Base Set",
            card_number="4/102",
            language="English",
            year=1999,
            set_family="Base Set",
            category="pokemon",
        )

    def test_round_trip_keeps_only_gcc_identity_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            index = GCCCatalogIndex(path)
            index.upsert(
                self._identity(),
                self._lot(),
                source="on_sale",
                seen_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
            )
            index.save()

            payload = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload).casefold()
            for forbidden in (
                "ebay",
                "seller",
                "image",
                "listing_price",
                "itemid",
                "localizedaspects",
            ):
                self.assertNotIn(forbidden, serialized)

            restored = GCCCatalogIndex(path)
            candidates = restored.candidates("Charizard")
            self.assertEqual(restored.entries_loaded, 1)
            self.assertEqual(restored.current_entries, 1)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].identity.card_number, "4/102")
            self.assertEqual(candidates[0].lot.url, self._lot().url)
            self.assertIsNone(candidates[0].lot.current_price)

    def test_absent_card_is_not_deleted_on_next_refresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            index = GCCCatalogIndex(path)
            index.upsert(self._identity(), self._lot(), source="on_sale")
            index.save()

            # A later refresh that simply does not see the old card must not
            # erase it: this is the cumulative behaviour we want.
            later = GCCCatalogIndex(path)
            later.save()
            final = GCCCatalogIndex(path)
            self.assertEqual(final.current_entries, 1)
            self.assertEqual(len(final.candidates("Charizard")), 1)

    def test_completed_sales_source_enriches_existing_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.json"
            index = GCCCatalogIndex(path)
            index.upsert(self._identity(), self._lot(), source="on_sale")
            index.upsert(self._identity(), self._lot(), source="completed_sales")
            index.save()
            raw = json.loads(path.read_text(encoding="utf-8"))
            entry = raw["items"][self._lot().url]
            self.assertEqual(entry["sources"], ["on_sale", "completed_sales"])
            self.assertEqual(index.current_entries, 1)


if __name__ == "__main__":
    unittest.main()
