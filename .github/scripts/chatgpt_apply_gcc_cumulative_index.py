from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# Avoid O(n^2) rebuilds while a daily refresh inserts thousands of GCC items.
replace_once(
    "v5/gcc_catalog_cache.py",
    '''        self._items[url] = entry\n        self._dirty = True\n        self._rebuild_name_index()\n        return True''',
    '''        previous_name = (\n            self._identity_from_entry(previous).card_name\n            if isinstance(previous, Mapping)\n            else None\n        )\n        self._items[url] = entry\n        if previous_name and previous_name != identity.card_name:\n            old_bucket = self._by_name.get(previous_name, [])\n            if url in old_bucket:\n                old_bucket.remove(url)\n        bucket = self._by_name.setdefault(identity.card_name, [])\n        if url not in bucket:\n            bucket.append(url)\n        self._dirty = True\n        return True''',
)

# ---- V5 GCC live adapter: persistent GCC-only cache + conflict provenance ----
replace_once(
    "v5/gcc_live_adapter.py",
    '''from contextlib import AbstractContextManager\nfrom dataclasses import dataclass, replace''',
    '''from collections import Counter\nfrom contextlib import AbstractContextManager\nfrom dataclasses import dataclass, replace''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''import watcher\nfrom gcc_history_shared import HistoricalParsingDiagnostics\n\nfrom .market_values.gcc_history.identity import canonicalize_collectible, match_identity''',
    '''import watcher\nfrom gcc_history_shared import HistoricalParsingDiagnostics\n\nfrom .gcc_catalog_cache import GCCCatalogIndex, canonical_from_gcc_lot\nfrom .market_values.gcc_history.identity import canonicalize_collectible, match_identity''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''def _lot_identity(lot: watcher.Lot) -> CanonicalCollectible:\n    parsed = watcher.extract_card_identity(lot)\n    core = parsed.get("core") or lot.title\n    set_name = lot.card_set or parsed.get("series") or ""\n    card_number = lot.card_number or parsed.get("ref") or ""\n    return canonicalize_collectible(\n        CanonicalCollectible(\n            card_name=core or None,\n            set_name=set_name or None,\n            card_number=card_number or None,\n            language=(lot.language or parsed.get("language") or None),\n            variant=lot.variant or None,\n            year=lot.year,\n            set_family=lot.set_family or set_name or None,\n            category="pokemon",\n        )\n    )''',
    '''def _lot_identity(lot: watcher.Lot) -> CanonicalCollectible:\n    return canonical_from_gcc_lot(lot)''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        history_extractor: Callable[..., Sequence[watcher.HistoricalSale]] = watcher.extract_historical_sales,\n        catalog_resolver: Callable[[CanonicalCollectible], GCCCatalogResolution] | None = None,\n    ) -> None:''',
    '''        history_extractor: Callable[..., Sequence[watcher.HistoricalSale]] = watcher.extract_historical_sales,\n        catalog_resolver: Callable[[CanonicalCollectible], GCCCatalogResolution] | None = None,\n        catalog_index: GCCCatalogIndex | None = None,\n    ) -> None:''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        self._history_extractor = history_extractor\n        self._catalog_resolver = catalog_resolver or self._resolve_from_public_explore\n        self._inventory_loaded = False''',
    '''        self._history_extractor = history_extractor\n        self._catalog_resolver = catalog_resolver or self._resolve_from_public_explore\n        self._catalog_index = catalog_index or GCCCatalogIndex()\n        self._inventory_loaded = False''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        self.inventory_pages_requested = 0\n        self.identity_conflicts = 0\n        self.representative_exact = 0''',
    '''        self.inventory_pages_requested = 0\n        self.identity_conflicts = 0\n        self.identity_conflict_fields: Counter[str] = Counter()\n        self.representative_exact = 0''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        self.catalog_search_failures = 0\n        self.parsing = HistoricalParsingDiagnostics()\n\n    def _load_inventory(self) -> None:''',
    '''        self.catalog_search_failures = 0\n        self.parsing = HistoricalParsingDiagnostics()\n\n    @property\n    def catalog_cache_entries_loaded(self) -> int:\n        return self._catalog_index.entries_loaded\n\n    @property\n    def catalog_cache_entries_current(self) -> int:\n        return self._catalog_index.current_entries\n\n    @property\n    def catalog_cache_added(self) -> int:\n        return self._catalog_index.added_this_run\n\n    @property\n    def catalog_cache_updated(self) -> int:\n        return self._catalog_index.updated_this_run\n\n    @property\n    def catalog_cache_lookup_hits(self) -> int:\n        return self._catalog_index.lookup_hits\n\n    @property\n    def catalog_cache_load_failures(self) -> int:\n        return self._catalog_index.load_failures\n\n    @property\n    def catalog_cache_save_failures(self) -> int:\n        return self._catalog_index.save_failures\n\n    def persist_catalog_index(self) -> None:\n        self._catalog_index.save()\n\n    def _record_identity_conflict(self, result) -> None:\n        if not result.conflicts:\n            return\n        self.identity_conflicts += 1\n        self.identity_conflict_fields.update(result.conflicts)\n\n    def _load_inventory(self) -> None:''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''            if not identity.card_name or not (identity.card_number or identity.set_name):\n                continue\n            self._by_name.setdefault(identity.card_name, []).append((identity, lot))''',
    '''            if not identity.card_name or not (identity.card_number or identity.set_name):\n                continue\n            self._by_name.setdefault(identity.card_name, []).append((identity, lot))\n            self._catalog_index.upsert(identity, lot, source="on_sale")''',
)
# Two conflict increments exist: Explore candidates and inventory/cache candidates.
path = Path("v5/gcc_live_adapter.py")
text = path.read_text(encoding="utf-8")
old = '''                elif result.conflicts:\n                    self.identity_conflicts += 1'''
if text.count(old) != 2:
    raise RuntimeError(f"v5/gcc_live_adapter.py: expected 2 conflict counters, got {text.count(old)}")
text = text.replace(old, '''                elif result.conflicts:\n                    self._record_identity_conflict(result)''')
path.write_text(text, encoding="utf-8")

replace_once(
    "v5/gcc_live_adapter.py",
    '''        if exact is not None:\n            return GCCCatalogResolution(exact, MatchClass.EXACT_MATCH, False)\n        if len(strong) == 1:\n            return GCCCatalogResolution(\n                next(iter(strong.values())), MatchClass.STRONG_MATCH, False\n            )''',
    '''        if exact is not None:\n            self._catalog_index.upsert(\n                _lot_identity(exact), exact, source="completed_sales"\n            )\n            return GCCCatalogResolution(exact, MatchClass.EXACT_MATCH, False)\n        if len(strong) == 1:\n            selected_strong = next(iter(strong.values()))\n            self._catalog_index.upsert(\n                _lot_identity(selected_strong),\n                selected_strong,\n                source="completed_sales",\n            )\n            return GCCCatalogResolution(\n                selected_strong, MatchClass.STRONG_MATCH, False\n            )''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        exact_matches: list[watcher.Lot] = []\n        strong_matches: dict[tuple[object, ...], watcher.Lot] = {}\n        inventory_ambiguous = False\n        for candidate_identity, lot in self._by_name.get(canonical.card_name or "", ()):''',
    '''        exact_matches: list[watcher.Lot] = []\n        strong_matches: dict[tuple[object, ...], watcher.Lot] = {}\n        inventory_ambiguous = False\n        candidate_pool = list(self._by_name.get(canonical.card_name or "", ()))\n        seen_urls = {lot.url for _identity, lot in candidate_pool}\n        for cached in self._catalog_index.candidates(canonical.card_name):\n            if cached.lot.url in seen_urls:\n                continue\n            candidate_pool.append((cached.identity, cached.lot))\n            seen_urls.add(cached.lot.url)\n\n        for candidate_identity, lot in candidate_pool:''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        self._context = None\n\n    def __enter__(self) -> V4RenderedGCCHistorySource:''',
    '''        self._context = None\n        self._source = None\n\n    def __enter__(self) -> V4RenderedGCCHistorySource:''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''            page = self._context.new_page()\n            page.set_default_timeout(watcher.TEXT_TIMEOUT)\n            page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)\n            return V4RenderedGCCHistorySource(page)''',
    '''            page = self._context.new_page()\n            page.set_default_timeout(watcher.TEXT_TIMEOUT)\n            page.set_default_navigation_timeout(watcher.NAV_TIMEOUT)\n            self._source = V4RenderedGCCHistorySource(page)\n            return self._source''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        del exc_type, exc_value, traceback\n        if self._context is not None:\n            self._context.close()''',
    '''        del exc_type, exc_value, traceback\n        if self._source is not None:\n            self._source.persist_catalog_index()\n        if self._context is not None:\n            self._context.close()''',
)

# ---- Aggregate diagnostics: tell us exactly which identity fields conflict. ----
replace_once(
    "v5/live_raw_pipeline.py",
    '''    gcc_inventory_pages_requested: int = 0\n    gcc_identity_conflicts: int = 0\n    gcc_representative_exact: int = 0''',
    '''    gcc_inventory_pages_requested: int = 0\n    gcc_identity_conflicts: int = 0\n    gcc_identity_conflict_fields: Tuple[Tuple[str, int], ...] = ()\n    gcc_representative_exact: int = 0''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''    gcc_catalog_completed_sales_enabled: int = 0\n    gcc_catalog_search_failures: int = 0\n    gcc_records_with_grader: int = 0''',
    '''    gcc_catalog_completed_sales_enabled: int = 0\n    gcc_catalog_search_failures: int = 0\n    gcc_catalog_cache_entries_loaded: int = 0\n    gcc_catalog_cache_entries_current: int = 0\n    gcc_catalog_cache_added: int = 0\n    gcc_catalog_cache_updated: int = 0\n    gcc_catalog_cache_lookup_hits: int = 0\n    gcc_catalog_cache_load_failures: int = 0\n    gcc_catalog_cache_save_failures: int = 0\n    gcc_records_with_grader: int = 0''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''                gcc_identity_conflicts=getattr(\n                    gcc_source, "identity_conflicts", 0\n                ),\n                gcc_representative_exact=getattr(''',
    '''                gcc_identity_conflicts=getattr(\n                    gcc_source, "identity_conflicts", 0\n                ),\n                gcc_identity_conflict_fields=tuple(\n                    sorted(\n                        getattr(gcc_source, "identity_conflict_fields", {}).items()\n                    )\n                ),\n                gcc_representative_exact=getattr(''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''                gcc_catalog_search_failures=getattr(\n                    gcc_source, "catalog_search_failures", 0\n                ),\n                gcc_records_with_grader=getattr(''',
    '''                gcc_catalog_search_failures=getattr(\n                    gcc_source, "catalog_search_failures", 0\n                ),\n                gcc_catalog_cache_entries_loaded=getattr(\n                    gcc_source, "catalog_cache_entries_loaded", 0\n                ),\n                gcc_catalog_cache_entries_current=getattr(\n                    gcc_source, "catalog_cache_entries_current", 0\n                ),\n                gcc_catalog_cache_added=getattr(\n                    gcc_source, "catalog_cache_added", 0\n                ),\n                gcc_catalog_cache_updated=getattr(\n                    gcc_source, "catalog_cache_updated", 0\n                ),\n                gcc_catalog_cache_lookup_hits=getattr(\n                    gcc_source, "catalog_cache_lookup_hits", 0\n                ),\n                gcc_catalog_cache_load_failures=getattr(\n                    gcc_source, "catalog_cache_load_failures", 0\n                ),\n                gcc_catalog_cache_save_failures=getattr(\n                    gcc_source, "catalog_cache_save_failures", 0\n                ),\n                gcc_records_with_grader=getattr(''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''            f"identity conflicts: {summary.providers.gcc_identity_conflicts}",\n            (\n                "manual market validation required: "''',
    '''            f"identity conflicts: {summary.providers.gcc_identity_conflicts}",\n            (\n                "identity conflict fields: "\n                + (\n                    " | ".join(\n                        f"{field}: {count}"\n                        for field, count in summary.providers.gcc_identity_conflict_fields\n                    )\n                    or "none"\n                )\n            ),\n            (\n                "manual market validation required: "''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''            f"catalog search failures: {summary.providers.gcc_catalog_search_failures}",\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
    '''            f"catalog search failures: {summary.providers.gcc_catalog_search_failures}",\n            (\n                "catalog cache loaded/current: "\n                f"{summary.providers.gcc_catalog_cache_entries_loaded}/"\n                f"{summary.providers.gcc_catalog_cache_entries_current}"\n            ),\n            (\n                "catalog cache added/updated this run: "\n                f"{summary.providers.gcc_catalog_cache_added}/"\n                f"{summary.providers.gcc_catalog_cache_updated}"\n            ),\n            (\n                "catalog cache lookup hits: "\n                f"{summary.providers.gcc_catalog_cache_lookup_hits}"\n            ),\n            (\n                "catalog cache load/save failures: "\n                f"{summary.providers.gcc_catalog_cache_load_failures}/"\n                f"{summary.providers.gcc_catalog_cache_save_failures}"\n            ),\n            f"history cache hits: {summary.providers.gcc_history_cache_hits}",''',
)

# ---- Manual V5 diagnostic restores/saves the same GCC-only cache as daily refresh. ----
replace_once(
    ".github/workflows/v5-live-raw-pipeline-diagnostic.yml",
    '''      GCC_HISTORY_CURRENCY: "USD"\n      PRODUCT_RESEARCH_MODE: "MANUAL_VALIDATION_ONLY"''',
    '''      GCC_HISTORY_CURRENCY: "USD"\n      GCC_CATALOG_INDEX_FILE: gcc_catalog_index.json\n      PRODUCT_RESEARCH_MODE: "MANUAL_VALIDATION_ONLY"''',
)
replace_once(
    ".github/workflows/v5-live-raw-pipeline-diagnostic.yml",
    '''      - name: Set up Python\n        uses: actions/setup-python@v5''',
    '''      - name: Restore cumulative GCC catalogue\n        uses: actions/cache@v4\n        with:\n          path: gcc_catalog_index.json\n          key: v5-gcc-catalog-${{ github.run_id }}\n          restore-keys: |\n            v5-gcc-catalog-\n\n      - name: Set up Python\n        uses: actions/setup-python@v5''',
)

# ---- Deterministic adapter tests: no filesystem cache leakage + conflict field proof. ----
path = Path("tests_v5/test_gcc_live_adapter_matching.py")
text = path.read_text(encoding="utf-8")
text = text.replace(
    '''from v5.gcc_live_adapter import (\n    GCCCatalogResolution,\n    V4RenderedGCCHistorySource,\n)''',
    '''from v5.gcc_catalog_cache import GCCCatalogCandidate\nfrom v5.gcc_live_adapter import (\n    GCCCatalogResolution,\n    V4RenderedGCCHistorySource,\n)''',
    1,
)
anchor = '''class GCCRepresentativeSelectionTests(unittest.TestCase):\n    def _source(self, lots, catalog_resolver=None):'''
replacement = '''class _MemoryCatalogIndex:\n    entries_loaded = 0\n    current_entries = 0\n    added_this_run = 0\n    updated_this_run = 0\n    lookup_hits = 0\n    load_failures = 0\n    save_failures = 0\n\n    def __init__(self, candidates=()):\n        self._candidates = tuple(candidates)\n\n    def candidates(self, _card_name):\n        self.lookup_hits += int(bool(self._candidates))\n        return self._candidates\n\n    def upsert(self, *_args, **_kwargs):\n        return True\n\n    def save(self):\n        return None\n\n\nclass GCCRepresentativeSelectionTests(unittest.TestCase):\n    def _source(self, lots, catalog_resolver=None, catalog_index=None):'''
if text.count(anchor) != 1:
    raise RuntimeError("test helper anchor not found")
text = text.replace(anchor, replacement, 1)
old = '''            history_extractor=lambda *_args, **_kwargs: (),\n            catalog_resolver=catalog_resolver,\n        )'''
new = '''            history_extractor=lambda *_args, **_kwargs: (),\n            catalog_resolver=catalog_resolver,\n            catalog_index=catalog_index or _MemoryCatalogIndex(),\n        )'''
if text.count(old) != 1:
    raise RuntimeError("test source constructor anchor not found")
text = text.replace(old, new, 1)
old = '''        self.assertGreaterEqual(source.identity_conflicts, 1)\n        self.assertEqual(source.no_representative, 1)'''
new = '''        self.assertGreaterEqual(source.identity_conflicts, 1)\n        self.assertGreaterEqual(source.identity_conflict_fields["card_number"], 1)\n        self.assertEqual(source.no_representative, 1)'''
if text.count(old) != 1:
    raise RuntimeError("conflict assertion anchor not found")
text = text.replace(old, new, 1)
insert_before = '''    def test_public_catalogue_exact_fallback_can_rescue_missing_on_sale_rep(self):\n'''
cache_test = '''    def test_cumulative_cache_can_rescue_card_no_longer_on_sale(self):\n        cached_lot = _lot(set_name="Base Set", year=None)\n        cached_lot.source_type = "catalog_cache"\n        cached_identity = _target(year=None)\n        cache = _MemoryCatalogIndex(\n            (GCCCatalogCandidate(cached_identity, cached_lot),)\n        )\n\n        def should_not_search(_identity):\n            self.fail("public Explore fallback should not run on a safe cache hit")\n\n        source, opened, _bounds = self._source(\n            [], catalog_resolver=should_not_search, catalog_index=cache\n        )\n        source.fetch(_target(year=None))\n        self.assertEqual(source.representative_exact, 1)\n        self.assertEqual(source.live_calls, 1)\n        self.assertEqual(len(opened), 1)\n        self.assertEqual(cache.lookup_hits, 1)\n\n'''
if text.count(insert_before) != 1:
    raise RuntimeError("cache test insertion anchor not found")
text = text.replace(insert_before, cache_test + insert_before, 1)
path.write_text(text, encoding="utf-8")
