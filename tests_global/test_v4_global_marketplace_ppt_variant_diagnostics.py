from __future__ import annotations

import os
import unittest
from unittest import mock

import v4_canonical_multimarket as canonical
import v4_global_marketplace_ppt_variant_diagnostics as diag
import v4_global_ppt_confirmation as ppt
from v4_global_market_core import CommercialIdentity


IDENTITY = CommercialIdentity(
    name="Litten",
    set_name="MEP Black Star Promos",
    number="044/0",
    language="en",
    grader="PSA",
    grade="9",
)
CANONICAL = canonical.CanonicalCard(
    status="EXACT",
    card_id="mep-044",
    set_id="mep",
    set_name="MEP Black Star Promos",
    local_id="044",
    full_number="044/0",
    name="Litten",
    language_code="en",
    variants={
        "__tcgdex_variants_detailed_state__": "USABLE",
        "__tcgdex_variants_detailed_entries__": ({"type": "holo", "size": "standard"},),
    },
)
ROWS = [
    {
        "name": "Litten",
        "setName": "MEP Black Star Promos",
        "cardNumber": "044/0",
        "language": "english",
        "rarity": "Promo",
        "variant": "Holofoil",
        "finish": "",
        "edition": "",
        "externalCatalogId": "mep-044",
        "setId": "mep",
        "price": 999999,
        "secret": "must-not-log",
    }
]


class PptVariantDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        diag.reset_ppt_variant_diagnostics()

    def tearDown(self):
        os.environ.pop("GLOBAL_PPT_VARIANT_DIAGNOSTICS", None)
        os.environ.pop("GLOBAL_PPT_VARIANT_DIAGNOSTICS_MAX", None)

    def test_wrapper_preserves_microvariant_result_and_logs_only_bounded_fields(self):
        os.environ["GLOBAL_PPT_VARIANT_DIAGNOSTICS"] = "true"
        original_result = ("MICROVARIANT_UNPROVEN", None, "provider material conflict")
        with mock.patch.object(diag, "_ORIGINAL_MATCH", return_value=original_result), mock.patch(
            "watcher.log"
        ) as log_mock:
            result = diag._diagnostic_match(IDENTITY, CANONICAL, ROWS)

        self.assertEqual(result, original_result)
        message = log_mock.call_args.args[0]
        self.assertIn("[PPT_VARIANT_DIAG]", message)
        self.assertIn('"card_id": "mep-044"', message)
        self.assertIn('"rarity": "Promo"', message)
        self.assertIn('"variant": "Holofoil"', message)
        self.assertNotIn("999999", message)
        self.assertNotIn("must-not-log", message)

    def test_non_microvariant_result_is_unchanged_and_silent(self):
        os.environ["GLOBAL_PPT_VARIANT_DIAGNOSTICS"] = "true"
        original_result = ("MATCHED", ROWS[0], "exact")
        with mock.patch.object(diag, "_ORIGINAL_MATCH", return_value=original_result), mock.patch(
            "watcher.log"
        ) as log_mock:
            result = diag._diagnostic_match(IDENTITY, CANONICAL, ROWS)
        self.assertEqual(result, original_result)
        log_mock.assert_not_called()

    def test_diagnostics_disabled_is_silent(self):
        original_result = ("MICROVARIANT_UNPROVEN", None, "blocked")
        with mock.patch.object(diag, "_ORIGINAL_MATCH", return_value=original_result), mock.patch(
            "watcher.log"
        ) as log_mock:
            result = diag._diagnostic_match(IDENTITY, CANONICAL, ROWS)
        self.assertEqual(result, original_result)
        log_mock.assert_not_called()

    def test_log_cap_is_hard_bounded(self):
        os.environ["GLOBAL_PPT_VARIANT_DIAGNOSTICS"] = "true"
        os.environ["GLOBAL_PPT_VARIANT_DIAGNOSTICS_MAX"] = "1"
        original_result = ("MICROVARIANT_UNPROVEN", None, "blocked")
        with mock.patch.object(diag, "_ORIGINAL_MATCH", return_value=original_result), mock.patch(
            "watcher.log"
        ) as log_mock:
            diag._diagnostic_match(IDENTITY, CANONICAL, ROWS)
            diag._diagnostic_match(IDENTITY, CANONICAL, ROWS)
        self.assertEqual(log_mock.call_count, 1)

    def test_installer_is_inert_when_disabled_and_wraps_current_match_when_enabled(self):
        old_match = ppt._match_canonical
        old_original = diag._ORIGINAL_MATCH
        old_installed = diag._INSTALLED
        try:
            diag._INSTALLED = False
            diag._ORIGINAL_MATCH = None
            diag.install_global_marketplace_ppt_variant_diagnostics()
            self.assertIs(ppt._match_canonical, old_match)

            os.environ["GLOBAL_PPT_VARIANT_DIAGNOSTICS"] = "true"
            diag.install_global_marketplace_ppt_variant_diagnostics()
            self.assertIs(diag._ORIGINAL_MATCH, old_match)
            self.assertIs(ppt._match_canonical, diag._diagnostic_match)
        finally:
            ppt._match_canonical = old_match
            diag._ORIGINAL_MATCH = old_original
            diag._INSTALLED = old_installed


if __name__ == "__main__":
    unittest.main()
