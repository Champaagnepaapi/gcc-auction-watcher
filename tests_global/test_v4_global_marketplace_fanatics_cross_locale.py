import unittest

from v4_global_marketplace_fanatics_cross_locale import (
    resolve_fanatics_cross_locale_identity,
)


def card(card_id, local_id, name, set_id, set_name, official):
    return {
        "id": card_id,
        "localId": local_id,
        "name": name,
        "set": {
            "id": set_id,
            "name": set_name,
            "cardCount": {"official": official, "total": official},
        },
    }


class FanaticsCrossLocaleTests(unittest.TestCase):
    def test_exact_set_code_recovers_romanized_japanese_name(self):
        alias = card("SV4a-258", "258", "Ralts", "SV4a", "Shiny Treasure ex", 190)
        japanese = card("SV4a-258", "258", "ラルトス", "SV4a", "シャイニートレジャーex", 190)

        def json_get(url, **kwargs):
            if "/id/sets/SV4a/258" in url:
                return 200, alias, {}
            if "/ja/cards/SV4a-258" in url:
                return 200, japanese, {}
            return 404, {}, {}

        result = resolve_fanatics_cross_locale_identity(
            "2023 Japanese Pokemon SV4a Ralts 258 PSA 10",
            json_get=json_get,
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "FANATICS_TCGDEX_CROSS_LOCALE_SET_LOCALID_EXACT")
        self.assertEqual(result.identity.name, "Ralts")
        self.assertEqual(result.identity.set_name, "Shiny Treasure ex")
        self.assertEqual(result.identity.number, "258/190")
        self.assertEqual(result.identity.language, "ja")

    def test_unique_alias_recovers_descriptive_provider_set(self):
        brief = {"id": "S12a-205", "localId": "205", "name": "Pikachu"}
        alias = card("S12a-205", "205", "Pikachu", "S12a", "VSTAR Universe", 172)
        japanese = card("S12a-205", "205", "ピカチュウ", "S12a", "VSTARユニバース", 172)

        def json_get(url, **kwargs):
            params = kwargs.get("params") or {}
            if url.endswith("/id/cards"):
                if params.get("name") == "eq:Pikachu" and params.get("localId") == "eq:205":
                    return 200, [brief], {}
                return 200, [], {}
            if url.endswith("/id/cards/S12a-205"):
                return 200, alias, {}
            if url.endswith("/ja/cards/S12a-205"):
                return 200, japanese, {}
            return 404, {}, {}

        result = resolve_fanatics_cross_locale_identity(
            "2022 Pokemon Japanese Sword & Shield VSTAR Universe AR Pikachu #205 PSA 10 GEM MINT",
            json_get=json_get,
        )
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "FANATICS_TCGDEX_CROSS_LOCALE_UNIQUE_NAME_LOCALID")
        self.assertEqual(result.identity.name, "Pikachu")
        self.assertEqual(result.identity.set_name, "VSTAR Universe")

    def test_alias_name_conflict_never_recovers_same_coordinate(self):
        alias = card("SV4a-258", "258", "Kirlia", "SV4a", "Shiny Treasure ex", 190)

        def json_get(url, **kwargs):
            if "/id/sets/SV4a/258" in url:
                return 200, alias, {}
            if url.endswith("/id/cards"):
                return 200, [], {}
            return 404, {}, {}

        result = resolve_fanatics_cross_locale_identity(
            "2023 Japanese Pokemon SV4a Ralts 258 PSA 10",
            json_get=json_get,
        )
        self.assertNotEqual(result.status, "EXACT")
        self.assertIsNone(result.identity)

    def test_full_fraction_conflict_stays_blocked(self):
        brief = {"id": "SV8-107", "localId": "107", "name": "Vivillon"}
        alias = card("SV8-107", "107", "Vivillon", "SV8", "Super Electric Breaker", 106)
        japanese = card("SV8-107", "107", "ビビヨン", "SV8", "超電ブレイカー", 106)

        def json_get(url, **kwargs):
            params = kwargs.get("params") or {}
            if url.endswith("/id/cards"):
                if params.get("name") == "eq:Vivillon" and params.get("localId") == "eq:107":
                    return 200, [brief], {}
                return 200, [], {}
            if url.endswith("/id/cards/SV8-107"):
                return 200, alias, {}
            if url.endswith("/ja/cards/SV8-107"):
                return 200, japanese, {}
            return 404, {}, {}

        result = resolve_fanatics_cross_locale_identity(
            "Vivillon 107/105 - Art Rare - PSA 10 - Japanese Pokémon",
            json_get=json_get,
        )
        self.assertNotEqual(result.status, "EXACT")
        self.assertIsNone(result.identity)

    def test_missing_explicit_language_is_never_recovered(self):
        result = resolve_fanatics_cross_locale_identity(
            "2026 Pokemon Ascended Heroes Pikachu ex 277 PSA 10",
            json_get=lambda *args, **kwargs: self.fail("network must not be called"),
        )
        self.assertEqual(result.status, "NO_MATCH")
        self.assertIsNone(result.identity)


if __name__ == "__main__":
    unittest.main()
