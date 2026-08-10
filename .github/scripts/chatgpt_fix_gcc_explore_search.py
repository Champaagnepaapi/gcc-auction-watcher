from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, got {count}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "v5/gcc_live_adapter.py",
    'GCC_EXPLORE_URL = "https://gradedcardcenter.com/en/filters/explore/pokemon"',
    'GCC_EXPLORE_URL = "https://gradedcardcenter.com/en/filters/explore/cards-graded"',
)

replace_once(
    "v5/gcc_live_adapter.py",
    '''GCC_V4_ACCESS_MECHANISM = (\n    "V4 public on-sale-items fast path + GCC public Explore/Completed Sales catalogue fallback + normal authenticated Playwright item page rendered history"\n)''',
    '''GCC_V4_ACCESS_MECHANISM = (\n    "V4 public on-sale-items fast path + GCC public graded-card Explore/Completed Sales local-search fallback + normal authenticated Playwright item page rendered history"\n)''',
)

replace_once(
    "v5/gcc_live_adapter.py",
    '''        self.catalog_completed_sales_enabled = 0\n        self.catalog_search_failures = 0\n        self.parsing = HistoricalParsingDiagnostics()''',
    '''        self.catalog_completed_sales_enabled = 0\n        self.catalog_search_failures = 0\n        self.catalog_search_ineffective = 0\n        self.parsing = HistoricalParsingDiagnostics()''',
)

replace_once(
    "v5/gcc_live_adapter.py",
    '''    def _catalog_search_box(self):\n        selectors = (\n            'input[placeholder="Search"]',\n            'input[placeholder="Rechercher"]',\n            'input[placeholder="Recherche"]',\n            'input[type="search"]',\n        )''',
    '''    def _catalog_search_box(self):\n        # GCC exposes both a site-wide search and, on the graded-card Explore\n        # view, a local catalogue search.  Only the explicit local placeholder\n        # is accepted here: a generic input[type=search] can silently select the\n        # global header search and leave Explore results unchanged.\n        selectors = (\n            'input[placeholder="Search"]',\n            'input[placeholder="Rechercher"]',\n            'input[placeholder="Recherche"]',\n        )''',
)

replace_once(
    "v5/gcc_live_adapter.py",
    '''                search_box.fill(query)\n                try:\n                    search_box.press("Enter")\n                except Exception:\n                    pass\n                self.catalog_searches += 1\n                self._page.wait_for_timeout(1200)\n                urls = self._catalog_item_urls()''',
    '''                # Capture the completed-sales result set before typing so\n                # we can prove that the local Explore filter actually reacted.\n                # Playwright fill() dispatches the input event; pressing Enter\n                # is intentionally avoided because GCC also has a global search.\n                before_urls = self._catalog_item_urls()\n                search_box.fill(query)\n                self.catalog_searches += 1\n                urls: tuple[str, ...] = ()\n                for _ in range(10):\n                    self._page.wait_for_timeout(250)\n                    urls = self._catalog_item_urls()\n                    if urls != before_urls:\n                        break\n                if urls == before_urls:\n                    self.catalog_search_ineffective += 1\n                    continue''',
)

replace_once(
    "v5/live_raw_pipeline.py",
    '''    gcc_catalog_completed_sales_enabled: int = 0\n    gcc_catalog_search_failures: int = 0\n    gcc_records_with_grader: int = 0''',
    '''    gcc_catalog_completed_sales_enabled: int = 0\n    gcc_catalog_search_failures: int = 0\n    gcc_catalog_search_ineffective: int = 0\n    gcc_records_with_grader: int = 0''',
)

replace_once(
    "v5/live_raw_pipeline.py",
    '''                gcc_catalog_search_failures=getattr(\n                    gcc_source, "catalog_search_failures", 0\n                ),\n                gcc_records_with_grader=getattr(''',
    '''                gcc_catalog_search_failures=getattr(\n                    gcc_source, "catalog_search_failures", 0\n                ),\n                gcc_catalog_search_ineffective=getattr(\n                    gcc_source, "catalog_search_ineffective", 0\n                ),\n                gcc_records_with_grader=getattr(''',
)

replace_once(
    "v5/live_raw_pipeline.py",
    '''            f"catalog search failures: {summary.providers.gcc_catalog_search_failures}",\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
    '''            f"catalog search failures: {summary.providers.gcc_catalog_search_failures}",\n            (\n                "catalog searches ineffective: "\n                f"{summary.providers.gcc_catalog_search_ineffective}"\n            ),\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
)

# Minimal regression: the resolver must use the graded-card Explore view where
# GCC exposes a distinct local Search control, not the category Explore page.
p = Path("tests_v5/test_gcc_live_adapter_matching.py")
text = p.read_text(encoding="utf-8")
text = text.replace(
    'from v5.gcc_live_adapter import V4RenderedGCCHistorySource',
    'from v5.gcc_live_adapter import GCC_EXPLORE_URL, V4RenderedGCCHistorySource',
    1,
)
needle = '''class GCCRepresentativeSelectionTests(unittest.TestCase):\n'''
insert = '''class GCCRepresentativeSelectionTests(unittest.TestCase):\n    def test_catalog_fallback_uses_graded_card_explore_view(self):\n        self.assertTrue(GCC_EXPLORE_URL.endswith("/filters/explore/cards-graded"))\n\n'''
if text.count(needle) != 1:
    raise RuntimeError("test class anchor not found exactly once")
text = text.replace(needle, insert, 1)
p.write_text(text, encoding="utf-8")
