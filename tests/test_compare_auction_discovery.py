from __future__ import annotations

import unittest

import watcher
from compare_auction_discovery import resolve_legacy_ids


class _FakePage:
    def __init__(self) -> None:
        self.waits: list[int] = []

    def wait_for_timeout(self, milliseconds: int) -> None:
        self.waits.append(milliseconds)


class LegacyTimerResolutionTests(unittest.TestCase):
    def lot(self, suffix: str, *, minutes_to_end=None, inspection_error=None):
        return watcher.Lot(
            url=f"https://gradedcardcenter.com/item/{suffix}",
            title=f"PSA 9 Pikachu {suffix}",
            current_price=50.0,
            source_type="auction",
            minutes_to_end=minutes_to_end,
            inspection_error=inspection_error,
        )

    def test_transient_missing_timer_is_retried_and_resolved(self):
        page = _FakePage()
        calls = 0

        def inspect(_page, current):
            nonlocal calls
            calls += 1
            if calls == 1:
                return self.lot("retry", minutes_to_end=None, inspection_error="timer")
            return self.lot("retry", minutes_to_end=120, inspection_error=None)

        resolved, unresolved = resolve_legacy_ids(
            page,
            [self.lot("retry")],
            717,
            inspect_func=inspect,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(page.waits, [300])
        self.assertEqual(
            resolved,
            {"https://gradedcardcenter.com/item/retry"},
        )
        self.assertEqual(unresolved, set())

    def test_persistent_missing_timer_remains_fail_closed(self):
        page = _FakePage()
        calls = 0

        def inspect(_page, current):
            nonlocal calls
            calls += 1
            return self.lot("unresolved", minutes_to_end=None, inspection_error="timer")

        resolved, unresolved = resolve_legacy_ids(
            page,
            [self.lot("unresolved")],
            717,
            inspect_func=inspect,
        )

        self.assertEqual(calls, 2)
        self.assertEqual(page.waits, [300])
        self.assertEqual(resolved, set())
        self.assertEqual(
            unresolved,
            {"https://gradedcardcenter.com/item/unresolved"},
        )

    def test_existing_timer_uses_no_detail_retry(self):
        page = _FakePage()

        def inspect(_page, current):
            raise AssertionError("inspect should not be called")

        resolved, unresolved = resolve_legacy_ids(
            page,
            [self.lot("already-timed", minutes_to_end=90)],
            717,
            inspect_func=inspect,
        )

        self.assertEqual(
            resolved,
            {"https://gradedcardcenter.com/item/already-timed"},
        )
        self.assertEqual(unresolved, set())
        self.assertEqual(page.waits, [])


if __name__ == "__main__":
    unittest.main()
