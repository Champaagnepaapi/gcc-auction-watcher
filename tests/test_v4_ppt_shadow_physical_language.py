from __future__ import annotations

import unittest
from types import SimpleNamespace

from v4_ppt_shadow_language_bridge import (
    RELATION_EXACT_LANGUAGE,
    _EnglishPptSession,
    resolve_ppt_market_identity,
)


class _CaptureSession:
    def __init__(self):
        self.params = None

    def get(self, url, *args, **kwargs):
        self.params = dict(kwargs.get("params") or {})
        return object()


class PptPhysicalLanguageTests(unittest.TestCase):
    def test_french_page_context_does_not_turn_english_physical_card_into_french(self):
        canonical = SimpleNamespace(
            status="EXACT",
            language_code="en",  # physical/canonical card language
            card_id="base1-4",
            set_id="base1",
            set_name="Base Set",
            local_id="4",
            full_number="4/102",
            name="Charizard",
            page_language="fr",  # UI/listing-site context; intentionally irrelevant
        )
        fake_market = SimpleNamespace(
            _fetch_tcgdex_card_detail=lambda *_args, **_kwargs: self.fail(
                "English physical card must not use the FR->EN bridge"
            )
        )

        result = resolve_ppt_market_identity(canonical, fake_market)

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.listing_language, "en")
        self.assertEqual(result.provider_language, "en")
        self.assertEqual(result.market_relation, RELATION_EXACT_LANGUAGE)
        self.assertEqual(result.identity.name, "Charizard")

    def test_exact_english_physical_card_forces_ppt_english_market(self):
        inner = _CaptureSession()
        session = _EnglishPptSession(inner)
        session.get("https://example.invalid", params={"search": "Charizard"})
        self.assertEqual(inner.params["language"], "english")


if __name__ == "__main__":
    unittest.main()
