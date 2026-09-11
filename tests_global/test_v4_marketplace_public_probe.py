import unittest
from types import SimpleNamespace

import v4_global_marketplace_public_probe as module
from v4_global_marketplace_public_probe import probe


class Page:
    def __init__(self, status=200, snapshots=()):
        self.status, self.snapshots = status, list(snapshots)
        self.events, self.waits = {}, []
    def on(self, event, callback): self.events[event] = callback
    def remove_listener(self, event, callback): self.events.pop(event)
    def goto(self, url, **kwargs):
        self.url = url
        return SimpleNamespace(status=self.status)
    def wait_for_timeout(self, ms): self.waits.append(ms)
    def evaluate(self, script): return self.snapshots.pop(0)


class PublicProbeTests(unittest.TestCase):
    def test_product_probe_retains_only_allowlisted_public_item_fields(self):
        page = Page(snapshots=[{"title": "Pikachu PSA10", "product": {"name": "Pikachu", "description": "do not copy", "seller": "do not copy", "offers": {"price": "1000", "priceCurrency": "JPY", "availability": "https://schema.org/InStock", "payment": "do not copy"}}, "fields": {"商品の状態": "未使用", "配送の方法": "匿名配送", "account": "do not copy"}}])
        result = module.inspect_public_item(page, "https://jp.mercari.com/item/m123")
        self.assertEqual(result["product"]["offers"]["priceCurrency"], "JPY")
        self.assertNotIn("do not copy", str(result))
        self.assertFalse(result["sold_proven"])

    def test_product_http_block_does_not_retry(self):
        page = Page(403)
        result = module.inspect_public_item(page, "https://jp.mercari.com/item/m123")
        self.assertEqual(result["state"], "HTTP_BLOCKED")
        self.assertEqual(page.waits, [])

    def test_403_stops_without_dom_or_retry(self):
        page = Page(403)
        result = probe(page, "snkrdunk", "https://snkrdunk.com/en/search/result?keyword=Pokemon", r"/used/\d+")
        self.assertEqual(result["state"], "HTTP_BLOCKED")
        self.assertEqual(page.waits, [])
        self.assertEqual(page.events, {})

    def test_empty_shell_stays_incomplete(self):
        page = Page(snapshots=[{"links": [], "container": False}] * 3)
        result = probe(page, "mercari", "https://jp.mercari.com/search", r"/item/m\d+")
        self.assertEqual(result["state"], "CONTENT_UNPROVEN")
        self.assertEqual(result["observations"], 3)
        self.assertFalse(result["complete"])

    def test_late_results_record_public_urls_only(self):
        page = Page(snapshots=[{"links": []}, {"links": ["https://jp.mercari.com/item/m123?tracking=x"]}])
        result = probe(page, "mercari", "https://jp.mercari.com/search", r"/item/m\d+")
        self.assertEqual(result["state"], "RESULTS")
        self.assertEqual(result["urls"], ["https://jp.mercari.com/item/m123"])
        self.assertFalse(result["complete"])


if __name__ == "__main__": unittest.main()
