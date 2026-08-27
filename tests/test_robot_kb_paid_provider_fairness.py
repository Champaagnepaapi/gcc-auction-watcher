from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
if str(LOCAL) not in sys.path:
    sys.path.insert(0, str(LOCAL))

import robot_kb_multisource_paid_fairness as fairness


class RobotKbPaidProviderFairnessTests(unittest.TestCase):
    def fake_harvest(self):
        calls = []

        def poketrace(_kb, _state, key, _diag, deadline):
            calls.append(("poketrace", key, deadline))

        def ppt(_kb, _state, key, _diag, deadline):
            calls.append(("ppt", key, deadline))

        harvest = SimpleNamespace(
            paid_open=lambda: True,
            harvest_poketrace=poketrace,
            harvest_ppt=ppt,
        )
        return harvest, calls

    def test_both_providers_keep_window_even_if_first_overruns(self):
        harvest, calls = self.fake_harvest()
        fairness.install(harvest)
        diag = SimpleNamespace(notes=[])

        with patch.dict(
            os.environ,
            {
                "ROBOT_KB_PAID_MAX_RUNTIME_SECONDS": "120",
                "POKETRACE_API_KEY": "pt-test-key",
                "POKEMON_PRICE_TRACKER_API_KEY": "ppt-test-key",
            },
            clear=False,
        ), patch.object(fairness.time, "monotonic", side_effect=[100.0, 1000.0]):
            harvest.run_paid(object(), {}, diag)

        self.assertEqual(
            calls,
            [
                ("poketrace", "pt-test-key", 160.0),
                ("ppt", "ppt-test-key", 1060.0),
            ],
        )
        self.assertIn(
            "paid:provider-windows:poketrace=60s:ppt=60s:independent=true",
            diag.notes,
        )

    def test_ppt_only_keeps_full_paid_runtime(self):
        harvest, calls = self.fake_harvest()
        fairness.install(harvest)
        diag = SimpleNamespace(notes=[])

        with patch.dict(
            os.environ,
            {
                "ROBOT_KB_PAID_MAX_RUNTIME_SECONDS": "120",
                "POKETRACE_API_KEY": "",
                "POKEMON_PRICE_TRACKER_API_KEY": "ppt-test-key",
            },
            clear=False,
        ), patch.object(fairness.time, "monotonic", return_value=50.0):
            harvest.run_paid(object(), {}, diag)

        self.assertEqual(calls, [("ppt", "ppt-test-key", 170.0)])
        self.assertIn("poketrace:key-not-configured", diag.notes)

    def test_poketrace_only_keeps_full_paid_runtime(self):
        harvest, calls = self.fake_harvest()
        fairness.install(harvest)
        diag = SimpleNamespace(notes=[])

        with patch.dict(
            os.environ,
            {
                "ROBOT_KB_PAID_MAX_RUNTIME_SECONDS": "120",
                "POKETRACE_API_KEY": "pt-test-key",
                "POKEMON_PRICE_TRACKER_API_KEY": "",
            },
            clear=False,
        ), patch.object(fairness.time, "monotonic", return_value=25.0):
            harvest.run_paid(object(), {}, diag)

        self.assertEqual(calls, [("poketrace", "pt-test-key", 145.0)])
        self.assertIn("ppt:key-not-configured", diag.notes)

    def test_entrypoint_installs_paid_fairness_after_p3_compat(self):
        source = (LOCAL / "robot_kb_multisource_entrypoint.py").read_text(encoding="utf-8")
        self.assertIn("import robot_kb_multisource_paid_fairness as paid_fairness", source)
        self.assertLess(
            source.index("p3_compat.install(harvest)"),
            source.index("paid_fairness.install(harvest)"),
        )


if __name__ == "__main__":
    unittest.main()
