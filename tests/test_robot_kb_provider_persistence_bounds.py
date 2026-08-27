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

import robot_kb_multisource_provider_bounds as bounds


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _Connection:
    def __init__(self, existing):
        self.existing = set(existing)
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        native_ids = set(params[2:])
        rows = [
            {"source_native_record_id": native_id}
            for native_id in sorted(self.existing & native_ids)
        ]
        return _Rows(rows)


class RobotKbProviderPersistenceBoundsTests(unittest.TestCase):
    def fake_harvest(self):
        persisted = []

        def persist_metrics(_kb, metrics, _raw, _raw_id, _source, _observed_at):
            persisted.append([metric.native_id for metric in metrics])
            return len(metrics)

        def refresh_ppt_sets(state, _session, _key, _diag):
            state["ppt"]["sets"] = {
                "english": [{"id": str(i)} for i in range(5)],
                "japanese": [{"id": str(i)} for i in range(4)],
            }
            state["ppt"]["positions"] = {"english": 0, "japanese": 0}
            state["ppt"]["language_index"] = 0
            return True

        def next_ppt_set(_state):
            return None

        harvest = SimpleNamespace(
            persist_metrics=persist_metrics,
            refresh_ppt_sets=refresh_ppt_sets,
            next_ppt_set=next_ppt_set,
        )
        return harvest, persisted

    def test_metric_persistence_is_bounded_and_continues_after_existing_ids(self):
        harvest, persisted = self.fake_harvest()
        bounds.install(harvest)
        kb = SimpleNamespace(connection=_Connection({"m1", "m2"}))
        metrics = [SimpleNamespace(native_id=f"m{i}") for i in range(1, 10)]

        with patch.dict(os.environ, {"ROBOT_KB_PROVIDER_METRICS_PER_RECORD": "3"}):
            stored = harvest.persist_metrics(
                kb, metrics, {"full": "raw"}, "raw-1", "poketrace", "2026-08-27T00:00:00Z"
            )

        self.assertEqual(stored, 3)
        self.assertEqual(persisted, [["m3", "m4", "m5"]])
        self.assertEqual(len(kb.connection.calls), 1)

    def test_ppt_catalog_refresh_preserves_progress(self):
        harvest, _persisted = self.fake_harvest()
        bounds.install(harvest)
        state = {
            "ppt": {
                "sets": {"english": [{"id": "old"}], "japanese": [{"id": "old"}]},
                "positions": {"english": 3, "japanese": 2},
                "language_index": 1,
            }
        }

        self.assertTrue(harvest.refresh_ppt_sets(state, object(), "test", object()))
        self.assertEqual(state["ppt"]["positions"], {"english": 3, "japanese": 2})
        self.assertEqual(state["ppt"]["language_index"], 1)

    def test_ppt_cycle_exhaustion_resets_next_cycle_positions(self):
        harvest, _persisted = self.fake_harvest()
        bounds.install(harvest)
        state = {
            "ppt": {
                "sets": {"english": [], "japanese": []},
                "positions": {"english": 5, "japanese": 4},
                "language_index": 1,
            }
        }

        self.assertIsNone(harvest.next_ppt_set(state))
        self.assertEqual(state["ppt"]["positions"], {"english": 0, "japanese": 0})
        self.assertEqual(state["ppt"]["language_index"], 0)

    def test_entrypoint_installs_bounds_after_p3_before_fairness(self):
        source = (LOCAL / "robot_kb_multisource_entrypoint.py").read_text(encoding="utf-8")
        self.assertIn("import robot_kb_multisource_provider_bounds as provider_bounds", source)
        self.assertLess(
            source.index("p3_compat.install(harvest)"),
            source.index("provider_bounds.install(harvest)"),
        )
        self.assertLess(
            source.index("provider_bounds.install(harvest)"),
            source.index("paid_fairness.install(harvest)"),
        )


if __name__ == "__main__":
    unittest.main()
