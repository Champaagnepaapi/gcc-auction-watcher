from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from v4_ppt_shadow_language_bridge import (
    RELATION_CROSS_LANGUAGE_EN,
    RELATION_EXACT_LANGUAGE,
    PptMarketIdentity,
    _apply_language_relation,
    estimate_fr_en_language_basis,
    install_v4_ppt_shadow_language_bridge,
    resolve_ppt_market_identity,
)
from v4_ppt_shadow_model import DailyGradePoint
from v4_ppt_shadow_provider import PptMacroIdentity


class PptShadowCrossLanguageTests(unittest.TestCase):
    def _canonical(self, language: str = "fr"):
        return SimpleNamespace(
            status="EXACT",
            language_code=language,
            card_id="base1-4",
            set_id="base1",
            set_name="Set de Base" if language == "fr" else "Base Set",
            local_id="4",
            full_number="4/102",
            name="Dracaufeu" if language == "fr" else "Charizard",
        )

    def test_english_listing_is_exact_language_without_bridge(self):
        canonical = self._canonical("en")
        fake_market = SimpleNamespace(
            _fetch_tcgdex_card_detail=lambda *_args, **_kwargs: self.fail(
                "English listing must not need a cross-language bridge"
            )
        )
        result = resolve_ppt_market_identity(canonical, fake_market)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.market_relation, RELATION_EXACT_LANGUAGE)
        self.assertEqual(result.identity.name, "Charizard")

    def test_french_listing_maps_to_english_alias_only_with_same_catalog_invariants(self):
        canonical = self._canonical("fr")
        english = {
            "id": "base1-4",
            "localId": "4",
            "name": "Charizard",
            "set": {
                "id": "base1",
                "name": "Base Set",
                "cardCount": {"official": 102},
            },
        }
        fake_market = SimpleNamespace(
            _fetch_tcgdex_card_detail=lambda language, card_id: (200, english)
        )
        result = resolve_ppt_market_identity(canonical, fake_market)
        self.assertEqual(result.status, "EXACT_BRIDGE")
        self.assertEqual(result.market_relation, RELATION_CROSS_LANGUAGE_EN)
        self.assertEqual(result.listing_language, "fr")
        self.assertEqual(result.provider_language, "en")
        self.assertEqual(result.identity.card_id, "base1-4")
        self.assertEqual(result.identity.name, "Charizard")
        self.assertEqual(result.identity.set_name, "Base Set")
        self.assertEqual(result.identity.number, "4/102")

    def test_french_bridge_fails_closed_if_catalog_set_changes(self):
        canonical = self._canonical("fr")
        english = {
            "id": "base1-4",
            "localId": "4",
            "name": "Charizard",
            "set": {"id": "different", "name": "Base Set"},
        }
        fake_market = SimpleNamespace(
            _fetch_tcgdex_card_detail=lambda language, card_id: (200, english)
        )
        result = resolve_ppt_market_identity(canonical, fake_market)
        self.assertEqual(result.status, "BRIDGE_CONFLICT")
        self.assertIsNone(result.identity)

    def _candidate(self, prices=(120.0, 118.0, 122.0)):
        dates = (
            datetime(2026, 8, 10, tzinfo=timezone.utc),
            datetime(2026, 7, 20, tzinfo=timezone.utc),
            datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        sales = [
            SimpleNamespace(
                price=price,
                source="gcc",
                grader="PSA",
                grade=10.0,
                sold_at=when,
                exact_card=True,
            )
            for price, when in zip(prices, dates)
        ]
        return SimpleNamespace(
            lot=SimpleNamespace(current_price=60.0),
            gcc=SimpleNamespace(sales=sales),
        )

    def _history(self):
        return [
            DailyGradePoint("2026-06-01", 1, 100.0),
            DailyGradePoint("2026-07-20", 1, 100.0),
            DailyGradePoint("2026-08-10", 1, 100.0),
        ]

    def test_language_basis_is_calibrated_only_from_exact_same_grade_dated_pairs(self):
        basis = estimate_fr_en_language_basis(
            self._candidate(),
            self._history(),
            grader="PSA",
            grade=10,
            usd_per_eur=1.0,
            today=datetime(2026, 8, 16, tzinfo=timezone.utc).date(),
        )
        self.assertEqual(basis.status, "CALIBRATED")
        self.assertEqual(basis.pair_count, 3)
        self.assertGreaterEqual(basis.distinct_sale_days, 2)
        self.assertGreaterEqual(basis.recent_pairs_90d, 1)
        self.assertAlmostEqual(basis.ratio_fr_per_en, 1.20, places=2)
        self.assertLess(basis.relative_mad, 0.05)

    def test_uncalibrated_french_anchor_cannot_become_fair_value_or_rescue(self):
        candidate = SimpleNamespace(
            lot=SimpleNamespace(current_price=50.0),
            gcc=SimpleNamespace(sales=[]),
        )
        relation = PptMarketIdentity(
            "EXACT_BRIDGE",
            PptMacroIdentity("base1-4", "Charizard", "Base Set", "4/102"),
            "fr",
            "en",
            RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_SAME_CARD_ID_SET_ID_LOCAL_ID_FR_TO_EN",
        )
        metrics, actionable = _apply_language_relation(
            {
                "fair_value_eur": 100.0,
                "fair_value_usd": 100.0,
                "evidence_strength": "STRONG",
                "shadow_required_discount_pct": 25.0,
                "baseline_30pct_signal": True,
                "kinetic_shadow_signal": True,
            },
            relation=relation,
            candidate=candidate,
            history=self._history(),
            grader="PSA",
            grade=10,
            usd_per_eur=1.0,
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        self.assertFalse(actionable)
        self.assertEqual(metrics["market_relation"], RELATION_CROSS_LANGUAGE_EN)
        self.assertEqual(metrics["anchor_fair_value_eur"], 100.0)
        self.assertIsNone(metrics["fair_value_eur"])
        self.assertFalse(metrics["kinetic_shadow_signal"])
        self.assertFalse(metrics["economic_eligible_in_shadow"])

    def test_calibrated_french_basis_adjusts_en_anchor_before_discount(self):
        candidate = self._candidate()
        relation = PptMarketIdentity(
            "EXACT_BRIDGE",
            PptMacroIdentity("base1-4", "Charizard", "Base Set", "4/102"),
            "fr",
            "en",
            RELATION_CROSS_LANGUAGE_EN,
            "TCGDEX_SAME_CARD_ID_SET_ID_LOCAL_ID_FR_TO_EN",
        )
        metrics, actionable = _apply_language_relation(
            {
                "fair_value_eur": 100.0,
                "fair_value_usd": 100.0,
                "evidence_strength": "STRONG",
                "shadow_required_discount_pct": 25.0,
                "baseline_30pct_signal": False,
                "kinetic_shadow_signal": False,
            },
            relation=relation,
            candidate=candidate,
            history=self._history(),
            grader="PSA",
            grade=10,
            usd_per_eur=1.0,
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        self.assertTrue(actionable)
        self.assertEqual(metrics["language_basis_status"], "CALIBRATED")
        self.assertAlmostEqual(metrics["fair_value_eur"], 120.0, places=2)
        self.assertAlmostEqual(metrics["discount_to_external_pct"], 50.0, places=2)
        self.assertEqual(metrics["shadow_required_discount_pct"], 35.0)
        self.assertTrue(metrics["kinetic_shadow_signal"])
        self.assertFalse(metrics["exact_language_comparable"])

    def test_install_wrapper_keeps_original_opportunities_unchanged(self):
        sentinel = [object(), object()]
        watcher = types.ModuleType("watcher")
        watcher.logs = []
        watcher.log = watcher.logs.append

        def original(*args, **kwargs):
            return sentinel

        watcher.process_external_market_candidates = original
        summary = {
            "eligible": 1,
            "matched": 1,
            "strong": 1,
            "exact_language": 0,
            "cross_language_anchor": 1,
            "cross_language_calibrated": 0,
            "anchor_only": 1,
            "bridge_failed": 0,
            "cache_hits": 0,
            "blocked_language": 0,
            "blocked_variant": 0,
            "rescue_candidates": 0,
            "revalue_candidates": 0,
        }
        module = sys.modules[install_v4_ppt_shadow_language_bridge.__module__]
        with patch.dict(sys.modules, {"watcher": watcher}), patch.dict(
            os.environ,
            {
                "V4_PPT_SHADOW_ENABLED": "true",
                "POKEMONPRICETRACKER_API_KEY": "offline-test-key",
            },
            clear=False,
        ), patch.object(module, "_ORIGINAL", None), patch.object(
            module, "collect_ppt_shadow_cross_language", return_value=summary
        ):
            install_v4_ppt_shadow_language_bridge()
            result = watcher.process_external_market_candidates(
                None,
                [],
                {},
                None,
                None,
                datetime(2026, 8, 16, tzinfo=timezone.utc),
            )

        self.assertIs(result, sentinel)
        self.assertTrue(getattr(watcher, "_v4_ppt_shadow_installed", False))
        self.assertTrue(any("economic-use=false" in line for line in watcher.logs))


if __name__ == "__main__":
    unittest.main()
