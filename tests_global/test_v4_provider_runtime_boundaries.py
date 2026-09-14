"""Real collector/runner regressions; substitutes only browser/HTTP boundaries."""
import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests_global.test_v4_global_marketplace_cardova_exhaustive_capture import (
    FakeResponse, PagedFakePage, _row,
)
import v4_global_marketplace_cardova_exhaustive_capture as cardova

class LanePage(PagedFakePage):
    def __init__(self, scenario):
        super().__init__({})
        self.scenario = scenario

    def goto(self, url, **kwargs):
        self.visited.append(url)
        lane = "auction" if "/auction" in url else "fixed"
        kind = 1 if lane == "auction" else 4
        row = dict(_row(lane), listing_type=kind)
        envelope = {"items": [row], "current_page": 1, "last_page": 1}
        payload = {"data": envelope}
        if self.scenario == "other_envelope":
            payload = {"data": {"items": [row]}, "recommendations": {
                "current_page": 1, "last_page": 1}}
        elif self.scenario == "other_lane":
            row["listing_type"] = 4 if kind == 1 else 1
        elif self.scenario == "mixed_lane":
            envelope["items"].append(dict(row, ulid="other", listing_type=4 if kind == 1 else 1))
        elif self.scenario == "future_page":
            envelope.update(current_page=9, last_page=9)
        elif self.scenario == "contradiction":
            envelope["pageInfo"] = {"hasNextPage": True}
        elif self.scenario == "http_error":
            pass
        response = FakeResponse(payload)
        response.status = 500 if self.scenario == "http_error" else 200
        if self.scenario != "unbound_request":
            self.request_handler(response.request)
        self.handler(response)


class ProviderRuntimeBoundaryTests(unittest.TestCase):
    def test_cardova_only_same_lane_envelope_current_page_can_complete(self):
        for scenario in ("valid", "other_envelope", "other_lane", "mixed_lane",
                         "future_page", "contradiction", "http_error", "unbound_request"):
            with self.subTest(scenario=scenario):
                page = LanePage(scenario)
                result = cardova.capture_cardova_public_inventory_exhaustive(
                    page, max_pages_each=2, settle_ms=0)
                self.assertEqual(result.complete, scenario == "valid")
                self.assertIsNone(page.handler)

    def test_fanatics_real_runner_installers_are_reentrant(self):
        result = subprocess.run([sys.executable, __file__, "fanatics"], cwd=ROOT,
                                text=True, capture_output=True, timeout=45)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def fanatics_case():
    sys.path.insert(0, str(ROOT))
    import requests
    from tests_global.test_v4_global_marketplace_fanatics_runtime_contract import CatalogueHTTP, LIVE
    http = CatalogueHTTP("live")
    with patch.object(requests.sessions.Session, "request",
                      lambda s, method, url, **kw: http.request(s, method, url, **kw)):
        import v4_global_marketplace_notify_resilient as runner
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch.object(sys, "argv", ["runner", "--help"]):
                try:
                    runner.main()
                except SystemExit as result:
                    assert result.code == 0
            runner.confirmed.install_global_external_market_stack()
            from v4_global_marketplace_fanatics_language_proof import install_global_marketplace_fanatics_language_proof
            from v4_global_marketplace_fanatics_cross_locale import install_global_marketplace_fanatics_cross_locale
            import v4_global_marketplace_fanatics_native_v3 as v3
            original = v3.resolve_fanatics_native_identity_v3
            for _ in range(3):
                install_global_marketplace_fanatics_language_proof()
                install_global_marketplace_fanatics_cross_locale()
            # The installed scanner passes the current TCGdex resolver explicitly.
            result = v3.resolve_fanatics_native_identity_v3(
                LIVE, proof_text=LIVE, resolver=runner.confirmed.multimarket.resolve_tcgdex_card)
            assert result.status == "EXACT", result
            assert v3.resolve_fanatics_native_identity_v3 is original, "resolver was recaptured"


if __name__ == "__main__":
    if sys.argv[1:] == ["fanatics"]:
        fanatics_case()
    else:
        unittest.main()
