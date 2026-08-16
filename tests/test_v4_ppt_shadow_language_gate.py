from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from v4_ppt_shadow_provider import collect_ppt_shadow


class _NoNetworkSession:
    def __init__(self):
        self.calls = 0

    def get(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("non-English candidate must be blocked before PPT network")


class PptShadowLanguageGateTests(unittest.TestCase):
    def test_non_english_candidate_is_blocked_before_network(self):
        lot = SimpleNamespace(
            grader="PSA",
            grade="10",
            current_price=100.0,
        )
        candidate = SimpleNamespace(
            lot=lot,
            gcc=SimpleNamespace(
                sales=[],
                estimate=None,
                branch="UNAVAILABLE",
                strength="UNAVAILABLE",
            ),
        )
        canonical = SimpleNamespace(
            status="EXACT",
            language_code="fr",
            card_id="base1-4",
            name="Dracaufeu",
            set_name="Set de Base",
            full_number="4/102",
            local_id="4",
        )

        fake_watcher = types.ModuleType("watcher")
        fake_watcher.external_commercial_identity_key = lambda _lot: "strict-key"
        fake_watcher._target_grade = lambda _lot: 10.0

        fake_canonical = types.ModuleType("v4_canonical_multimarket")
        fake_canonical._usd_per_eur = lambda: 1.0
        fake_canonical._canonical_from_lot = lambda _lot: canonical
        fake_canonical._raw_variant_choice = lambda _lot, _canonical: ("holo", True)

        session = _NoNetworkSession()
        state = {}
        now = datetime(2026, 8, 15, 22, 0, tzinfo=timezone.utc)

        with patch.dict(
            os.environ,
            {"POKEMONPRICETRACKER_API_KEY": "offline-test-key"},
            clear=False,
        ), patch.dict(
            sys.modules,
            {
                "watcher": fake_watcher,
                "v4_canonical_multimarket": fake_canonical,
            },
        ):
            summary = collect_ppt_shadow(
                [candidate],
                [],
                state,
                now,
                session=session,
            )

        self.assertEqual(summary["blocked_language"], 1)
        self.assertEqual(summary["eligible"], 0)
        self.assertEqual(session.calls, 0)
        self.assertEqual(state["v4_ppt_shadow"]["records"], {})
        self.assertEqual(state["v4_ppt_shadow"]["cache"], {})


if __name__ == "__main__":
    unittest.main()
