from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one occurrence, found {count}: {old[:100]!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_all_checked(path: str, old: str, new: str, expected_min: int = 1) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count < expected_min:
        raise RuntimeError(f"{path}: expected at least {expected_min} occurrences, found {count}: {old!r}")
    file_path.write_text(text.replace(old, new), encoding="utf-8")


# ---------------------------------------------------------------------------
# V4: preserve structured GCC grading metadata and recognize GCC graders.
# ---------------------------------------------------------------------------
replace_once(
    "watcher.py",
    'GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG")',
    'GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG", "SGC", "SFG", "SGS", "SCA", "TCC")',
)

replace_all_checked(
    "watcher.py",
    "PSA|PCA|CGC|BGS|BECKETT|CCC|CA|PG",
    "PSA|PCA|CGC|BGS|BECKETT|CCC|CA|PG|SGC|SFG|SGS|SCA|TCC",
    expected_min=2,
)
replace_all_checked(
    "watcher.py",
    "PSA|PCA|CCC|BGS|CGC|SGC|CA|PG",
    "PSA|PCA|CCC|BGS|CGC|SGC|CA|PG|SFG|SGS|SCA|TCC",
    expected_min=1,
)
replace_all_checked(
    "watcher.py",
    "PSA|PCA|CCC|BGS|CGC|SGC|Grade|Note|Gradation|Grading|",
    "PSA|PCA|CCC|BGS|CGC|SGC|SFG|SGS|SCA|TCC|Grade|Note|Gradation|Grading|",
    expected_min=1,
)

replace_once(
    "watcher.py",
    '''def _gcc_fixed_result_to_lot(\n    result: dict,\n    item_url: str,\n    coverage: CoverageAudit,\n) -> Optional[Lot]:''',
    '''def _gcc_fixed_result_to_lot(\n    result: dict,\n    item_url: str,\n    coverage: CoverageAudit,\n    *,\n    min_price: Optional[float] = MIN_PRICE,\n    max_price: Optional[float] = MAX_PRICE,\n) -> Optional[Lot]:''',
)
replace_once(
    "watcher.py",
    '''    if price < MIN_PRICE or price > MAX_PRICE:\n        coverage.record_terminal(item_url, ACCOUNT_EXCLUDED_BY_RULES)\n        return None\n\n    return Lot(''',
    '''    if min_price is not None and price < min_price:\n        coverage.record_terminal(item_url, ACCOUNT_EXCLUDED_BY_RULES)\n        return None\n    if max_price is not None and price > max_price:\n        coverage.record_terminal(item_url, ACCOUNT_EXCLUDED_BY_RULES)\n        return None\n\n    return Lot(''',
)
replace_once(
    "watcher.py",
    '''def collect_fixed_lots_from_api(\n    run_diagnostics: Optional[RunDiagnostics] = None,\n    *,\n    http_get=None,\n    page_size: int = GCC_FIXED_PAGE_SIZE,\n    max_pages: int = GCC_FIXED_MAX_PAGES,\n) -> list[Lot]:''',
    '''def collect_fixed_lots_from_api(\n    run_diagnostics: Optional[RunDiagnostics] = None,\n    *,\n    http_get=None,\n    page_size: int = GCC_FIXED_PAGE_SIZE,\n    max_pages: int = GCC_FIXED_MAX_PAGES,\n    min_price: Optional[float] = MIN_PRICE,\n    max_price: Optional[float] = MAX_PRICE,\n) -> list[Lot]:''',
)
replace_once(
    "watcher.py",
    '''        params = {\n            "sellingTypes": "FIXED_PRICE",\n            "categories": "Pokemon",\n            "itemTypes": "CARDS",\n            "minPriceInCents": round(MIN_PRICE * 100),\n            "maxPriceInCents": round(MAX_PRICE * 100),\n            "page": page_number,\n            "limit": page_size,\n            "includeCounts": "true" if page_number == 1 else "false",\n        }''',
    '''        params = {\n            "sellingTypes": "FIXED_PRICE",\n            "categories": "Pokemon",\n            "itemTypes": "CARDS",\n            "page": page_number,\n            "limit": page_size,\n            "includeCounts": "true" if page_number == 1 else "false",\n        }\n        if min_price is not None:\n            params["minPriceInCents"] = round(min_price * 100)\n        if max_price is not None:\n            params["maxPriceInCents"] = round(max_price * 100)''',
)
replace_once(
    "watcher.py",
    '                lot = _gcc_fixed_result_to_lot(result, item_url, coverage)',
    '''                lot = _gcc_fixed_result_to_lot(\n                    result,\n                    item_url,\n                    coverage,\n                    min_price=min_price,\n                    max_price=max_price,\n                )''',
)

replace_once(
    "watcher.py",
    '        lot.grader, lot.grade = parse_grader_grade(f"{lot.title}\\n{body}")',
    '''        # The public GCC inventory already exposes gradingCompany + grade.\n        # Treat that structured pair as authoritative for fixed listings instead\n        # of erasing it when the rendered item page omits grading metadata.\n        structured_grader = (lot.grader or "").strip().upper()\n        structured_grade_raw = (\n            str(lot.grade).strip() if lot.grade is not None else ""\n        )\n        parsed_grader, parsed_grade = parse_grader_grade(f"{lot.title}\\n{body}")\n        if structured_grader in GRADERS and structured_grade_raw:\n            lot.grader = structured_grader\n            lot.grade = (\n                validate_grade_value(\n                    structured_grade_raw,\n                    structured_grader,\n                    log_invalid=False,\n                )\n                or structured_grade_raw\n            )\n        elif structured_grader in GRADERS:\n            lot.grader = structured_grader\n            lot.grade = (\n                parsed_grade\n                if not parsed_grader or parsed_grader == structured_grader\n                else None\n            )\n        else:\n            lot.grader, lot.grade = parsed_grader, parsed_grade''',
)

replace_once(
    "gcc_history_shared.py",
    'HISTORY_GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG", "SGC")',
    'HISTORY_GRADERS = ("PSA", "PCA", "CGC", "BGS", "BECKETT", "CCC", "CA", "PG", "SGC", "SFG", "SGS", "SCA", "TCC")',
)

# ---------------------------------------------------------------------------
# V5: unbounded identity index + safe exact/unique-strong representative.
# ---------------------------------------------------------------------------
replace_once(
    "v5/gcc_live_adapter.py",
    '''Inventory is read from the public on-sale-items endpoint already used by V4.\nFor an exact identity present in that inventory, one normal authenticated GCC\nitem page is rendered and its sales-history text is parsed by the shared V4/V5\nextractor.  No private endpoint, stealth mode, persistence, or bypass is used.''',
    '''Inventory is read from the public on-sale-items endpoint already used by V4,\nwithout reusing V4's 0-100 EUR economic price window for identity lookup. For an\nexact identity, or one unique strong identity with no known conflict, one normal\nauthenticated GCC item page is rendered and its sales-history text is parsed by\nthe shared V4/V5 extractor. No private endpoint, stealth mode, persistence, or\nbypass is used.''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''GCC_V4_ACCESS_MECHANISM = (\n    "V4 public on-sale-items inventory + normal authenticated Playwright item page rendered history"\n)''',
    '''GCC_V4_ACCESS_MECHANISM = (\n    "V4 public on-sale-items identity index without economic price cap + normal authenticated Playwright item page rendered history"\n)''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        self.inventory_pages_requested = 0\n        self.identity_conflicts = 0\n        self.parsing = HistoricalParsingDiagnostics()''',
    '''        self.inventory_pages_requested = 0\n        self.identity_conflicts = 0\n        self.representative_exact = 0\n        self.representative_strong = 0\n        self.representative_ambiguous = 0\n        self.no_representative = 0\n        self.parsing = HistoricalParsingDiagnostics()''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        lots = tuple(\n            _call_without_v4_detail_logs(self._inventory_fetcher, diagnostics)\n        )\n        self.inventory_pages_requested = diagnostics.fixed_coverage.pages_requested\n        for lot in lots:\n            identity = _lot_identity(lot)\n            if not identity.minimum_identity_complete or not identity.card_name:\n                continue\n            self._by_name.setdefault(identity.card_name, []).append((identity, lot))''',
    '''        lots = tuple(\n            _call_without_v4_detail_logs(\n                self._inventory_fetcher,\n                diagnostics,\n                min_price=0.0,\n                max_price=None,\n            )\n        )\n        self.inventory_pages_requested = diagnostics.fixed_coverage.pages_requested\n        for lot in lots:\n            identity = _lot_identity(lot)\n            # Exact matching needs name+set+number, but a safe STRONG_MATCH can\n            # legitimately be name+number (or name+set with discriminator).\n            if not identity.card_name or not (identity.card_number or identity.set_name):\n                continue\n            self._by_name.setdefault(identity.card_name, []).append((identity, lot))''',
)
replace_once(
    "v5/gcc_live_adapter.py",
    '''        matches: list[watcher.Lot] = []\n        for candidate_identity, lot in self._by_name.get(canonical.card_name or "", ()):\n            result = match_identity(canonical, candidate_identity)\n            if result.match_class is MatchClass.EXACT_MATCH:\n                matches.append(lot)\n            elif result.conflicts:\n                self.identity_conflicts += 1\n        if not matches:\n            self._fetch_cache[canonical.key] = ()\n            return ()\n\n        # One exact page per identity is the minimum real mechanism.  Its\n        # rendered history already contains the comparable transactions.\n        inspected = _call_without_v4_detail_logs(\n            self._item_inspector,\n            self._page,\n            replace(matches[0]),\n            log_listing_errors=False,\n        )''',
    '''        exact_matches: list[watcher.Lot] = []\n        strong_matches: dict[tuple[object, ...], watcher.Lot] = {}\n        ambiguous_seen = False\n        for candidate_identity, lot in self._by_name.get(canonical.card_name or "", ()):\n            result = match_identity(canonical, candidate_identity)\n            if result.match_class is MatchClass.EXACT_MATCH:\n                exact_matches.append(lot)\n            elif result.match_class is MatchClass.STRONG_MATCH:\n                # Multiple listings of the same canonical collectible are not\n                # ambiguous; distinct strong identities are.\n                strong_matches.setdefault(candidate_identity.key, lot)\n            elif result.match_class is MatchClass.AMBIGUOUS:\n                ambiguous_seen = True\n            elif result.conflicts:\n                self.identity_conflicts += 1\n\n        selected: watcher.Lot | None = None\n        if exact_matches:\n            selected = exact_matches[0]\n            self.representative_exact += 1\n        elif len(strong_matches) == 1:\n            selected = next(iter(strong_matches.values()))\n            self.representative_strong += 1\n        elif len(strong_matches) > 1 or ambiguous_seen:\n            self.representative_ambiguous += 1\n        else:\n            self.no_representative += 1\n\n        if selected is None:\n            self._fetch_cache[canonical.key] = ()\n            return ()\n\n        # One representative page per identity is enough: its rendered history\n        # already contains the comparable transactions for that collectible.\n        inspected = _call_without_v4_detail_logs(\n            self._item_inspector,\n            self._page,\n            replace(selected),\n            log_listing_errors=False,\n        )''',
)

# Existing injected test inventory follows the new optional-bound signature.
replace_once(
    "tests_v5/test_gcc_live_adapter.py",
    '    def inventory(diagnostics):\n        diagnostics.fixed_coverage.pages_requested = 1',
    '    def inventory(diagnostics, **_bounds):\n        diagnostics.fixed_coverage.pages_requested = 1',
)

# Expose representative-selection counters in aggregate V5 diagnostics.
replace_once(
    "v5/live_raw_pipeline.py",
    '''    gcc_inventory_pages_requested: int = 0\n    gcc_identity_conflicts: int = 0\n    gcc_records_with_grader: int = 0''',
    '''    gcc_inventory_pages_requested: int = 0\n    gcc_identity_conflicts: int = 0\n    gcc_representative_exact: int = 0\n    gcc_representative_strong: int = 0\n    gcc_representative_ambiguous: int = 0\n    gcc_no_representative: int = 0\n    gcc_records_with_grader: int = 0''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''                gcc_identity_conflicts=getattr(\n                    gcc_source, "identity_conflicts", 0\n                ),\n                gcc_records_with_grader=getattr(''',
    '''                gcc_identity_conflicts=getattr(\n                    gcc_source, "identity_conflicts", 0\n                ),\n                gcc_representative_exact=getattr(\n                    gcc_source, "representative_exact", 0\n                ),\n                gcc_representative_strong=getattr(\n                    gcc_source, "representative_strong", 0\n                ),\n                gcc_representative_ambiguous=getattr(\n                    gcc_source, "representative_ambiguous", 0\n                ),\n                gcc_no_representative=getattr(\n                    gcc_source, "no_representative", 0\n                ),\n                gcc_records_with_grader=getattr(''',
)
replace_once(
    "v5/live_raw_pipeline.py",
    '''            (\n                "public inventory pages requested: "\n                f"{summary.providers.gcc_inventory_pages_requested}"\n            ),\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
    '''            (\n                "public inventory pages requested: "\n                f"{summary.providers.gcc_inventory_pages_requested}"\n            ),\n            f"representative exact: {summary.providers.gcc_representative_exact}",\n            f"representative strong: {summary.providers.gcc_representative_strong}",\n            (\n                "representative ambiguous: "\n                f"{summary.providers.gcc_representative_ambiguous}"\n            ),\n            f"no representative: {summary.providers.gcc_no_representative}",\n            f"cache hits: {summary.providers.gcc_history_cache_hits}",''',
)

# ---------------------------------------------------------------------------
# Focused regression tests.
# ---------------------------------------------------------------------------
Path("tests/test_v4_grader_preservation.py").write_text(
    r'''import unittest

import watcher
from gcc_history_shared import parse_historical_grade


class _Locator:
    def __init__(self, text):
        self._text = text

    @property
    def first(self):
        return self

    def inner_text(self, timeout=None):
        return self._text


class _Page:
    def __init__(self, body, heading=""):
        self.body = body
        self.heading = heading

    def goto(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def locator(self, selector):
        if selector == "body":
            return _Locator(self.body)
        if selector == "h1":
            return _Locator(self.heading)
        raise AssertionError(selector)


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class V4StructuredGraderTests(unittest.TestCase):
    def test_requested_graders_are_distinct_supported_graders(self):
        for grader in ("SFG", "SGS", "SCA", "TCC"):
            with self.subTest(grader=grader):
                self.assertIn(grader, watcher.GRADERS)
                self.assertEqual(
                    watcher.parse_grader_grade(f"{grader} 9.5 Example Card"),
                    (grader, "9.5"),
                )
                evidence = parse_historical_grade(f"{grader} 9.5 Example Card\n25 €")
                self.assertEqual(evidence.grader, grader)
                self.assertEqual(evidence.grade, "9.5")

    def test_inspection_preserves_structured_api_grader_and_grade(self):
        lot = watcher.Lot(
            url="https://gradedcardcenter.com/item/fixture",
            title="SFG 9.5 Mega Latias Ex",
            current_price=35.0,
            source_type="fixed",
            grader="SFG",
            grade="9.5",
            card_set="Mega Symphonia",
            card_number="079/063",
            language="Japanese",
        )
        page = _Page(
            "Description\nArticle\nGradation\nDétails\nCatégorie\nPokemon\n"
            "Réference\n#079/063\nHistorique des ventes\nPSA 10 Mega Latias Ex\n18 €"
        )
        inspected = watcher.inspect_item(page, lot)
        self.assertEqual(inspected.grader, "SFG")
        self.assertEqual(inspected.grade, "9.5")
        self.assertEqual(watcher.extract_card_identity(inspected)["core"], "Mega Latias Ex")

    def test_unbounded_identity_inventory_omits_max_price_and_keeps_expensive_card(self):
        captured = []
        payload = {
            "info": {"currentPage": 1, "nextPage": None, "counts": {"total": 1}},
            "results": [
                {
                    "id": "fixture-expensive",
                    "priceInCents": 50000,
                    "item": {
                        "title": "PSA 10 Charizard",
                        "gradingCompany": "PSA",
                        "grade": "10",
                        "collectible": {
                            "category": "Pokemon",
                            "language": "English",
                            "yearOfDistribution": "1999",
                            "extension": "Base",
                            "set": "Base Set",
                            "reference": "4/102",
                            "type": "CARDS",
                        },
                    },
                }
            ],
        }

        def get(_url, *, params, **_kwargs):
            captured.append(dict(params))
            return _Response(payload)

        lots = watcher.collect_fixed_lots_from_api(
            http_get=get,
            max_pages=2,
            min_price=0.0,
            max_price=None,
        )
        self.assertEqual(len(lots), 1)
        self.assertEqual(lots[0].current_price, 500.0)
        self.assertNotIn("maxPriceInCents", captured[0])
        self.assertEqual(captured[0]["minPriceInCents"], 0)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

Path("tests_v5/test_gcc_live_adapter_matching.py").write_text(
    r'''import unittest
from dataclasses import replace

import watcher
from v5.gcc_live_adapter import V4RenderedGCCHistorySource
from v5.market_values.gcc_history.models import CanonicalCollectible


def _lot(*, set_name="", year=None, number="4/102"):
    return watcher.Lot(
        url=f"https://gradedcardcenter.com/item/{set_name or 'missing'}-{year or 'none'}-{number.replace('/', '-')}",
        title="PSA 10 Charizard",
        current_price=500.0,
        source_type="fixed",
        grader="PSA",
        grade="10",
        card_set=set_name,
        card_number=number,
        language="English",
        year=year,
        set_family=set_name,
    )


def _target(*, year=None):
    return CanonicalCollectible(
        card_name="charizard",
        set_name="base set",
        card_number="4/102",
        language="english",
        year=year,
        set_family="base set",
        category="pokemon",
    )


class GCCRepresentativeSelectionTests(unittest.TestCase):
    def _source(self, lots):
        opened = []
        bounds = []

        def inventory(diagnostics, **kwargs):
            diagnostics.fixed_coverage.pages_requested = 3
            bounds.append(kwargs)
            return tuple(lots)

        def inspect(_page, value, *, log_listing_errors=True):
            self.assertFalse(log_listing_errors)
            opened.append(value.url)
            return replace(value, body="Historique des ventes", inspection_error="")

        source = V4RenderedGCCHistorySource(
            object(),
            inventory_fetcher=inventory,
            item_inspector=inspect,
            history_extractor=lambda *_args, **_kwargs: (),
        )
        return source, opened, bounds

    def test_unique_strong_match_is_accepted(self):
        source, opened, bounds = self._source([_lot(set_name="", year=1999)])
        source.fetch(_target(year=1999))
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(source.representative_exact, 0)
        self.assertEqual(source.representative_strong, 1)
        self.assertEqual(source.representative_ambiguous, 0)
        self.assertEqual(source.no_representative, 0)
        self.assertEqual(bounds, [{"min_price": 0.0, "max_price": None}])

    def test_multiple_distinct_strong_matches_are_rejected_as_ambiguous(self):
        source, opened, _bounds = self._source(
            [_lot(set_name="", year=1999), _lot(set_name="", year=2000)]
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 0)
        self.assertEqual(opened, [])
        self.assertEqual(source.representative_strong, 0)
        self.assertEqual(source.representative_ambiguous, 1)
        self.assertEqual(source.no_representative, 0)

    def test_conflict_never_opens_page_and_counts_no_representative(self):
        source, opened, _bounds = self._source([_lot(set_name="Base Set", number="5/102")])
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 0)
        self.assertEqual(opened, [])
        self.assertGreaterEqual(source.identity_conflicts, 1)
        self.assertEqual(source.no_representative, 1)

    def test_exact_match_has_priority(self):
        source, opened, _bounds = self._source(
            [_lot(set_name="Base Set", year=None), _lot(set_name="", year=1999)]
        )
        source.fetch(_target(year=None))
        self.assertEqual(source.live_calls, 1)
        self.assertEqual(len(opened), 1)
        self.assertEqual(source.representative_exact, 1)
        self.assertEqual(source.representative_strong, 0)


if __name__ == "__main__":
    unittest.main()
''',
    encoding="utf-8",
)

print("one-shot V4/V5 patch applied")
