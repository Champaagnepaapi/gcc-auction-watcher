import unittest

import v4_global_marketplace_fanatics_language_proof as target
import v4_global_fanatics_native_identity as v1
from v4_global_market_core import CommercialIdentity


def exact(language: str, *, provider_set: str, catalog_set: str, reason: str):
    label = "English" if language == "en" else "Japanese"
    coordinate = v1.FanaticsNativeCoordinate(
        year=2024,
        language_code=language,
        language_label=label,
        set_name=provider_set,
        name="Raichu",
        local_id="132",
        grade="10",
    )
    identity = CommercialIdentity(
        name="Raichu",
        set_name=catalog_set,
        number="132/091",
        language=language,
        grader="PSA",
        grade="10",
    )
    return v1.FanaticsNativeResolution("EXACT", reason, coordinate=coordinate, identity=identity)


def clean_no_match():
    return v1.FanaticsNativeResolution("NO_MATCH", target._CLEAN_TCGDEX_NO_MATCH)


class FanaticsLanguageProofTests(unittest.TestCase):
    def setUp(self):
        target._language_proof_titles = 0

    def test_unique_english_set_exact_proves_language(self):
        original = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        english = exact(
            "en",
            provider_set="Paldean Fates",
            catalog_set="Paldean Fates",
            reason="FANATICS_TCGDEX_SET_EXACT",
        )
        result = target._choose_language_resolution(original, english, clean_no_match())
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "FANATICS_TCGDEX_LANGUAGE_UNIQUE_SET_EXACT")
        self.assertEqual(result.identity.language, "en")

    def test_both_set_exact_languages_stay_ambiguous(self):
        original = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        english = exact(
            "en",
            provider_set="Shared Set",
            catalog_set="Shared Set",
            reason="FANATICS_TCGDEX_SET_EXACT",
        )
        japanese = exact(
            "ja",
            provider_set="Shared Set",
            catalog_set="Shared Set",
            reason="FANATICS_TCGDEX_CROSS_LOCALE_UNIQUE_NAME_LOCALID",
        )
        result = target._choose_language_resolution(original, english, japanese)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIsNone(result.identity)

    def test_unique_name_only_never_proves_missing_language(self):
        original = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        english = exact(
            "en",
            provider_set="Promo",
            catalog_set="Scarlet & Violet Promos",
            reason="FANATICS_TCGDEX_UNIQUE_NAME_LOCALID",
        )
        result = target._choose_language_resolution(original, english, clean_no_match())
        self.assertIs(result, original)

    def test_transient_competing_language_blocks(self):
        original = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        english = exact(
            "en",
            provider_set="Paldean Fates",
            catalog_set="Paldean Fates",
            reason="FANATICS_TCGDEX_SET_EXACT",
        )
        japanese = v1.FanaticsNativeResolution("ERROR", "tcgdex_cross_locale_transient_http_503")
        result = target._choose_language_resolution(original, english, japanese)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "fanatics_language_competing_probe_unresolved")

    def test_cross_locale_generic_set_conflict_does_not_compete(self):
        original = v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")
        english = exact(
            "en",
            provider_set="Paldean Fates",
            catalog_set="Paldean Fates",
            reason="FANATICS_TCGDEX_SET_EXACT",
        )
        japanese = exact(
            "ja",
            provider_set="Paldean Fates",
            catalog_set="Shiny Treasure ex",
            reason="FANATICS_TCGDEX_CROSS_LOCALE_UNIQUE_NAME_LOCALID",
        )
        result = target._choose_language_resolution(original, english, japanese)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.language, "en")

    def test_wrapper_probes_both_languages_without_treating_marker_as_proof(self):
        calls = []

        def fake(title, *, proof_text="", resolver=None):
            calls.append(title)
            if title.endswith(" English"):
                return exact(
                    "en",
                    provider_set="Paldean Fates",
                    catalog_set="Paldean Fates",
                    reason="FANATICS_TCGDEX_SET_EXACT",
                )
            if title.endswith(" Japanese"):
                return clean_no_match()
            return v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")

        old = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = fake
        try:
            result = target.resolve_fanatics_native_identity_with_language_proof(
                "2024 Pokemon Paldean Fates Raichu 132 PSA 10"
            )
        finally:
            target._ORIGINAL_RESOLVER = old

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.identity.language, "en")
        self.assertEqual(len(calls), 3)
        self.assertTrue(calls[1].endswith(" English"))
        self.assertTrue(calls[2].endswith(" Japanese"))

    def test_existing_explicit_language_path_is_untouched(self):
        calls = []
        japanese = exact(
            "ja",
            provider_set="SV4a",
            catalog_set="Shiny Treasure ex",
            reason="FANATICS_TCGDEX_CROSS_LOCALE_SET_LOCALID_EXACT",
        )

        def fake(title, *, proof_text="", resolver=None):
            calls.append(title)
            return japanese

        old = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = fake
        try:
            result = target.resolve_fanatics_native_identity_with_language_proof(
                "2023 Japanese Pokemon SV4a Ralts 258 PSA 10"
            )
        finally:
            target._ORIGINAL_RESOLVER = old

        self.assertIs(result, japanese)
        self.assertEqual(calls, ["2023 Japanese Pokemon SV4a Ralts 258 PSA 10"])


if __name__ == "__main__":
    unittest.main()
