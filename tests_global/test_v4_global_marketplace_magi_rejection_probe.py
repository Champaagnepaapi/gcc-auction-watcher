from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest import mock

import japan_edge_hunter as japan
import v4_global_marketplace_magi_native_identity as native
import v4_global_marketplace_magi_rejection_probe as probe


class MagiRejectionProbeTests(unittest.TestCase):
    def setUp(self):
        probe.clear_magi_rejection_probe_state()

    def test_records_only_public_magi_item_and_is_bounded(self):
        ask = japan.Ask(
            "magi",
            "https://magi.camp/items/123",
            "  PSA10   ミュウツー  ",
            10000,
            "ignored body",
        )
        result = native.MagiNativeResolution("NO_MATCH", "collector_number_unproven")
        out = io.StringIO()
        with (
            mock.patch.object(probe, "_ENABLED", True),
            mock.patch.object(probe, "_MAX_TOTAL", 1),
            redirect_stdout(out),
        ):
            probe._record(ask, result)
            probe._record(ask, result)
        text = out.getvalue()
        self.assertEqual(text.count("[MAGI_REJECT]"), 1)
        self.assertIn("collector_number_unproven", text)
        self.assertIn("https://magi.camp/items/123", text)
        self.assertIn("PSA10 ミュウツー", text)
        self.assertNotIn("ignored body", text)

    def test_invalid_url_is_never_logged(self):
        ask = japan.Ask("magi", "https://example.com/private", "PSA10 card", 10000, "secret")
        result = native.MagiNativeResolution("NO_MATCH", "x")
        out = io.StringIO()
        with mock.patch.object(probe, "_ENABLED", True), redirect_stdout(out):
            probe._record(ask, result)
        self.assertEqual(out.getvalue(), "")

    def test_exact_resolution_is_never_logged(self):
        identity = mock.Mock()
        ask = japan.Ask("magi", "https://magi.camp/items/124", "PSA10 card", 10000, "")
        result = native.MagiNativeResolution("EXACT", "ok", identity=identity)
        out = io.StringIO()
        with mock.patch.object(probe, "_ENABLED", True), redirect_stdout(out):
            probe._record(ask, result)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
