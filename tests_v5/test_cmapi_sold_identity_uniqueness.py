from __future__ import annotations

import unittest

from v5 import cmapi_sold_identity_uniqueness as target


class FakeResolver:
    def __init__(self, *, set_number: bool = False, name_number: bool = False) -> None:
        self.set_number = set_number
        self.name_number = name_number
        self.set_calls = 0
        self.name_calls = 0

    def set_number_exact(self, _card) -> bool:
        self.set_calls += 1
        return self.set_number

    def name_number_unique(self, _card) -> bool:
        self.name_calls += 1
        return self.name_number


class CmapiSoldIdentityUniquenessTests(unittest.TestCase):
    def test_signed_gengar_never_rescued(self) -> None:
        card = {"name": "Gengar VMAX", "set": "Fusion Strike", "number": "271"}
        offer = {
            "title": "Gengar VMAX #271 - Signed AUTO 10 / PSA 10 – TCG Card",
            "company": "PSA",
            "grade": "10",
        }
        resolver = FakeResolver(set_number=True, name_number=True)
        self.assertTrue(target.is_signed_or_autographed(offer["title"]))
        self.assertFalse(target.catalog_rescue_matches(card, offer, resolver))
        self.assertEqual(resolver.set_calls, 0)
        self.assertEqual(resolver.name_calls, 0)

    def test_lugia_set_number_recovers_missing_v_suffix(self) -> None:
        card = {"name": "Lugia V", "set": "Silver Tempest", "number": "186"}
        offer = {
            "title": "PSA 10 Lugia #186 Silver Tempest Sword & Shield Alternate Full Art Holo",
            "company": "PSA",
            "grade": "10",
        }
        resolver = FakeResolver(set_number=True)
        self.assertTrue(target.catalog_rescue_matches(card, offer, resolver))
        self.assertEqual(resolver.set_calls, 1)

    def test_espeon_name_number_recovers_missing_set(self) -> None:
        card = {"name": "Espeon VMAX", "set": "Fusion Strike", "number": "270"}
        offer = {
            "title": "Espeon VMAX (Alternate Art Secret) 270/264 PSA 10",
            "company": "PSA",
            "grade": "10",
        }
        resolver = FakeResolver(name_number=True)
        self.assertTrue(target.catalog_rescue_matches(card, offer, resolver))
        self.assertEqual(resolver.name_calls, 1)

    def test_dragonite_name_number_recovers_missing_set(self) -> None:
        card = {"name": "Dragonite V", "set": "Evolving Skies", "number": "192"}
        offer = {
            "title": "Dragonite V 192/203 PSA 10",
            "company": "PSA",
            "grade": "10",
        }
        resolver = FakeResolver(name_number=True)
        self.assertTrue(target.catalog_rescue_matches(card, offer, resolver))

    def test_blaziken_set_number_recovers_missing_vmax_suffix(self) -> None:
        card = {"name": "Blaziken VMAX", "set": "Chilling Reign", "number": "201"}
        offer = {
            "title": "POKEMON BLAZIKEN 2021 SWORD & SHIELD CHILLING REIGN #201 FA SECRET PSA 10",
            "company": "PSA",
            "grade": "10",
        }
        resolver = FakeResolver(set_number=True)
        self.assertTrue(target.catalog_rescue_matches(card, offer, resolver))

    def test_wrong_number_stays_rejected(self) -> None:
        card = {"name": "Dragonite V", "set": "Evolving Skies", "number": "192"}
        offer = {"title": "Dragonite V 191/203 PSA 10", "company": "PSA", "grade": "10"}
        resolver = FakeResolver(set_number=True, name_number=True)
        self.assertFalse(target.catalog_rescue_matches(card, offer, resolver))
        self.assertEqual(resolver.set_calls, 0)
        self.assertEqual(resolver.name_calls, 0)


if __name__ == "__main__":
    unittest.main()
