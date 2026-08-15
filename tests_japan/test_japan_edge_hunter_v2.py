from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import japan_edge_hunter as base
import japan_edge_hunter_v2 as v2

NOW = datetime(2026, 8, 16, tzinfo=timezone.utc)


def row(native_id="x", price=100, days=5, *, name="Absol", number="#089/063", variety="", rarity="Mega Attack Rare", set_name="Mega Brave"):
    return {
        "id": native_id,
        "status": "SOLD",
        "soldAt": (NOW - timedelta(days=days)).isoformat().replace("+00:00", "Z"),
        "priceInCents": int(price * 100),
        "item": {
            "gradingCompany": "PSA",
            "grade": "10",
            "collectible": {
                "category": "Pokemon",
                "type": "CARDS",
                "language": "Japanese",
                "set": set_name,
                "reference": number,
                "yearOfDistribution": 2025,
                "edition": "Unlimited",
                "attribute": "",
                "variety": variety,
                "rarity": rarity,
                "character": {"englishName": name},
            },
        },
    }


def ask(provider="magi", extra_search="", detail_noise=""):
    search = f"Absol 089/063 PSA10 Japanese Mega Brave 日本版 ¥8,500 {extra_search}".strip()
    text = search
    if detail_noise:
        text += f"\n---DETAIL---\n{detail_noise}"
    return base.Ask(
        provider,
        "https://magi.camp/items/2038087342",
        "Absol 089/063 PSA10 Japanese Mega Brave",
        8500,
        text,
    )


class JapanEdgeV2Tests(unittest.TestCase):
    def test_detail_page_recommendation_noise_does_not_fake_multi_or_auction(self):
        ident = base.sold_from_gcc(row()).identity
        noisy = ask(detail_noise="おすすめ商品 2枚セット販売 オークション 入札")
        ok, reason = v2.identity_check(noisy, ident)
        self.assertTrue(ok)
        self.assertEqual(reason, "strict_text_identity")

    def test_search_associated_multi_and_auction_still_fail_closed(self):
        ident = base.sold_from_gcc(row()).identity
        self.assertEqual(v2.identity_check(ask(extra_search="2枚セット販売"), ident)[1], "multi_item_listing")
        self.assertEqual(v2.identity_check(ask(extra_search="現在 オークション"), ident)[1], "ongoing_auction")

    def test_official_notice_marks_mega_dream_ma_family_as_variant_sensitive(self):
        affected = base.sold_from_gcc(
            row(
                name="Mega Charizard X ex",
                number="#223/193",
                set_name="Mega Dream ex",
                rarity="Mega Attack Rare",
            )
        ).identity
        control = base.sold_from_gcc(row()).identity
        self.assertTrue(v2._official_surface_error_applicable(affected))
        self.assertFalse(v2._official_surface_error_applicable(control))

    def test_unqualified_affected_gcc_sold_cannot_be_exact_reference(self):
        sales = [
            base.sold_from_gcc(row("a", 100, 2, name="Mega Charizard X ex", number="#223/193", set_name="Mega Dream ex")),
            base.sold_from_gcc(row("b", 110, 3, name="Mega Charizard X ex", number="#223/193", set_name="Mega Dream ex")),
            base.sold_from_gcc(row("c", 120, 4, name="Mega Charizard X ex", number="#223/193", set_name="Mega Dream ex")),
        ]
        self.assertEqual(v2.references(sales, NOW), [])

    def test_explicit_incorrect_texture_gcc_sold_can_form_separate_reference(self):
        sales = [
            base.sold_from_gcc(row("a", 600, 2, name="Mega Charizard X ex", number="#223/193", set_name="Mega Dream ex", variety="MA-INCORRECT TEXTURE")),
            base.sold_from_gcc(row("b", 620, 3, name="Mega Charizard X ex", number="#223/193", set_name="Mega Dream ex", variety="MA-INCORRECT TEXTURE")),
        ]
        refs = v2.references(sales, NOW)
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0].fair_eur, 610)

    def test_incorrect_texture_listing_requires_explicit_variant_text(self):
        ident = base.sold_from_gcc(
            row(
                name="Mega Charizard X ex",
                number="#223/193",
                set_name="Mega Dream ex",
                variety="MA-INCORRECT TEXTURE",
            )
        ).identity
        plain = base.Ask(
            "magi",
            "https://magi.camp/items/1",
            "Mega Charizard X ex 223/193 PSA10 Japanese Mega Dream ex",
            12000,
            "日本版 223/193 PSA10 Mega Dream ex",
        )
        self.assertEqual(v2.identity_check(plain, ident)[1], "official_surface_variant_unproven")
        explicit = base.Ask(
            "magi",
            "https://magi.camp/items/2",
            "Mega Charizard X ex 223/193 PSA10 MA-INCORRECT TEXTURE Japanese Mega Dream ex",
            12000,
            "日本版 223/193 PSA10 MA-INCORRECT TEXTURE Mega Dream ex",
        )
        self.assertTrue(v2.identity_check(explicit, ident)[0])


if __name__ == "__main__":
    unittest.main()
