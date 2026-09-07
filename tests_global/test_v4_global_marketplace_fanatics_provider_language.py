import unittest

import v4_global_marketplace_fanatics_provider_language as target
import v4_global_fanatics_native_identity as v1
from v4_global_market_core import CommercialIdentity


def _exact(language="ja"):
    label = "Japanese" if language == "ja" else "English"
    coordinate = v1.FanaticsNativeCoordinate(
        year=2024,
        language_code=language,
        language_label=label,
        set_name="151",
        name="Pikachu",
        local_id="173",
        grade="10",
    )
    identity = CommercialIdentity(
        name="Pikachu",
        set_name="151",
        number="173/165",
        language=language,
        grader="PSA",
        grade="10",
    )
    return v1.FanaticsNativeResolution(
        "EXACT", "FANATICS_TCGDEX_SET_EXACT", coordinate=coordinate, identity=identity
    )


class FanaticsProviderLanguageTests(unittest.TestCase):
    def test_explicit_provider_url_language_recovers_missing_h1_language(self):
        calls = []

        def fake(title, *, proof_text="", resolver=None):
            calls.append(title)
            if title.endswith(" Japanese"):
                return _exact("ja")
            return v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")

        old = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = fake
        try:
            result = target.resolve_fanatics_native_identity_with_provider_language(
                "2024 Pokemon 151 Pikachu #173 PSA 10",
                proof_text=(
                    "Provider URL: https://www.fanaticscollect.com/buy-now/id/"
                    "2024-pokemon-japanese-151-pikachu-173-psa-10"
                ),
            )
        finally:
            target._ORIGINAL_RESOLVER = old
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "FANATICS_PROVIDER_TEXT_LANGUAGE_TCGDEX_EXACT")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(len(calls), 2)

    def test_explicit_language_field_is_allowed(self):
        self.assertEqual(target._provider_language("Card Language: English"), ("en", "English"))

    def test_competing_provider_languages_remain_unproven(self):
        proof = "Pokemon Japanese\nRelated: Pokemon English"
        self.assertIsNone(target._provider_language(proof))

    def test_no_provider_language_never_defaults_to_english_or_japanese(self):
        calls = []

        def fake(title, *, proof_text="", resolver=None):
            calls.append(title)
            return v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")

        old = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = fake
        try:
            result = target.resolve_fanatics_native_identity_with_provider_language(
                "2024 Pokemon 151 Pikachu #173 PSA 10",
                proof_text="Guide Price $100",
            )
        finally:
            target._ORIGINAL_RESOLVER = old
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "explicit_language_unproven")
        self.assertEqual(len(calls), 1)

    def test_language_conflict_is_fail_closed(self):
        def fake(title, *, proof_text="", resolver=None):
            if title.endswith(" Japanese"):
                return _exact("en")
            return v1.FanaticsNativeResolution("NO_MATCH", "explicit_language_unproven")

        old = target._ORIGINAL_RESOLVER
        target._ORIGINAL_RESOLVER = fake
        try:
            result = target.resolve_fanatics_native_identity_with_provider_language(
                "2024 Pokemon 151 Pikachu #173 PSA 10",
                proof_text="Pokemon Japanese",
            )
        finally:
            target._ORIGINAL_RESOLVER = old
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIsNone(result.identity)


if __name__ == "__main__":
    unittest.main()
