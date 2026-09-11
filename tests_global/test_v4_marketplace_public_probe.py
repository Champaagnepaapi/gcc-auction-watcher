import unittest
from types import SimpleNamespace

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
