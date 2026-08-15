import unittest
from dataclasses import replace
from datetime import datetime, timezone

import watcher
import v4_canonical_multimarket as multimarket
import v4_price_discovery as pd
import v4_notification_signal_quality_guard as guard


def make_lot(
    *,
    url="https://gradedcardcenter.com/item/example",
    price=10.0,
    source_type="fixed",
    minutes_to_end=None,
):
    return watcher.Lot(
        url=url,
        title="Florizarre ex",
        current_price=price,
        source_type=source_type,
        minutes_to_end=minutes_to_end,
        grader="PCA",
        grade="9.5",
        card_set="Couronne Stellaire",
        card_number="001/142",
        language="French",
    )


def make_signal(
    *,
    reference=16.0,
    ratio=1.6,
    anchors=None,
):
    return pd.PriceDiscoverySignal(
        listing_identity="Florizarre ex #001/142",
        gcc_price=10.0,
        grader="PCA",
        grade="9.5",
        exact_grader_liquidity=pd.LIQUIDITY_LOW,
        category=pd.CATEGORY_ILLIQUID_PRICE_DISCOVERY,
        liquidity=pd.LIQUIDITY_LOW,
        evidence_quality=pd.EVIDENCE_QUALITY_MODERATE,
        uncertainty=pd.UNCERTAINTY_HIGH,
        grader_spread=pd.GRADER_SPREAD_MODERATE,
        credible_high_reference=reference,
        asymmetric_upside_ratio=ratio,
        main_thesis="sparse exact market",
        credible_adjacent_anchors=tuple(anchors or ()),
        manual_review_recommended=True,
    )


def make_lead(lot, signal):
    canonical = multimarket.CanonicalCard(
        status="EXACT",
        card_id="sv07-001",
        set_id="sv07",
        set_name="Couronne Stellaire",
        local_id="001",
        full_number="001/142",
        name="Florizarre ex",
        language_code="fr",
    )
    return multimarket.ManualReviewLead(
        identity_key="legacy-changing-identity",
        lot=lot,
        canonical=canonical,
        raw=None,
        gap_pct=37.5,
        graded_note=signal.main_thesis,
        discovery_signal=signal,
    )


class ManualReviewSignalQualityTests(unittest.TestCase):
    def test_dedupe_key_is_stable_per_gcc_listing(self):
        first = make_lot()
        second = replace(
            first,
            grader="PCA",
            grade="9",
            language="fr",
            commercial_dimensions={"finish": "holo"},
        )
        self.assertEqual(
            guard._stable_manual_review_key(first),
            guard._stable_manual_review_key(second),
        )

    def test_legacy_identity_dedupe_is_migrated_to_stable_listing_key(self):
        lot = make_lot()
        signal = make_signal()
        lead = replace(
            make_lead(lot, signal),
            identity_key=guard._stable_manual_review_key(lot),
        )
        legacy_key = watcher.external_commercial_identity_key(lot)
        now = datetime(2026, 8, 15, 18, 30, tzinfo=timezone.utc)
        state = {
            multimarket.MANUAL_REVIEW_STATE_KEY: {
                "schema_version": multimarket.MANUAL_REVIEW_SCHEMA_VERSION,
                "entries": {
                    legacy_key: {
                        "sent_at": now.isoformat(),
                        "price": 10.0,
                        "gap_pct": 37.5,
                        "tcgdex_card_id": "sv07-001",
                    }
                },
            }
        }
        original = guard._BASE_MANUAL_REVIEW_SHOULD_NOTIFY
        guard._BASE_MANUAL_REVIEW_SHOULD_NOTIFY = multimarket._manual_review_should_notify
        try:
            self.assertFalse(
                guard._manual_review_should_notify_with_legacy_migration(
                    state, lead, now
                )
            )
        finally:
            guard._BASE_MANUAL_REVIEW_SHOULD_NOTIFY = original
        self.assertIn(
            lead.identity_key,
            state[multimarket.MANUAL_REVIEW_STATE_KEY]["entries"],
        )

    def test_illiquid_auction_is_silent_before_last_five_minutes(self):
        anchors = [
            pd.AdjacentAnchor(
                "EBAY_SOLD", "ebay", "PCA", "9.5", "fr", 25.0, "SOLD", 2
            )
        ]
        lead = make_lead(
            make_lot(source_type="auction", minutes_to_end=7),
            make_signal(reference=25.0, ratio=2.5, anchors=anchors),
        )
        self.assertFalse(guard._illiquid_phone_worthy(lead))

    def test_gcc_only_small_illiquid_edge_is_log_only_even_for_fixed(self):
        anchors = [
            pd.AdjacentAnchor(
                "EXACT_GCC_SOLD", "gcc", "PCA", "9.5", "fr", 12.0, "SOLD"
            ),
            pd.AdjacentAnchor(
                "EXACT_GCC_SOLD", "gcc", "PCA", "9.5", "fr", 16.0, "SOLD"
            ),
            pd.AdjacentAnchor(
                "EXACT_GCC_SOLD", "gcc", "PCA", "9.5", "fr", 20.0, "SOLD"
            ),
        ]
        lead = make_lead(
            make_lot(price=10.0, source_type="fixed"),
            make_signal(reference=16.0, ratio=1.6, anchors=anchors),
        )
        self.assertFalse(guard._illiquid_phone_worthy(lead))

    def test_gcc_only_large_fixed_dislocation_can_still_notify(self):
        anchors = [
            pd.AdjacentAnchor(
                "EXACT_GCC_SOLD", "gcc", "PCA", "9.5", "fr", 18.0, "SOLD"
            ),
            pd.AdjacentAnchor(
                "EXACT_GCC_SOLD", "gcc", "PCA", "9.5", "fr", 22.0, "SOLD"
            ),
        ]
        lead = make_lead(
            make_lot(price=10.0, source_type="fixed"),
            make_signal(reference=20.0, ratio=2.0, anchors=anchors),
        )
        self.assertTrue(guard._illiquid_phone_worthy(lead))

    def test_external_graded_sold_anchor_can_keep_moderate_fixed_signal(self):
        anchors = [
            pd.AdjacentAnchor(
                "EBAY_SOLD", "ebay", "PCA", "9.5", "fr", 14.0, "SOLD", 2
            )
        ]
        lead = make_lead(
            make_lot(price=10.0, source_type="fixed"),
            make_signal(reference=14.0, ratio=1.4, anchors=anchors),
        )
        self.assertTrue(guard._illiquid_phone_worthy(lead))


class TechnicalAlertQualityTests(unittest.TestCase):
    def _complete_diagnostics(self):
        diagnostics = watcher.RunDiagnostics()
        diagnostics.fixed_coverage.set_end_reason(watcher.END_EMPTY_PAGE_REACHED)
        diagnostics.auction_coverage.set_end_reason(watcher.END_EMPTY_PAGE_REACHED)

        diagnostics.fixed_economic_coverage.register_candidates(
            [], discovered_listings=0
        )
        diagnostics.fixed_economic_coverage.finalize()
        diagnostics.auction_economic_coverage.register_candidates(
            [], discovered_listings=0
        )
        diagnostics.auction_economic_coverage.finalize()
        return diagnostics

    def test_expected_auction_economic_cap_is_log_only(self):
        diagnostics = self._complete_diagnostics()
        lot = make_lot(source_type="auction", minutes_to_end=20)
        audit = diagnostics.auction_economic_coverage
        audit.register_candidates([lot], discovered_listings=1, valuation_cap=0)
        audit.record_cap_skipped(lot)
        audit.finalize()

        self.assertEqual(audit.status, watcher.COVERAGE_INCOMPLETE)
        self.assertFalse(guard.actionable_technical_alert_required(diagnostics))

    def test_urgent_new_listing_backlog_still_alerts(self):
        diagnostics = self._complete_diagnostics()
        diagnostics.fixed_queue.initialized = True
        diagnostics.fixed_queue.register("new-card", watcher.QUEUE_P0_NEW)
        diagnostics.fixed_queue.record_budget_skipped("new-card")
        self.assertTrue(guard.actionable_technical_alert_required(diagnostics))

    def test_real_auction_discovery_loss_still_alerts(self):
        diagnostics = self._complete_diagnostics()
        diagnostics.auction_coverage.mark_incomplete(
            "page failed", watcher.END_PAGE_FAILED
        )
        self.assertTrue(guard.actionable_technical_alert_required(diagnostics))


class RawMarketIsolationTests(unittest.TestCase):
    def test_v4_runtime_raw_adapter_returns_none(self):
        lot = make_lot()
        canonical = multimarket.CanonicalCard(status="EXACT")
        self.assertIsNone(guard._no_v4_raw_market_signal(lot, canonical))


if __name__ == "__main__":
    unittest.main()
