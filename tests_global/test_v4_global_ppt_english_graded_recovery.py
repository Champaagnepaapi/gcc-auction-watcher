from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

import v4_canonical_multimarket as multimarket
import v4_global_live_confirmed as confirmed
import v4_global_ppt_confirmation as ppt
import v4_global_ppt_english_graded_recovery as recovery
from v4_global_market_core import CommercialIdentity


NOW = datetime(2026, 9, 14, 18, 0, tzinfo=timezone.utc)
IDENTITY = CommercialIdentity(
    name="Litten",
    set_name="MEP Black Star Promos",
    number="044/0",
    language="en",
    grader="PSA",
    grade="9",
)
CANONICAL = multimarket.CanonicalCard(
    status="EXACT",
    card_id="mep-044",
    set_id="mep",
    set_name="MEP Black Star Promos",
    local_id="044",
    full_number="044/0",
    name="Litten",
    language_code="en",
)


class EnglishPptRecoveryTests(unittest.TestCase):
    def test_psa9_english_uses_two_bounded_exact_calls(self):
        shallow = {
            "externalCatalogId": "mep-044",
            "setId": "provider-mep",
            "setName": "MEP Black Star Promos",
            "cardNumber": "044/0",
            "name": "Litten",
            "language": "english",
            "tcgPlayerId": "123",
        }
        deep = dict(shallow)
        calls = []

        def fake_request(_session, _key, _budget, params, _timeout):
            calls.append(dict(params))
            if len(calls) == 1:
                return 200, {"data": [shallow]}
            return 200, {"data": [deep]}

        with mock.patch.object(
            recovery,
            "_ORIGINAL_FETCH",
            return_value=ppt.PptSnapshot("BLOCKED_LANGUAGE"),
        ), mock.patch.object(ppt, "_request", side_effect=fake_request), mock.patch.object(
            ppt,
            "_match_canonical",
            side_effect=[
                ("EXACT", shallow, "TCGDEX_EXTERNAL_CATALOG_ID"),
                ("EXACT", deep, "TCGDEX_EXTERNAL_CATALOG_ID"),
            ],
        ), mock.patch.object(
            ppt,
            "_snapshot_from_deep_row",
            return_value=ppt.PptSnapshot(
                "MATCHED",
                fair_eur=24.0,
                sales_count=5,
                last_sale_at=NOW,
            ),
        ):
            result = recovery.fetch_english_graded_snapshot(
                IDENTITY,
                api_key="placeholder",
                budget=ppt.PptBudget(max_http_calls=10, max_credits=100),
                session=object(),
                fx=object(),
                now=NOW,
                canonical=CANONICAL,
            )

        self.assertEqual(result.status, "MATCHED")
        self.assertEqual(result.sales_count, 5)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["language"], "english")
        self.assertIn("Litten", calls[0]["search"])
        self.assertIn("044/0", calls[0]["search"])
        self.assertEqual(calls[1]["tcgPlayerId"], "123")
        self.assertEqual(calls[1]["includeEbay"], "true")
        self.assertEqual(ppt._grade_key(IDENTITY), "psa9")
        self.assertIn("exact TCGdex macro/material gate", result.note)

    def test_material_ambiguity_remains_blocking_before_deep_call(self):
        with mock.patch.object(
            recovery,
            "_ORIGINAL_FETCH",
            return_value=ppt.PptSnapshot("BLOCKED_LANGUAGE"),
        ), mock.patch.object(
            ppt,
            "_request",
            return_value=(200, {"data": [{"name": "Shining Mewtwo"}]}),
        ) as request_mock, mock.patch.object(
            ppt,
            "_match_canonical",
            return_value=(
                "MICROVARIANT_UNPROVEN",
                None,
                "TCGDEX_VARIANTS_DETAILED_AMBIGUOUS",
            ),
        ):
            result = recovery.fetch_english_graded_snapshot(
                CommercialIdentity(
                    name="Shining Mewtwo",
                    set_name="Neo Destiny",
                    number="109/105",
                    language="en",
                    grader="PSA",
                    grade="10",
                ),
                api_key="placeholder",
                budget=ppt.PptBudget(max_http_calls=10, max_credits=100),
                session=object(),
                fx=object(),
                now=NOW,
                canonical=multimarket.CanonicalCard(
                    status="EXACT",
                    card_id="neo4-109",
                    set_id="neo4",
                    set_name="Neo Destiny",
                    local_id="109",
                    full_number="109/105",
                    name="Shining Mewtwo",
                    language_code="en",
                ),
            )

        self.assertEqual(result.status, "MICROVARIANT_UNPROVEN")
        self.assertEqual(request_mock.call_count, 1)

    def test_unsupported_grade_delegates_without_provider_call(self):
        baseline = ppt.PptSnapshot("BLOCKED_LANGUAGE", note="legacy")
        with mock.patch.object(recovery, "_ORIGINAL_FETCH", return_value=baseline), mock.patch.object(
            ppt, "_request"
        ) as request_mock:
            result = recovery.fetch_english_graded_snapshot(
                CommercialIdentity(
                    name="Litten",
                    set_name="MEP Black Star Promos",
                    number="044/0",
                    language="en",
                    grader="PSA",
                    grade="7",
                ),
                api_key="placeholder",
                budget=ppt.PptBudget(),
                session=object(),
                fx=object(),
                now=NOW,
                canonical=CANONICAL,
            )
        self.assertIs(result, baseline)
        request_mock.assert_not_called()

    def test_non_english_delegates_without_provider_call(self):
        baseline = ppt.PptSnapshot("BLOCKED_LANGUAGE", note="legacy")
        with mock.patch.object(recovery, "_ORIGINAL_FETCH", return_value=baseline), mock.patch.object(
            ppt, "_request"
        ) as request_mock:
            result = recovery.fetch_english_graded_snapshot(
                CommercialIdentity(
                    name="Litten",
                    set_name="MEP Black Star Promos",
                    number="044/0",
                    language="fr",
                    grader="PSA",
                    grade="9",
                ),
                api_key="placeholder",
                budget=ppt.PptBudget(),
                session=object(),
                fx=object(),
                now=NOW,
                canonical=CANONICAL,
            )
        self.assertIs(result, baseline)
        request_mock.assert_not_called()

    def test_unresolved_canonical_never_calls_provider(self):
        with mock.patch.object(
            recovery,
            "_ORIGINAL_FETCH",
            return_value=ppt.PptSnapshot("BLOCKED_LANGUAGE"),
        ), mock.patch.object(ppt, "_request") as request_mock:
            result = recovery.fetch_english_graded_snapshot(
                IDENTITY,
                api_key="placeholder",
                budget=ppt.PptBudget(),
                session=object(),
                fx=object(),
                now=NOW,
                canonical=multimarket.CanonicalCard("AMBIGUOUS"),
            )
        self.assertEqual(result.status, "TCGDEX_UNRESOLVED")
        request_mock.assert_not_called()

    def test_installer_is_idempotent(self):
        old_fetch = confirmed.fetch_snapshot
        old_installed = recovery._INSTALLED
        try:
            recovery._INSTALLED = False
            recovery.install_global_ppt_english_graded_recovery()
            first = confirmed.fetch_snapshot
            recovery.install_global_ppt_english_graded_recovery()
            self.assertIs(confirmed.fetch_snapshot, first)
            self.assertIs(first, recovery.fetch_english_graded_snapshot)
        finally:
            confirmed.fetch_snapshot = old_fetch
            recovery._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main()
