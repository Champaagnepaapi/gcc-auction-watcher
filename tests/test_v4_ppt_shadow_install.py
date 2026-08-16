from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import v4_ppt_shadow_provider as ppt


class PptShadowInstallTests(unittest.TestCase):
    def _watcher(self, result):
        module = types.ModuleType("watcher")
        module.logs = []
        module.log = module.logs.append

        def original(*args, **kwargs):
            return result

        module.process_external_market_candidates = original
        module.original = original
        return module

    def test_safe_off_does_not_wrap_v4(self):
        sentinel = [object()]
        watcher = self._watcher(sentinel)
        with patch.dict(sys.modules, {"watcher": watcher}), patch.dict(
            os.environ,
            {"V4_PPT_SHADOW_ENABLED": "false"},
            clear=False,
        ), patch.object(ppt, "_ORIGINAL", None):
            ppt.install_v4_ppt_shadow()

        self.assertIs(watcher.process_external_market_candidates, watcher.original)
        self.assertFalse(getattr(watcher, "_v4_ppt_shadow_installed", False))

    def test_enabled_wrapper_returns_original_opportunities_unchanged(self):
        sentinel = [object(), object()]
        watcher = self._watcher(sentinel)
        summary = {
            "eligible": 1,
            "matched": 1,
            "strong": 1,
            "cache_hits": 0,
            "blocked_language": 0,
            "blocked_variant": 0,
            "rescue_candidates": 1,
            "revalue_candidates": 0,
        }
        now = datetime(2026, 8, 15, 22, 0, tzinfo=timezone.utc)

        with patch.dict(sys.modules, {"watcher": watcher}), patch.dict(
            os.environ,
            {
                "V4_PPT_SHADOW_ENABLED": "true",
                "POKEMONPRICETRACKER_API_KEY": "offline-test-key",
            },
            clear=False,
        ), patch.object(ppt, "_ORIGINAL", None), patch.object(
            ppt, "collect_ppt_shadow", return_value=summary
        ) as collector:
            ppt.install_v4_ppt_shadow()
            result = watcher.process_external_market_candidates(
                None,
                [],
                {},
                None,
                None,
                now,
            )

        self.assertIs(result, sentinel)
        collector.assert_called_once()
        self.assertTrue(getattr(watcher, "_v4_ppt_shadow_installed", False))
        self.assertTrue(any("economic-use=false" in line for line in watcher.logs))


if __name__ == "__main__":
    unittest.main()
