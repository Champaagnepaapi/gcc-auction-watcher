from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import watcher
import v4_exact_active_ask_position as active


class ExactActiveAskTests(unittest.TestCase):
    def lot(self, **overrides):
        values = dict(
            url="https://gradedcardcenter.com/item/test-active-ask",
            title="Celebi VMAX",
            current_price=70.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_set="Jet-Black Spirit",
            card_number="084/070",
            language="Japanese",
            year=2021,
            variant="Holo",
            commercial_dimensions={},
            body="",
            sale_name="",
            end_text="",
            minutes_to_end=None,
            listing_text="",
            page_title_raw="",
            inspection_error="",
            set_family="",
        )
        values.update(overrides)
        return watcher.Lot(**values)

    def test_active_search_is_bin_and_never_sold_completed(self):
        url = active.build_ebay_active_url(self.lot())
        self.assertIn("LH_BIN=1", url)
        self.assertNotIn("LH_Sold", url)
        self.assertNotIn("LH_Complete", url)

    def test_grade_parser_requires_explicit_grader_and_grade(self):
        self.assertEqual(active._grader_grade_from_text("PSA 10 Celebi VMAX"), ("PSA", 10.0))
        self.assertEqual(active._grader_grade_from_text("PCA 9.5 Celebi"), ("PCA", 9.5))
        self.assertEqual(active._grader_grade_from_text("Celebi VMAX raw"), ("", None))

    def test_exact_candidate_uses_existing_strict_external_gate(self):
        lot = self.lot()
        with patch.object(watcher, "ebay_result_match_score", return_value=(100, "exact")), patch.object(
            watcher, "external_comparable_is_exact", return_value=True
        ) as gate:
            self.assertTrue(active._exact_active_ask_candidate(lot, "Celebi PSA 10 084/070", "Japanese Holo"))
        comparable = gate.call_args.args[1]
        self.assertEqual(comparable.source, "ebay")
        self.assertEqual(comparable.grader, "PSA")
        self.assertEqual(comparable.grade, 10.0)
        self.assertIsNone(comparable.sold_at)

    def test_ask_block_explicitly_says_not_a_sale(self):
        lot = self.lot()
        op = SimpleNamespace(lot=lot, exact_active_ask=active.ActiveAskEvidence(
            source="eBay BIN",
            price=90.0,
            url="https://www.ebay.fr/itm/123",
            title="Celebi PSA 10",
            gap_pct=22.2,
            gcc_is_cheapest=True,
        ))
        text = active._ask_block(op)
        self.assertIn("ASK, PAS UNE VENTE", text)
        self.assertIn("22.2%", text)

    def test_process_wrapper_never_creates_opportunity_from_ask(self):
        existing = []
        active._ORIGINAL_PROCESS = lambda *args, **kwargs: existing
        with patch.object(active, "_enabled", return_value=True):
            result = active._process_with_active_ask(None, [], {}, None, None, None)
        self.assertIs(result, existing)
        self.assertEqual(result, [])

    def test_only_final_fixed_opportunities_consume_active_ask_budget(self):
        fixed_a = SimpleNamespace(lot=self.lot(url="fixed-a"), discount_pct=50.0)
        fixed_b = SimpleNamespace(lot=self.lot(url="fixed-b"), discount_pct=40.0)
        fixed_c = SimpleNamespace(lot=self.lot(url="fixed-c"), discount_pct=30.0)
        auction = SimpleNamespace(lot=self.lot(url="auction", source_type="auction"), discount_pct=99.0)
        opportunities = [fixed_c, auction, fixed_b, fixed_a]
        active._ORIGINAL_PROCESS = lambda *args, **kwargs: opportunities
        seen = []
        with patch.object(active, "_enabled", return_value=True), patch.object(active, "_max_cards", return_value=2), patch.object(
            active, "scrape_lowest_exact_ebay_ask", side_effect=lambda page, lot: seen.append(lot.url) or None
        ):
            result = active._process_with_active_ask(None, [], {}, None, None, None)
        self.assertIs(result, opportunities)
        self.assertEqual(seen, ["fixed-a", "fixed-b"])
        self.assertNotIn("auction", seen)

    def test_positive_ask_cache_is_reused_by_exact_commercial_identity(self):
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        state = {}
        first = self.lot(url="fixed-a", current_price=70.0)
        second = self.lot(url="fixed-b", current_price=60.0)
        evidence = active.ActiveAskEvidence(
            source="eBay BIN",
            price=100.0,
            url="https://www.ebay.fr/itm/123",
            title="Celebi VMAX PSA 10",
            gap_pct=30.0,
            gcc_is_cheapest=True,
        )
        active._store_active_ask(state, first, evidence, now)
        cached = active._cached_active_ask(state, second, now + timedelta(minutes=10))
        self.assertIsNotNone(cached)
        self.assertEqual(cached.price, 100.0)
        # Recomputed for the second GCC listing, not copied from the first one.
        self.assertEqual(cached.gap_pct, 40.0)

    def test_active_ask_cache_separates_grade_and_language(self):
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        state = {}
        original = self.lot()
        evidence = active.ActiveAskEvidence(
            source="eBay BIN", price=100.0, url="u", title="t",
            gap_pct=30.0, gcc_is_cheapest=True,
        )
        active._store_active_ask(state, original, evidence, now)
        self.assertIsNone(active._cached_active_ask(
            state, self.lot(grade="9"), now + timedelta(minutes=5)
        ))
        self.assertIsNone(active._cached_active_ask(
            state, self.lot(language="French"), now + timedelta(minutes=5)
        ))

    def test_active_ask_cache_expires_and_never_caches_no_match(self):
        now = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
        state = {}
        lot = self.lot()
        self.assertIsNone(active._cached_active_ask(state, lot, now))
        self.assertNotIn(active._ACTIVE_ASK_CACHE_STATE_KEY, state)
        evidence = active.ActiveAskEvidence(
            source="eBay BIN", price=100.0, url="u", title="t",
            gap_pct=30.0, gcc_is_cheapest=True,
        )
        active._store_active_ask(state, lot, evidence, now)
        with patch.object(active, "_cache_ttl_minutes", return_value=30):
            self.assertIsNone(active._cached_active_ask(
                state, lot, now + timedelta(minutes=31)
            ))

    def test_cardmarket_raw_is_not_an_exact_graded_ask_source(self):
        self.assertEqual(active.ActiveAskEvidence.__annotations__["source"], "str")
        self.assertNotIn("cardmarket", active.build_ebay_active_url(self.lot()).lower())


if __name__ == "__main__":
    unittest.main()
