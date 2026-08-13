from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as mm


NOW = datetime(2026, 8, 12, 8, 0, tzinfo=timezone.utc)


def lot(
    *,
    name="Charizard",
    reference="4/102",
    language="English",
    grader="PSA",
    grade="8",
    price=40.0,
    series="Base Set",
):
    return watcher.Lot(
        url="https://gradedcardcenter.com/item/test-card",
        title=name,
        current_price=price,
        source_type="fixed",
        grader=grader,
        grade=grade,
        card_number=reference,
        card_set=series,
        language=language,
        body=(
            "Catégorie: Pokémon\n"
            f"Référence: #{reference}\n"
            f"Série: {series}\n"
            f"Langue: {language}\n"
            "Article Gradation Détails\n"
            f"Société de gradation: {grader}\n"
            f"Note: {grade}\n"
        ),
    )


def tcgdex_card(
    *,
    card_id="base1-4",
    name="Charizard",
    local_id="4",
    set_id="base1",
    set_name="Base Set",
    official=102,
    total=102,
    variants=None,
    pricing=None,
):
    return {
        "id": card_id,
        "name": name,
        "localId": local_id,
        "set": {
            "id": set_id,
            "name": set_name,
            "cardCount": {"official": official, "total": total},
        },
        "variants": variants
        or {"normal": False, "holo": True, "reverse": False, "firstEdition": False},
        "pricing": pricing or {},
    }


def market_estimate(low=90, central=100, high=110):
    return watcher.MarketEstimate(
        low=low,
        central=central,
        high=high,
        kept_comparables=[],
        rejected_outliers=[],
        recent_90_count=0,
        dated_count=0,
        liquidity="moyenne",
        dispersion="faible",
        confidence="moyenne",
        adaptive_discount_pct=30,
        rationale="external aggregate",
        source_counts={"poketrace": 5},
        exact_grade_count=5,
        same_grader_count=5,
        source_consistent=True,
    )


class PsaProductionScopeTests(unittest.TestCase):
    def test_psa_scope_is_8_8_5_9_and_10_only(self):
        for grade in ("8", "8.5", "9", "10"):
            self.assertTrue(mm.psa_grade_in_production_scope(lot(grade=grade)))
        for grade in ("1", "6", "7", "7.5", "9.5"):
            self.assertFalse(mm.psa_grade_in_production_scope(lot(grade=grade)))

    def test_non_psa_grade_is_unchanged(self):
        self.assertTrue(
            mm.psa_grade_in_production_scope(
                lot(grader="BGS", grade="7")
            )
        )

    def test_scope_filter_accounts_psa_below_8(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        target = lot(grade="7")
        with patch.object(mm, "_ORIGINAL_IS_VALID_POKEMON_CARD", return_value=True):
            self.assertFalse(mm.scoped_is_valid_pokemon_card(target))
        self.assertEqual(mm._DIAGNOSTICS.psa_below_8_excluded, 1)


class TCGdexCanonicalIdentityTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        mm.clear_tcgdex_cache()

    def test_exact_name_and_full_number_resolve_unique_card(self):
        target = lot()
        detail = tcgdex_card()
        def mock_get(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "base1-4")
        self.assertEqual(result.set_id, "base1")
        self.assertTrue(result.unique_name_number)

    def test_same_name_and_number_multiple_sets_is_ambiguous_without_exact_set(self):
        target = lot(series="Unknown GCC label")
        a = tcgdex_card(card_id="a-4", set_id="a", set_name="Set A")
        b = tcgdex_card(card_id="b-4", set_id="b", set_name="Set B")
        def mock_get(url, params=None, timeout=None):
            if "/cards/a-4" in url:
                return 200, a, {}
            if "/cards/b-4" in url:
                return 200, b, {}
            if params and params.get("localId") == "eq:4":
                return 200, [
                    {"id": "a-4", "name": "Charizard", "localId": "4"},
                    {"id": "b-4", "name": "Charizard", "localId": "4"},
                ], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "AMBIGUOUS")

    def test_denominator_conflict_never_resolves(self):
        target = lot(reference="4/130")
        detail = tcgdex_card(official=102, total=102)
        def mock_get(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if "/sets" in url:
                return 200, [{"id": "base1", "name": "Base Set"}], {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "NO_MATCH")

    def test_canonical_enrichment_does_not_replace_listing_title(self):
        target = lot(name="Charizard")
        result = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            reason="exact",
        )
        mm._attach_canonical_to_lot(target, result)
        self.assertEqual(target.title, "Charizard")
        self.assertEqual(target.card_set, "Base Set")
        self.assertEqual(target.set_family, "base1")

    def test_padded_card_number_matches_unpadded_tcgdex_card(self):
        target = lot(reference="#004/102")
        detail = tcgdex_card(local_id="4", official=102, total=102)
        def mock_get(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get):
            result = mm.resolve_tcgdex_card(target)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.local_id, "4")
        self.assertEqual(result.full_number, "4/102")

    def test_canonical_from_lot_memory_cache_and_no_duplicate_network_calls(self):
        target = lot(reference="4/102")
        detail = tcgdex_card(local_id="4", official=102, total=102)
        def mock_get(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get) as mock_get_fn:
            canonical1 = mm.resolve_tcgdex_card(target)
            mm._attach_canonical_to_lot(target, canonical1)
            canonical2 = mm._canonical_from_lot(target)
            self.assertEqual(canonical1.status, "EXACT")
            self.assertEqual(canonical2.status, "EXACT")
            self.assertEqual(mock_get_fn.call_count, 4)  # 3 localId queries (4, 004, 04) + 1 detail fetch

        # Test non-match lot caching
        target_nomatch = lot(reference="999/102", name="NonExistentCard")
        with patch.object(mm, "_json_get", return_value=(200, [], {})) as mock_get_nomatch:
            res1 = mm.resolve_tcgdex_card(target_nomatch)
            mm._attach_canonical_to_lot(target_nomatch, res1)
            res2 = mm._canonical_from_lot(target_nomatch)
            self.assertEqual(res1.status, "NO_MATCH")
            self.assertEqual(res2.status, "NO_MATCH")
            # First resolution queries 1 numeric representation (999 has no padding variants) + 1 sets search = 2 calls. Second reuses lot cache = 0 additional calls.
            self.assertEqual(mock_get_nomatch.call_count, 2)

    def test_cache_key_denominator_partitioning(self):
        # 1. Cache EXACT 004/102
        target1 = lot(reference="#004/102")
        detail = tcgdex_card(local_id="4", official=102, total=102)
        def mock_get1(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get1):
            res1 = mm.resolve_tcgdex_card(target1)
        self.assertEqual(res1.status, "EXACT")

        # 2. Query 4/102 -> safe cache reuse (0 network calls)
        target2 = lot(reference="4/102")
        with patch.object(mm, "_json_get", side_effect=AssertionError("Should use cache")):
            res2 = mm.resolve_tcgdex_card(target2)
        self.assertEqual(res2.status, "EXACT")
        self.assertEqual(res2.card_id, "base1-4")

        # 3. Query 4/130 -> MUST NOT reuse cache, must make network call and fail on denominator
        target3 = lot(reference="4/130")
        with patch.object(mm, "_json_get", side_effect=mock_get1) as mock_get3:
            res3 = mm.resolve_tcgdex_card(target3)
        self.assertEqual(res3.status, "NO_MATCH")
        self.assertTrue(mock_get3.called)

        # 4. Query 4/999 -> MUST NOT reuse cache, must make network call
        target4 = lot(reference="4/999")
        with patch.object(mm, "_json_get", return_value=(200, [], {})) as mock_get4:
            res4 = mm.resolve_tcgdex_card(target4)
        self.assertEqual(res4.status, "NO_MATCH")
        self.assertTrue(mock_get4.called)

    def test_tcgdex_transient_http_errors_never_cached_as_no_match(self):
        target = lot(reference="4/102")

        # 1. /cards HTTP 429 -> ERROR, not in cache
        mm.clear_tcgdex_cache()
        with patch.object(mm, "_json_get", return_value=(429, {}, {})):
            res_429 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_429.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # 2. /cards HTTP 500 -> ERROR, not in cache
        mm.clear_tcgdex_cache()
        with patch.object(mm, "_json_get", return_value=(500, {}, {})):
            res_500 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_500.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # 3. card-detail HTTP 500 -> ERROR, not in cache
        mm.clear_tcgdex_cache()
        def mock_get_detail_500(url, params=None, timeout=None):
            if "/cards/" in url:
                return 500, {}, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_detail_500):
            res_det_500 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_det_500.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # 4. /sets HTTP 500 when needed -> ERROR, not in cache
        mm.clear_tcgdex_cache()
        def mock_get_sets_500(url, params=None, timeout=None):
            if "/sets" in url:
                return 500, {}, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_sets_500):
            res_sets_500 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_sets_500.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # 5. Next retry succeeds -> EXACT and cached
        detail = tcgdex_card(local_id="4", official=102, total=102)
        def mock_get_ok(url, params=None, timeout=None):
            if "/cards/" in url:
                return 200, detail, {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "base1-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_ok):
            res_ok = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_ok.status, "EXACT")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 1)

        # 6. Clean 200 empty responses -> NO_MATCH and cached
        mm.clear_tcgdex_cache()
        non_existent = lot(name="UnknownCard", reference="999/100")
        with patch.object(mm, "_json_get", return_value=(200, [], {})):
            res_clean_nomatch = mm.resolve_tcgdex_card(non_existent)
        self.assertEqual(res_clean_nomatch.status, "NO_MATCH")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 1)

    def test_tcgdex_partial_detail_failure_fails_closed_and_disambiguates_on_retry(self):
        briefs = [
            {"id": "base1-4", "name": "Charizard", "localId": "4"},
            {"id": "base2-4", "name": "Charizard", "localId": "4"},
        ]
        detail_base1 = tcgdex_card(card_id="base1-4", set_id="base1", set_name="Base Set", local_id="4", official=102, total=102)
        detail_base2 = tcgdex_card(card_id="base2-4", set_id="base2", set_name="Base Set 2", local_id="4", official=130, total=130)

        # Case A: First detail 200, second detail 500 => ERROR (not EXACT), 0 cache entries
        mm.clear_tcgdex_cache()
        target_no_set = lot(name="Charizard", reference="4", series="")
        def mock_get_a(url, params=None, timeout=None):
            if "/cards/base1-4" in url:
                return 200, detail_base1, {}
            if "/cards/base2-4" in url:
                return 500, {}, {}
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_a):
            res_a = mm.resolve_tcgdex_card(target_no_set)
        self.assertEqual(res_a.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # Case B: First detail 200, second detail 429 => ERROR (not EXACT), 0 cache entries
        mm.clear_tcgdex_cache()
        def mock_get_b(url, params=None, timeout=None):
            if "/cards/base1-4" in url:
                return 200, detail_base1, {}
            if "/cards/base2-4" in url:
                return 429, {}, {}
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_b):
            res_b = mm.resolve_tcgdex_card(target_no_set)
        self.assertEqual(res_b.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # Case C: Retry when both details succeed, no exact set discriminator in listing => AMBIGUOUS, cached
        mm.clear_tcgdex_cache()
        def mock_get_c(url, params=None, timeout=None):
            if "/cards/base1-4" in url:
                return 200, detail_base1, {}
            if "/cards/base2-4" in url:
                return 200, detail_base2, {}
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_c):
            res_c = mm.resolve_tcgdex_card(target_no_set)
        self.assertEqual(res_c.status, "AMBIGUOUS")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 1)

        # Case D: Retry when both details succeed, listing specifies "Base Set" => EXACT for base1-4, cached
        mm.clear_tcgdex_cache()
        target_base_set = lot(name="Charizard", reference="4", series="Base Set")
        with patch.object(mm, "_json_get", side_effect=mock_get_c):
            res_d = mm.resolve_tcgdex_card(target_base_set)
        self.assertEqual(res_d.status, "EXACT")
        self.assertEqual(res_d.card_id, "base1-4")
        self.assertEqual(res_d.set_id, "base1")
        self.assertEqual(res_d.set_name, "Base Set")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 1)

    def test_tcgdex_detail_404_treated_as_unresolved_error_never_exact(self):
        # BLOCKER 1 regression: detail 404 for discovered brief must not manufacture uniqueness
        briefs = [
            {"id": "base1-4", "name": "Charizard", "localId": "4"},
            {"id": "base2-4", "name": "Charizard", "localId": "4"},
        ]
        detail_base1 = tcgdex_card(card_id="base1-4", set_id="base1", set_name="Base Set", local_id="4", official=102, total=102)
        mm.clear_tcgdex_cache()
        target = lot(name="Charizard", reference="4", series="")
        def mock_get_404(url, params=None, timeout=None):
            if "/cards/base1-4" in url:
                return 200, detail_base1, {}
            if "/cards/base2-4" in url:
                return 404, {}, {}
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_get_404):
            res = mm.resolve_tcgdex_card(target)
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

    def test_tcgdex_numeric_queries_union_candidates(self):
        # BLOCKER 2 regression: 004 returns candidate A, 4 returns candidate B
        detail_a = tcgdex_card(card_id="a-004", set_id="set-a", set_name="Set A", local_id="004", official=100, total=100)
        detail_b = tcgdex_card(card_id="b-4", set_id="set-b", set_name="Set B", local_id="4", official=100, total=100)
        def mock_get_union(url, params=None, timeout=None):
            if "/cards/a-004" in url:
                return 200, detail_a, {}
            if "/cards/b-4" in url:
                return 200, detail_b, {}
            if params and params.get("localId") == "eq:004":
                return 200, [{"id": "a-004", "name": "Charizard", "localId": "004"}], {}
            if params and params.get("localId") == "eq:4":
                return 200, [{"id": "b-4", "name": "Charizard", "localId": "4"}], {}
            return 200, [], {}

        # Listing has no set discriminator => AMBIGUOUS
        mm.clear_tcgdex_cache()
        target_no_set = lot(name="Charizard", reference="004/100", series="")
        with patch.object(mm, "_json_get", side_effect=mock_get_union):
            res_amb = mm.resolve_tcgdex_card(target_no_set)
        self.assertEqual(res_amb.status, "AMBIGUOUS")

        # Listing specifies Set A => EXACT A
        mm.clear_tcgdex_cache()
        target_set_a = lot(name="Charizard", reference="004/100", series="Set A")
        with patch.object(mm, "_json_get", side_effect=mock_get_union):
            res_exact = mm.resolve_tcgdex_card(target_set_a)
        self.assertEqual(res_exact.status, "EXACT")
        self.assertEqual(res_exact.card_id, "a-004")
        self.assertEqual(res_exact.set_name, "Set A")

    def test_tcgdex_search_endpoints_404_fail_closed_and_not_cached(self):
        # 1. /cards search 404 => ERROR/retryable, not clean NO_MATCH, no cache pollution
        mm.clear_tcgdex_cache()
        target = lot(name="Charizard", reference="4/100")
        with patch.object(mm, "_json_get", return_value=(404, {}, {})):
            res_cards_404 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_cards_404.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

        # 2. /sets search 404 => ERROR/retryable, not clean NO_MATCH, no cache pollution
        mm.clear_tcgdex_cache()
        def mock_sets_404(url, params=None, timeout=None):
            if "/sets" in url:
                return 404, {}, {}
            return 200, [], {}
        with patch.object(mm, "_json_get", side_effect=mock_sets_404):
            res_sets_404 = mm.resolve_tcgdex_card(target)
        self.assertEqual(res_sets_404.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)

    def test_tcgdex_historical_truncation_bug_regression_6_briefs(self):
        # True regression for old [:5] truncation bug:
        # Briefs 1-5: only candidate 1 (Set 1) validates (candidates 2-5 are invalid, e.g. name mismatch).
        # Brief 6: candidate 6 (Set 6) ALSO validates.
        # Old [:5] would only see candidate 1 and manufacture EXACT.
        # New complete logic inspects all 6, sees Candidate 1 + Candidate 6, and returns AMBIGUOUS.
        briefs = [
            {"id": f"set{i}-4", "name": "Charizard", "localId": "4"}
            for i in range(1, 7)
        ]
        detail_valid_1 = tcgdex_card(card_id="set1-4", set_id="set1", set_name="Set 1", name="Charizard", local_id="4", official=100, total=100)
        detail_invalid_2 = tcgdex_card(card_id="set2-4", set_id="set2", set_name="Set 2", name="DifferentCardName", local_id="4", official=100, total=100)
        detail_invalid_3 = tcgdex_card(card_id="set3-4", set_id="set3", set_name="Set 3", name="DifferentCardName", local_id="4", official=100, total=100)
        detail_invalid_4 = tcgdex_card(card_id="set4-4", set_id="set4", set_name="Set 4", name="DifferentCardName", local_id="4", official=100, total=100)
        detail_invalid_5 = tcgdex_card(card_id="set5-4", set_id="set5", set_name="Set 5", name="DifferentCardName", local_id="4", official=100, total=100)
        detail_valid_6 = tcgdex_card(card_id="set6-4", set_id="set6", set_name="Set 6", name="Charizard", local_id="4", official=100, total=100)

        details_map = {
            "set1-4": detail_valid_1,
            "set2-4": detail_invalid_2,
            "set3-4": detail_invalid_3,
            "set4-4": detail_invalid_4,
            "set5-4": detail_invalid_5,
            "set6-4": detail_valid_6,
        }

        def mock_get_truncation(url, params=None, timeout=None):
            for card_id, det in details_map.items():
                if f"/cards/{card_id}" in url:
                    return 200, det, {}
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}

        mm.clear_tcgdex_cache()
        target = lot(name="Charizard", reference="4/100", series="")
        with patch.object(mm, "_json_get", side_effect=mock_get_truncation):
            res = mm.resolve_tcgdex_card(target)
        self.assertEqual(res.status, "AMBIGUOUS")

    def test_tcgdex_explicit_cap_exceeded_11_briefs_is_ambiguous(self):
        # 11 unique briefs returned (>10 explicit cap) => immediately AMBIGUOUS without detail fetching
        briefs = [
            {"id": f"set{i}-4", "name": "Charizard", "localId": "4"}
            for i in range(1, 12)
        ]
        def mock_get_11(url, params=None, timeout=None):
            if "/cards/" in url:
                raise AssertionError("Should not fetch details when brief count > 10")
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}

        mm.clear_tcgdex_cache()
        target = lot(name="Charizard", reference="4/100", series="")
        with patch.object(mm, "_json_get", side_effect=mock_get_11):
            res = mm.resolve_tcgdex_card(target)
        self.assertEqual(res.status, "AMBIGUOUS")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 1)

    def test_tcgdex_malformed_discovered_brief_fails_closed(self):
        # Discovered brief with missing/empty id must fail-closed to ERROR
        briefs = [
            {"name": "Charizard", "localId": "4"},  # missing id
        ]
        def mock_get_malformed(url, params=None, timeout=None):
            if params and params.get("localId") == "eq:4":
                return 200, briefs, {}
            return 200, [], {}

        mm.clear_tcgdex_cache()
        target = lot(name="Charizard", reference="4/100", series="")
        with patch.object(mm, "_json_get", side_effect=mock_get_malformed):
            res = mm.resolve_tcgdex_card(target)
        self.assertEqual(res.status, "ERROR")
        self.assertEqual(len(mm._TCGDEX_MEMORY_CACHE), 0)


class RawMarketSignalTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()

    def test_exact_holo_uses_variant_specific_raw_prices(self):
        target = lot()
        target.variant = "Holo"
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "cardmarket": {
                    "trend-holo": 100,
                    "avg7-holo": 98,
                    "avg30-holo": 96,
                },
                "tcgplayer": {
                    "unit": "USD",
                    "holo": {"marketPrice": 110},
                },
            },
            variants={"normal": False, "holo": True, "reverse": False},
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.1):
            signal = mm.raw_market_signal(target, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.variant, "holo")
        self.assertIn("Cardmarket", signal.sources)
        self.assertIn("TCGplayer", signal.sources)

    def test_tcgplayer_camelcase_and_unnormalized_pricing_keys(self):
        target = lot()
        target.variant = "Reverse"
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "tcgplayer": {
                    "unit": "USD",
                    "reverseHolofoil": {"marketPrice": 77.0},
                },
            },
            variants={"normal": False, "holo": False, "reverse": True},
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.0):
            signal = mm.raw_market_signal(target, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.variant, "reverse")
        self.assertIn("TCGplayer", signal.sources)
        self.assertAlmostEqual(signal.central, 77.0)

    def test_ambiguous_variant_uses_conservative_manual_envelope(self):
        target = lot()
        canonical = mm.CanonicalCard(
            "EXACT",
            card_id="x",
            set_id="s",
            set_name="Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            pricing={
                "cardmarket": {"trend": 50, "trend-holo": 100},
                "tcgplayer": {
                    "unit": "USD",
                    "normal": {"marketPrice": 55},
                    "holo": {"marketPrice": 110},
                },
            },
            variants={"normal": True, "holo": True, "reverse": False},
        )
        with patch.object(mm, "_usd_per_eur", return_value=1.0):
            signal = mm.raw_market_signal(target, canonical)
        self.assertIsNotNone(signal)
        self.assertEqual(signal.variant, "AMBIGUOUS_CONSERVATIVE_ENVELOPE")
        self.assertLess(signal.low, signal.central)
        self.assertEqual(mm._DIAGNOSTICS.raw_signal_variant_ambiguous, 1)

    def test_raw_signal_never_constructs_graded_opportunity(self):
        target = lot(price=20)
        signal = mm.RawMarketSignal(
            60, 70, 80, "EUR", ("Cardmarket",), "holo", "manual"
        )
        review, gap = mm._should_manual_review(target, signal)
        self.assertTrue(review)
        self.assertGreater(gap, 60)


class PokeTraceExactGradedTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        self.target = lot()
        self.canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            unique_name_number=True,
        )

    def _responses(self, tier="PSA_8", sale_count=5, game="pokemon"):
        return [
            (
                200,
                {
                    "data": {
                        "active": True,
                        "user": {"plan": "Pro", "remaining": 9000, "limit": 10000},
                    }
                },
                {},
            ),
            (
                200,
                {
                    "data": [
                        {
                            "id": "pt-1",
                            "name": "Charizard",
                            "cardNumber": "4/102",
                            "set": {"name": "Base Set", "slug": "base-set"},
                            "variant": "Holofoil",
                            "productType": "single",
                            "game": game,
                            "currency": "USD",
                            "prices": {
                                "ebay": {
                                    tier: {
                                        "avg": 100,
                                        "low": 90,
                                        "high": 110,
                                        "saleCount": sale_count,
                                        "approxSaleCount": True,
                                    }
                                }
                            },
                        }
                    ]
                },
                {},
            ),
        ]

    def test_exact_psa8_poketrace_can_be_strong(self):
        budget = mm.RequestBudget()
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_paced_poketrace_get", side_effect=self._responses()
        ), patch.object(mm, "_usd_per_eur", return_value=1.0):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_MATCHED)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_STRONG)
        self.assertEqual(evidence.source, "poketrace")
        self.assertEqual(evidence.estimate.central, 100)

    def test_poketrace_two_sales_stays_weak_by_default(self):
        budget = mm.RequestBudget()
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(
            mm, "_paced_poketrace_get",
            side_effect=self._responses(sale_count=2),
        ), patch.object(mm, "_usd_per_eur", return_value=1.0):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertEqual(evidence.status, watcher.EXTERNAL_CLEAN_INSUFFICIENT)
        self.assertEqual(evidence.strength, watcher.EVIDENCE_WEAK)

    def test_psa_half_grade_tier_uses_underscore(self):
        self.target.grade = "8.5"
        self.assertEqual(mm._poketrace_grade_tier(self.target), "PSA_8_5")

    def test_french_us_record_is_not_exact_graded_evidence(self):
        self.target.language = "French"
        candidate = {
            "name": "Charizard",
            "cardNumber": "4/102",
            "set": {"name": "Base Set"},
            "variant": "Holofoil",
            "productType": "single",
            "game": "pokemon",
        }
        self.assertFalse(
            mm._candidate_exact_for_canonical(
                self.target, self.canonical, candidate
            )
        )

    def test_free_plan_never_creates_graded_evidence(self):
        budget = mm.RequestBudget()
        response = (
            200,
            {
                "data": {
                    "active": True,
                    "user": {"plan": "Free", "remaining": 200, "limit": 250},
                }
            },
            {},
        )
        with patch.object(mm, "POKETRACE_ENABLED", True), patch.object(
            mm, "POKETRACE_API_KEY", "test-key"
        ), patch.object(mm, "_paced_poketrace_get", return_value=response):
            evidence = mm._poketrace_evidence(
                self.target, self.canonical, budget, NOW
            )
        self.assertNotEqual(evidence.strength, watcher.EVIDENCE_STRONG)


class MultiMarketIntegrationTests(unittest.TestCase):
    def setUp(self):
        mm._DIAGNOSTICS = mm.MultiMarketDiagnostics()
        mm.clear_tcgdex_cache()
        self.target = lot(price=40)
        self.gcc = watcher.GccMarketEvidence(
            self.target,
            [],
            None,
            None,
            watcher.GCC_BRANCH_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            rejection="historique vide",
            rejection_category=watcher.REJECTION_EMPTY_HISTORY,
            terminal=False,
        )
        self.candidate = watcher.ValuationCandidate(self.gcc)
        self.canonical = mm.CanonicalCard(
            "EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            language_code="en",
            unique_name_number=True,
        )

    def test_strong_poketrace_can_rescue_empty_gcc(self):
        evidence = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=market_estimate(90, 100, 110),
            note="PokeTrace exact PSA 8",
            fetched_at=NOW,
        )
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(mm, "_poketrace_evidence", return_value=evidence):
            result = mm.multimarket_process_external_market_candidates(
                None,
                [self.candidate],
                {},
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].valuation_path, watcher.PATH_EXTERNAL_RESCUE)
        self.assertAlmostEqual(result[0].estimated_market, 100)

    def test_all_candidates_use_external_provider_even_when_gcc_supported(self):
        estimate = market_estimate(90, 100, 110)
        supported_op = watcher._opportunity_from_estimate(
            self.target, estimate, []
        )
        supported = watcher.GccMarketEvidence(
            self.target,
            [],
            estimate,
            supported_op,
            watcher.GCC_BRANCH_SUPPORTED,
            watcher.EVIDENCE_STRONG,
        )
        candidate = watcher.ValuationCandidate(supported)
        evidence = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=market_estimate(92, 102, 112),
            note="external",
            fetched_at=NOW,
        )
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=None
        ), patch.object(mm, "_poketrace_evidence", return_value=evidence):
            result = mm.multimarket_process_external_market_candidates(
                None,
                [candidate],
                {},
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].valuation_path, watcher.PATH_GCC_EXTERNAL_CONFIRMED
        )

    def test_raw_only_interesting_card_becomes_manual_review_not_opportunity(self):
        raw = mm.RawMarketSignal(
            90, 100, 110, "EUR", ("Cardmarket",), "holo", "raw"
        )
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_CLEAN_NO_MATCH,
            watcher.EVIDENCE_UNAVAILABLE,
            "poketrace",
            note="graded absent",
            fetched_at=NOW,
        )
        fallback = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_TRANSIENT_UNAVAILABLE,
            watcher.EVIDENCE_UNAVAILABLE,
            "psa",
            note="APR unavailable; eBay 0",
            fetched_at=NOW,
        )
        state = {}
        with patch.object(mm, "_canonical_from_lot", return_value=self.canonical), patch.object(
            mm, "raw_market_signal", return_value=raw
        ), patch.object(mm, "_poketrace_evidence", return_value=poketrace), patch.object(
            mm, "_fallback_external", return_value=fallback
        ), patch.object(mm, "_notify_manual_review") as notify:
            result = mm.multimarket_process_external_market_candidates(
                None,
                [self.candidate],
                state,
                watcher.ValidationBudgets(),
                watcher.RunDiagnostics(),
                NOW,
            )
        self.assertEqual(result, [])
        notify.assert_called_once()
        self.assertIn(mm.MANUAL_REVIEW_STATE_KEY, state)

    def test_manual_review_is_deduplicated_inside_ttl(self):
        raw = mm.RawMarketSignal(
            90, 100, 110, "EUR", ("Cardmarket",), "holo", "raw"
        )
        lead = mm.ManualReviewLead(
            "key", self.target, self.canonical, raw, 55, "graded unavailable"
        )
        state = {}
        self.assertTrue(mm._manual_review_should_notify(state, lead, NOW))
        self.assertFalse(mm._manual_review_should_notify(state, lead, NOW))

    def test_install_bumps_external_cache_schema_and_wires_pipeline(self):
        old_inspect = watcher.inspect_item
        old_valid = watcher.is_valid_pokemon_card
        old_process = watcher.process_external_market_candidates
        old_schema = watcher.EXTERNAL_CACHE_SCHEMA_VERSION
        try:
            mm.install_canonical_multimarket_pipeline()
            self.assertEqual(
                watcher.EXTERNAL_CACHE_SCHEMA_VERSION,
                mm.MULTIMARKET_EXTERNAL_CACHE_SCHEMA_VERSION,
            )
            self.assertIs(watcher.inspect_item, mm.canonical_inspect_item)
            self.assertIs(
                watcher.process_external_market_candidates,
                mm.multimarket_process_external_market_candidates,
            )
        finally:
            watcher.inspect_item = old_inspect
            watcher.is_valid_pokemon_card = old_valid
            watcher.process_external_market_candidates = old_process
            watcher.EXTERNAL_CACHE_SCHEMA_VERSION = old_schema


    def test_fallback_external_calls_real_watcher_fetch_external_market_evidence(self):
        # Must not crash or call nonexistent fetch_psa_apr_evidence
        budgets = watcher.ValidationBudgets()
        diagnostics = watcher.ExternalMarketDiagnostics()
        with patch.object(watcher, "fetch_external_market_evidence") as mock_fetch:
            mock_fetch.return_value = watcher.ExternalMarketEvidence(
                "key", watcher.EXTERNAL_CLEAN_NO_MATCH, watcher.EVIDENCE_UNAVAILABLE, "ebay", note="clean"
            )
            res = mm._fallback_external(None, self.candidate, budgets, diagnostics, NOW)
            mock_fetch.assert_called_once()
            self.assertEqual(res.status, watcher.EXTERNAL_CLEAN_NO_MATCH)

    def test_safe_notify_manual_review_with_raw_none_does_not_crash(self):
        # Lead with raw=None and discovery_signal must format and notify safely
        import v4_multimarket_safety as mms
        import v4_price_discovery as pd
        signal = pd.PriceDiscoverySignal(
            listing_identity="Charizard Base Set",
            gcc_price=45.0,
            grader="PCA",
            grade="10",
            exact_grader_liquidity=pd.LIQUIDITY_LOW,
            category=pd.CATEGORY_ILLIQUID_PRICE_DISCOVERY,
            liquidity=pd.LIQUIDITY_LOW,
            evidence_quality=pd.EVIDENCE_QUALITY_MODERATE,
            uncertainty=pd.UNCERTAINTY_HIGH,
            grader_spread=pd.GRADER_SPREAD_HIGH,
            credible_high_reference=120.0,
            asymmetric_upside_ratio=2.67,
            main_thesis="Sparse PCA 10 liquidity rescued by PSA 10 sold anchor",
            credible_adjacent_anchors=(),
            crossgrade_required=False,
            manual_review_recommended=True,
            diagnostics=(),
        )
        lead = mm.ManualReviewLead(
            "key", self.target, self.canonical, raw=None, gap_pct=0.0, graded_note="graded absent", discovery_signal=signal
        )
        # Test calling safe_notify_manual_review directly
        mms.safe_notify_manual_review(lead)

    def test_collect_price_discovery_lead_blocks_conflicted_or_weak_raw(self):
        # 1. Weak or conflicted raw consensus alone returns None (blocked from creating lead)
        weak_raw = mm.RawMarketSignal(
            90, 100, 110, "EUR", ("Cardmarket",), "holo", "raw", confidence="WEAK", anomaly_flags=("CONFLICT",), disagreement_ratio=1.45
        )
        lead_solo = mm._collect_price_discovery_lead(
            self.candidate, self.canonical, weak_raw, None, None, NOW
        )
        self.assertIsNone(lead_solo)

        # 2. When valid poketrace anchors exist alongside weak raw, no RAW_CONSENSUS anchor is added
        mock_est = type("Estimate", (), {"central": 220.0, "low": 200.0, "high": 250.0, "exact_grade_count": 5})()
        poketrace = watcher.ExternalMarketEvidence(
            watcher.external_commercial_identity_key(self.target),
            watcher.EXTERNAL_MATCHED,
            watcher.EVIDENCE_STRONG,
            "poketrace",
            estimate=mock_est,
            fetched_at=NOW,
        )

        canonical_fr = mm.CanonicalCard(
            status="EXACT",
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Dracaufeu",
            language_code="fr",
            unique_name_number=True,
        )
        lead_with_pt = mm._collect_price_discovery_lead(
            self.candidate, canonical_fr, weak_raw, poketrace=poketrace, now=NOW
        )
        self.assertIsNotNone(lead_with_pt)
        self.assertIsNotNone(lead_with_pt.discovery_signal)
        for a in lead_with_pt.discovery_signal.credible_adjacent_anchors:
            self.assertNotEqual(a.anchor_type, "RAW_CONSENSUS")


if __name__ == "__main__":
    unittest.main()
