"""Production COMC discovery with browser-boundary fixtures, no GCC catalog."""
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

import v4_global_marketplace_scan as scan

URL = "https://www.comc.com/Cards/Pokemon/2023/Pokemon_151/183/Mewtwo/23600000/Graded/PSA/10"
CELLS = ["2023 Pokemon Scarlet & Violet - 151 [sv2a] - [Base] - Japanese", "183", "Art Rare - Mewtwo [PSA 10 GEM MT]", "Get SRP", "$80", "Get SRP", "1"]


class Page:
    def __init__(self, cells=None, status=200):
        self.cells, self.status = list(CELLS if cells is None else cells), status
        self.calls = []
    def goto(self, url, **kwargs):
        self.url = url
        self.calls.append(url)
        return SimpleNamespace(status=self.status)
    def wait_for_timeout(self, ms): pass
    def evaluate(self, script):
        return [{"cells": self.cells, "hrefs": [URL]}] if self.cells else []
    def locator(self, selector): return self
    def inner_text(self, **kwargs): return "All Sellers\n$80.00\nBuy Now\n"


class ComcNativeTests(unittest.TestCase):
    def scan(self, page):
        return scan.scan_comc_inventory(page, (), observed_at=datetime.now(timezone.utc), max_pages=1)

    def test_catalog_free_exact_public_row_reaches_evaluation(self):
        rows, status = self.scan(Page())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identity.name, "Mewtwo")
        self.assertEqual(rows[0].identity.set_name, "151")
        self.assertEqual(rows[0].identity.number, "183/165")
        self.assertIn("Art Rare", rows[0].identity.variant)
        self.assertIsNone(rows[0].all_in_eur({"USD": 1}))
        self.assertFalse(status.complete)

    def test_contradictory_reviewed_set_code_is_rejected(self):
        cells = CELLS.copy(); cells[0] = cells[0].replace('sv2a', 'SV8a')
        rows, _ = self.scan(Page(cells))
        self.assertEqual(rows, [])

    def test_language_and_psa_proof_are_required(self):
        for i, value in ((0, CELLS[0].replace('Japanese', '')), (2, 'Mewtwo [Near Mint]'), (2, 'Mewtwo [PSA 9 MINT]')):
            cells = CELLS.copy(); cells[i] = value
            self.assertEqual(self.scan(Page(cells))[0], [])

    def test_provider_error_and_unproven_empty_never_complete(self):
        for page in (Page(status=403), Page([])):
            rows, status = self.scan(page)
            self.assertEqual(rows, [])
            self.assertFalse(status.complete)

    def test_bundle_and_material_conflicts_are_rejected(self):
        for name in ('Mewtwo Lot of 2 [PSA 10 GEM MT]', 'Mewtwo Master Ball Poke Ball [PSA 10 GEM MT]'):
            cells = CELLS.copy(); cells[2] = name
            self.assertEqual(self.scan(Page(cells))[0], [])


if __name__ == '__main__': unittest.main()
