from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch

import watcher
import v4_canonical_multimarket as canonical
import v4_tcgdex_source_pinned_finish as source_finish
import v4_tcgdex_source_pinned_outage_fallback as outage
import v4_tcgdex_source_pinned_set_reconciliation as source_set


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class SourcePinnedOutageFallbackTests(unittest.TestCase):
    def setUp(self):
        canonical._DIAGNOSTICS = canonical.MultiMarketDiagnostics()
        source_finish.clear_source_finish_runtime_state()

    def tearDown(self):
        source_finish.clear_source_finish_runtime_state()

    @staticmethod
    def _lot(
        number: str = "102/100",
        *,
        title: str = "Articuno",
        language: str = "Japanese",
        card_set: str = "Battle Partners",
    ) -> watcher.Lot:
        return watcher.Lot(
            url="https://gradedcardcenter.com/item/tcgdex-outage-source-test",
            title=title,
            current_price=50.0,
            source_type="fixed",
            grader="PSA",
            grade="10",
            card_number=number,
            card_set=card_set,
            language=language,
            body=(
                "Catégorie: Pokémon\n"
                f"Référence: #{number}\n"
                f"Série: {card_set}\n"
                f"Langue: {language}\n"
            ),
        )

    @staticmethod
    def _error(reason: str = "TCGdex ConnectionError") -> canonical.CanonicalCard:
        return canonical.CanonicalCard("ERROR", reason=reason)

    @staticmethod
    def _source(set_id: str, *finishes: str) -> str:
        variants = "\n".join(
            f'        {{ type: "{finish}", thirdParty: {{ cardmarket: 1 }} }},'
            for finish in finishes
        )
        return (
            'import { Card } from "../../../interfaces";\n'
            f'import Set from "../{set_id}";\n'
            "const card: Card = {\n"
            "    variants: [\n"
            f"{variants}\n"
            "    ],\n"
            "};\n"
            "export default card;\n"
        )

    def test_connection_error_recovers_reviewed_battle_partners_coordinate(self):
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("SV9", "holo")),
        ) as get, patch.object(watcher, "log"):
            result = outage.recover_source_pinned_outage(
                self._lot(), self._error()
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.card_id, "SV9-102")
        self.assertEqual(result.set_id, "SV9")
        self.assertEqual(result.local_id, "102")
        self.assertEqual(result.full_number, "102/100")
        self.assertEqual(result.name, "Articuno")
        self.assertEqual(result.language_code, "ja")
        self.assertEqual(result.reason, "TCGDEX_SOURCE_PINNED_OUTAGE_RECOVERY")
        self.assertTrue(result.variants["holo"])
        self.assertFalse(result.variants["normal"])
        self.assertFalse(result.variants["reverse"])
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 0)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 1)
        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/SV/SV9/102.ts", get.call_args.args[0])

    def test_retryable_http_503_can_use_same_reviewed_source_rule(self):
        recovered = canonical.CanonicalCard(
            status="EXACT",
            card_id="SV9-102",
            set_id="SV9",
            set_name="Battle Partners",
            local_id="102",
            full_number="102/100",
            name="Articuno",
            language_code="ja",
            variants={"holo": True},
        )
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_set, "_recover_from_immutable_source", return_value=recovered
        ) as recover, patch.object(watcher, "log"):
            result = outage.recover_source_pinned_outage(
                self._lot(), self._error("TCGdex HTTP 503 on /cards")
            )

        self.assertEqual(result.status, "EXACT")
        self.assertEqual(result.reason, "TCGDEX_SOURCE_PINNED_OUTAGE_RECOVERY")
        recover.assert_called_once()
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 0)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 1)

    def test_malformed_payload_error_is_never_recovered(self):
        original = self._error("TCGdex malformed brief without id")
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_set,
            "_recover_from_immutable_source",
            side_effect=AssertionError("non-transport ERROR must stay blocked"),
        ):
            result = outage.recover_source_pinned_outage(self._lot(), original)

        self.assertIs(result, original)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 1)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)

    def test_no_match_is_never_recovered(self):
        original = canonical.CanonicalCard("NO_MATCH", reason="ordinary no match")
        with patch.object(
            source_set,
            "_recover_from_immutable_source",
            side_effect=AssertionError("NO_MATCH must use the normal recovery stack"),
        ):
            result = outage.recover_source_pinned_outage(self._lot(), original)
        self.assertIs(result, original)

    def test_wrong_denominator_stays_original_error_without_source_request(self):
        original = self._error()
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_finish._SESSION,
            "get",
            side_effect=AssertionError("wrong denominator must not reach source"),
        ):
            result = outage.recover_source_pinned_outage(
                self._lot("102/101"), original
            )

        self.assertIs(result, original)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 1)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)

    def test_non_japanese_listing_stays_original_error(self):
        original = self._error()
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_set,
            "_recover_from_immutable_source",
            side_effect=AssertionError("non-Japanese listing must not reach source"),
        ):
            result = outage.recover_source_pinned_outage(
                self._lot(language="English"), original
            )

        self.assertIs(result, original)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 1)

    def test_unreviewed_set_stays_original_error(self):
        original = self._error("TCGdex Timeout")
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_set,
            "_recover_from_immutable_source",
            side_effect=AssertionError("unreviewed set must not reach source"),
        ):
            result = outage.recover_source_pinned_outage(
                self._lot(card_set="Unknown Japanese Set"), original
            )

        self.assertIs(result, original)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 1)

    def test_missing_or_wrong_source_keeps_retryable_error_fail_closed(self):
        original = self._error("TCGdex ConnectionError")
        canonical._DIAGNOSTICS.tcgdex_error = 1
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, self._source("SV8", "holo")),
        ):
            result = outage.recover_source_pinned_outage(self._lot(), original)

        self.assertIs(result, original)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_error, 1)
        self.assertEqual(canonical._DIAGNOSTICS.tcgdex_exact, 0)

    def test_installer_wraps_once_and_preserves_non_error_result(self):
        original_resolver = canonical.resolve_tcgdex_card
        original_saved = outage._ORIGINAL_RESOLVER

        def base(_lot):
            return canonical.CanonicalCard("NO_MATCH", reason="base")

        try:
            canonical.resolve_tcgdex_card = base
            outage._ORIGINAL_RESOLVER = None
            outage.install_v4_tcgdex_source_pinned_outage_fallback()
            wrapped = canonical.resolve_tcgdex_card
            outage.install_v4_tcgdex_source_pinned_outage_fallback()
            self.assertIs(canonical.resolve_tcgdex_card, wrapped)
            result = canonical.resolve_tcgdex_card(self._lot())
            self.assertEqual(result.status, "NO_MATCH")
            self.assertEqual(result.reason, "base")
        finally:
            canonical.resolve_tcgdex_card = original_resolver
            outage._ORIGINAL_RESOLVER = original_saved

    def test_bootstrap_installs_transport_before_source_outage_fallback(self):
        source = Path("run_watcher_multimarket_resilient.py").read_text(
            encoding="utf-8"
        )
        retry_pos = source.index("install_v4_tcgdex_resilience()")
        fallback_pos = source.index(
            "install_v4_tcgdex_source_pinned_outage_fallback()"
        )
        runner_pos = source.index('runpy.run_module("run_watcher_multimarket"')
        self.assertLess(retry_pos, fallback_pos)
        self.assertLess(fallback_pos, runner_pos)


if __name__ == "__main__":
    unittest.main()
