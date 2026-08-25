from __future__ import annotations

import unittest
from unittest import mock

import v4_global_marketplace_magi_detail_retry as retry


class Page:
    def __init__(self):
        self.waits = []

    def wait_for_timeout(self, value):
        self.waits.append(value)


class MagiDetailRetryTests(unittest.TestCase):
    def test_success_is_not_retried(self):
        page = Page()
        calls = []

        def original(_page, ask):
            calls.append(ask)
            return "ok"

        with mock.patch.object(retry, "_ORIGINAL_DETAIL", original):
            self.assertEqual(retry.magi_detail_once_retry(page, "ask"), "ok")
        self.assertEqual(calls, ["ask"])
        self.assertEqual(page.waits, [])

    def test_one_transport_failure_gets_one_retry(self):
        page = Page()
        calls = []

        def original(_page, ask):
            calls.append(ask)
            if len(calls) == 1:
                raise TimeoutError("first")
            return "ok"

        with mock.patch.object(retry, "_ORIGINAL_DETAIL", original):
            self.assertEqual(retry.magi_detail_once_retry(page, "ask"), "ok")
        self.assertEqual(calls, ["ask", "ask"])
        self.assertEqual(page.waits, [250])

    def test_second_failure_propagates(self):
        page = Page()
        calls = []

        def original(_page, ask):
            calls.append(ask)
            raise TimeoutError("still broken")

        with mock.patch.object(retry, "_ORIGINAL_DETAIL", original):
            with self.assertRaises(TimeoutError):
                retry.magi_detail_once_retry(page, "ask")
        self.assertEqual(calls, ["ask", "ask"])
        self.assertEqual(page.waits, [250])


if __name__ == "__main__":
    unittest.main()
