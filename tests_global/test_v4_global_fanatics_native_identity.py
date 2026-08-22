import unittest
from datetime import datetime, timezone

import v4_canonical_multimarket as multimarket
from v4_global_fanatics_native_identity import (
    parse_fanatics_native_coordinate,
    resolve_fanatics_native_identity,
    scan_fanatics_native_inventory,
)


JA_TITLE = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 PSA 10 GEM MINT"
EN_TITLE = "2023 Pokemon English Scarlet & Violet 151 Illustration Rare Psyduck #175 PSA 9 MINT"


def canonical(*, name, set_name, local_id, full_number, language="ja", status="EXACT", reason="TEST_EXACT"):
    return multimarket.CanonicalCard(
        status=status,
        card_id=f"test-{local_id}",
        set_id="test-set",
        set_name=set_name,
        local_id=local_id,
        full_number=full_number,
        name=name,
        language_code=language,
        reason=reason,
    )


class FakeLocator:
    def __init__(self, text):
        self.text = text

    @property
    def first(self):
        return self

    def inner_text(self, timeout=None):
        return self.text


class FakePage:
    def __init__(self, title, body):
        self.title = title
        self.body = body
        self.visits = []

    def goto(self, url, **kwargs):
        self.visits.append(url)

    def wait_for_timeout(self, _ms):
        return None

    def locator(self, selector):
        if selector == "h1":
            return FakeLocator(self.title)
        if selector == "body":
            return FakeLocator(self.body)
        raise AssertionError(selector)


class FanaticsNativeIdentityTests(unittest.TestCase):
    def test_parses_japanese_h1_without_gcc_seed(self):
        result = parse_fanatics_native_coordinate(JA_TITLE)
        self.assertEqual(result.status, "PARSED")
        self.assertIsNotNone(result.coordinate)
        coordinate = result.coordinate
        self.assertEqual(coordinate.language_code, "ja")
        self.assertEqual(coordinate.set_name, "Raging Surf")
        self.assertEqual(coordinate.name, "Groudon")
        self.assertEqual(coordinate.local_id, "69")
        self.assertEqual(coordinate.grade, "10")

    def test_parses_english_psa9_h1(self):
        result = parse_fanatics_native_coordinate(EN_TITLE)
        self.assertEqual(result.status, "PARSED")
        coordinate = result.coordinate
        self.assertEqual(coordinate.language_code, "en")
        self.assertEqual(coordinate.set_name, "151")
        self.assertEqual(coordinate.name, "Psyduck")
        self.assertEqual(coordinate.local_id, "175")
        self.assertEqual(coordinate.grade, "9")

    def test_exact_tcgdex_result_builds_commercial_identity(self):
        def resolver(_lot):
            return canonical(name="Groudon", set_name="Raging Surf", local_id="69", full_number="69/62")

        result = resolve_fanatics_native_identity(JA_TITLE, resolver=resolver)
        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "FANATICS_H1_NATIVE_TCGDEX_EXACT")
        self.assertEqual(result.identity.number, "69/62")
        self.assertEqual(result.identity.language, "ja")
        self.assertEqual(result.identity.grader, "PSA")
        self.assertEqual(result.identity.grade, "10")

    def test_missing_explicit_language_fails_closed(self):
        title = "2023 Pokemon Scarlet & Violet Raging Surf AR Groudon #69 PSA 10 GEM MINT"
        result = parse_fanatics_native_coordinate(title)
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "fanatics_title_schema_unproven")

    def test_missing_rarity_boundary_fails_closed(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf Groudon #69 PSA 10 GEM MINT"
        result = parse_fanatics_native_coordinate(title)
        self.assertEqual(result.status, "NO_MATCH")
        self.assertEqual(result.reason, "rarity_boundary_missing")

    def test_tcgdex_set_conflict_fails_closed(self):
        def resolver(_lot):
            return canonical(name="Groudon", set_name="Paradox Rift", local_id="69", full_number="69/182")

        result = resolve_fanatics_native_identity(JA_TITLE, resolver=resolver)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "tcgdex_set_name_conflict")
        self.assertIsNone(result.identity)

    def test_tcgdex_name_conflict_fails_closed(self):
        def resolver(_lot):
            return canonical(name="Kyogre", set_name="Raging Surf", local_id="69", full_number="69/62")

        result = resolve_fanatics_native_identity(JA_TITLE, resolver=resolver)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "tcgdex_card_name_conflict")

    def test_conflicting_exposed_fraction_fails_closed(self):
        def resolver(_lot):
            return canonical(name="Groudon", set_name="Raging Surf", local_id="69", full_number="69/62")

        result = resolve_fanatics_native_identity(
            JA_TITLE,
            proof_text="Listing coordinate 69/70",
            resolver=resolver,
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(result.reason, "conflicting_full_fraction")

    def test_non_exact_tcgdex_status_never_becomes_identity(self):
        def resolver(_lot):
            return multimarket.CanonicalCard("AMBIGUOUS", reason="multiple")

        result = resolve_fanatics_native_identity(JA_TITLE, resolver=resolver)
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertIsNone(result.identity)

    def test_psa7_is_outside_native_scope(self):
        title = "2023 Pokemon Japanese Scarlet & Violet Raging Surf AR Groudon #69 PSA 7 NM"
        result = parse_fanatics_native_coordinate(title)
        self.assertEqual(result.status, "NO_MATCH")

    def test_scanner_accepts_without_any_gcc_seeds(self):
        import v4_global_fanatics_native_identity as native

        page = FakePage(JA_TITLE, "$40.00\nGuide Price $60.00")
        old_urls = native.scan._fanatics_urls
        old_install = native.confirmed.install_global_external_market_stack
        old_resolver = native.multimarket.resolve_tcgdex_card
        try:
            native.scan._fanatics_urls = lambda _page, scroll_rounds: (["https://www.fanaticscollect.com/buy-now/12345678-1234-1234-1234-123456789012"], 1)
            native.confirmed.install_global_external_market_stack = lambda: None
            native.multimarket.resolve_tcgdex_card = lambda _lot: canonical(
                name="Groudon",
                set_name="Raging Surf",
                local_id="69",
                full_number="69/62",
            )
            rows, status = scan_fanatics_native_inventory(
                page,
                (),
                observed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
                max_detail_pages=5,
                scroll_rounds=1,
            )
        finally:
            native.scan._fanatics_urls = old_urls
            native.confirmed.install_global_external_market_stack = old_install
            native.multimarket.resolve_tcgdex_card = old_resolver

        self.assertEqual(status.status, "OK")
        self.assertEqual(status.candidates, 1)
        self.assertEqual(status.exact, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].market, "fanatics")
        self.assertEqual(rows[0].identity.number, "69/62")
        self.assertTrue(rows[0].identity_proven)
        self.assertIn("GCC history is not an identity prerequisite", rows[0].note)


if __name__ == "__main__":
    unittest.main()
