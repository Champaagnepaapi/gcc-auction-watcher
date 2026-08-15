from __future__ import annotations

import unittest
from types import SimpleNamespace

import watcher
import v4_smart_external_priority as smart


def candidate(
    *,
    url: str,
    source_type: str = "fixed",
    price: float = 50.0,
    grader: str = "PSA",
    exact: int = 3,
    branch: str = watcher.GCC_BRANCH_SUPPORTED,
    minutes: int | None = None,
):
    lot = SimpleNamespace(
        url=url,
        source_type=source_type,
        current_price=price,
        grader=grader,
        minutes_to_end=minutes,
    )
    gcc = SimpleNamespace(
        diagnostics=SimpleNamespace(exact_grade_count=exact),
        branch=branch,
    )
    return SimpleNamespace(lot=lot, gcc=gcc, fixed_queue_category=watcher.QUEUE_P1_CHANGED)


class SmartExternalPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        smart._PRICE_DROP_BY_ITEM.clear()
        self.old_sort = smart._ORIGINAL_EXTERNAL_SORT
        self.old_prepare = smart._ORIGINAL_PREPARE

    def tearDown(self) -> None:
        smart._ORIGINAL_EXTERNAL_SORT = self.old_sort
        smart._ORIGINAL_PREPARE = self.old_prepare
        smart._PRICE_DROP_BY_ITEM.clear()

    def test_auction_order_is_bit_for_bit_delegated_to_canonical_sort(self) -> None:
        smart._ORIGINAL_EXTERNAL_SORT = lambda c, status: (
            0,
            c.lot.minutes_to_end,
            c.lot.url,
        )
        soon = candidate(url="soon", source_type="auction", minutes=2, price=99, exact=0, grader="PCA")
        later = candidate(url="later", source_type="auction", minutes=30, price=1, exact=0, grader="CCC")
        self.assertEqual(smart._smart_external_queue_sort_key(soon, "MISS"), (0, 2, "soon"))
        self.assertLess(
            smart._smart_external_queue_sort_key(soon, "MISS"),
            smart._smart_external_queue_sort_key(later, "MISS"),
        )

    def test_sparse_secondary_low_price_scores_above_liquid_psa(self) -> None:
        strong = candidate(url="strong", price=85, grader="PSA", exact=5)
        sparse = candidate(url="sparse", price=20, grader="PCA", exact=0, branch=watcher.GCC_BRANCH_UNAVAILABLE)
        self.assertGreater(smart.external_priority_score(sparse), smart.external_priority_score(strong))

    def test_real_price_drop_is_remembered_before_queue_overwrites_last_price(self) -> None:
        lot = SimpleNamespace(url="https://gradedcardcenter.com/item/drop", current_price=60.0)
        item_id = "drop-id"
        original_fixed_id = watcher.fixed_listing_id
        watcher.fixed_listing_id = lambda _lot: item_id

        state = {
            watcher.FIXED_QUEUE_STATE_KEY: {
                "items": {item_id: {"last_price": 100.0}}
            }
        }

        def fake_prepare(candidates, state, run_now, diagnostics, cap):
            state[watcher.FIXED_QUEUE_STATE_KEY]["items"][item_id]["last_price"] = 60.0
            return [lot], {item_id: watcher.QUEUE_P1_CHANGED}, state[watcher.FIXED_QUEUE_STATE_KEY]["items"]

        smart._ORIGINAL_PREPARE = fake_prepare
        try:
            smart._prepare_with_price_drop_memory([lot], state, None, None, 120)
            self.assertAlmostEqual(smart._PRICE_DROP_BY_ITEM[item_id], 40.0)
        finally:
            watcher.fixed_listing_id = original_fixed_id

    def test_smart_score_only_reorders_inside_existing_fixed_category(self) -> None:
        category = {
            "new": 1,
            "changed-a": 2,
            "changed-b": 2,
            "stale": 5,
        }
        smart._ORIGINAL_EXTERNAL_SORT = lambda c, status: (
            category[c.lot.url],
            4,
            c.lot.url,
        )
        new = candidate(url="new", price=99, exact=5)
        changed_a = candidate(url="changed-a", price=90, exact=5)
        changed_b = candidate(url="changed-b", price=10, exact=0, grader="PCA")
        stale = candidate(url="stale", price=1, exact=0, grader="CCC")
        ordered = sorted(
            [stale, changed_a, changed_b, new],
            key=lambda c: smart._smart_external_queue_sort_key(c, "MISS"),
        )
        self.assertEqual([c.lot.url for c in ordered], ["new", "changed-b", "changed-a", "stale"])


if __name__ == "__main__":
    unittest.main()
