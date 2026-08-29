from pathlib import Path
import importlib.util
import unittest


PATH = Path(__file__).resolve().parents[1] / "mac" / "robot-kb-local" / "robot_kb_cardova_network_discovery.py"
spec = importlib.util.spec_from_file_location("cardova_network_discovery", PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


class CardovaNetworkDiscoveryTests(unittest.TestCase):
    def test_url_gate_is_cardova_https_only(self):
        self.assertTrue(mod._allowed("https://www.cardova.co.jp/en/auction/close"))
        self.assertTrue(mod._allowed("https://bg.cardova.co.jp/api/v1/auction/select-list"))
        self.assertFalse(mod._allowed("http://www.cardova.co.jp/en/auction/close"))
        self.assertFalse(mod._allowed("https://example.com/"))

    def test_route_regex_finds_public_auction_routes(self):
        text = 'x="/api/v1/auction/select-list?status=close&limit=24"; y="/api/v1/trade/history"'
        hits = mod.ROUTE_RE.findall(text)
        self.assertIn("/api/v1/auction/select-list?status=close&limit=24", hits)
        self.assertIn("/api/v1/trade/history", hits)

    def test_safety_summary(self):
        s = mod.safe_summary()
        self.assertTrue(s["public_anonymous_only"])
        for key in (
            "credentials_used", "cookies_supplied", "authentication_headers_supplied",
            "posts_issued", "robot_kb_write", "sale_transaction_stored",
            "v4_economic_use", "automatic_purchase", "automatic_bid",
            "automatic_offer", "automatic_checkout", "automatic_payment",
        ):
            self.assertFalse(s[key], key)


if __name__ == "__main__":
    unittest.main()
