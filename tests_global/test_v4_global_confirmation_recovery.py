from __future__ import annotations

import unittest
from unittest import mock

import v4_canonical_multimarket as multimarket
import v4_global_economic_confirmation as confirmation
import v4_global_live_confirmed as live_confirmed
import v4_global_ppt_confirmation as ppt
from v4_global_market_core import FIXED_ASK, CommercialIdentity


MEWTWO = CommercialIdentity(
    name="Mewtwo",
    set_name="151",
    number="183/165",
    language="ja",
    grader="PSA",
    grade="10",
)
RAIKOU = CommercialIdentity(
    name="Raikou",
    set_name="VSTAR Universe",
    number="218/172",
    language="ja",
    grader="PSA",
    grade="10",
    finish="V",
    variant="Special Art Rare",
)
RAIKOU_CANONICAL = multimarket.CanonicalCard(
    status="EXACT",
    card_id="S12a-218",
    set_id="S12a",
    set_name="VSTAR Universe",
    local_id="218",
    full_number="218/172",
    name="Raikou",
    language_code="ja",
    reason="TEST_EXACT",
)


def _card(identity: CommercialIdentity, *, actionable: bool) -> dict[str, object]:
    offers = []
    if actionable:
        offers.append(
            {
                "market": "fanatics",
                "evidence_type": FIXED_ASK,
                "all_in_eur": 99.0,
            }
        )
    return {
        "identity": {
            "name": identity.name,
            "set_name": identity.set_name,
            "number": identity.number,
            "language": identity.language,
            "grader": identity.grader,
            "grade": identity.grade,
            "edition": identity.edition,
            "finish": identity.finish,
            "variant": identity.variant,
        },
        "offers": offers,
    }


class GlobalRecoveryRegressionTests(unittest.TestCase):
    def test_synthetic_tcgdex_lot_keeps_card_name_clean(self):
        lot = confirmation._lot_for_identity(RAIKOU)
        self.assertEqual(lot.title, "Raikou")
        self.assertEqual(lot.listing_text, "Raikou")
        self.assertEqual(lot.card_set, "VSTAR Universe")
        self.assertEqual(lot.card_number, "218/172")
        self.assertEqual(lot.language, "Japanese")
        self.assertEqual(lot.grader, "PSA")
        self.assertEqual(lot.grade, "10")
        self.assertIn("Special Art Rare", lot.variant)

    def test_provider_budget_prioritizes_actionable_then_reviewed(self):
        actionable_reviewed = _card(MEWTWO, actionable=True)
        diagnostic_reviewed = _card(MEWTWO, actionable=False)
        actionable_dynamic = _card(RAIKOU, actionable=True)
        diagnostic_dynamic = _card(RAIKOU, actionable=False)

        self.assertLess(
            live_confirmed._confirmation_priority(0, actionable_reviewed),
            live_confirmed._confirmation_priority(1, diagnostic_reviewed),
        )
        self.assertLess(
            live_confirmed._confirmation_priority(0, actionable_reviewed),
            live_confirmed._confirmation_priority(2, actionable_dynamic),
        )
        self.assertLess(
            live_confirmed._confirmation_priority(2, actionable_dynamic),
            live_confirmed._confirmation_priority(3, diagnostic_dynamic),
        )

    @mock.patch("v4_global_ppt_confirmation._request")
    def test_generic_ppt_discovery_is_bounded_to_five_rows(self, request_mock):
        request_mock.return_value = (200, {"data": []})
        result = ppt.fetch_snapshot(
            RAIKOU,
            api_key="test-only-not-a-secret",
            budget=ppt.PptBudget(interval_seconds=0),
            session=mock.Mock(),
            fx=mock.Mock(),
            canonical=RAIKOU_CANONICAL,
        )
        self.assertEqual(result.status, "CLEAN_NO_MATCH")
        params = request_mock.call_args.args[3]
        self.assertEqual(params["limit"], 5)
        self.assertEqual(params["language"], "japanese")
        self.assertEqual(params["search"], "Raikou")


if __name__ == "__main__":
    unittest.main()
