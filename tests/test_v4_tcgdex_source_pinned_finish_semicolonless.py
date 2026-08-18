from __future__ import annotations

import unittest
from unittest.mock import patch

import v4_canonical_multimarket as mm
import v4_tcgdex_source_pinned_finish as source_finish


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def _semicolonless_source(set_id: str, finish: str = "holo") -> str:
    return (
        'import { Card } from "../../../interfaces"\n'
        f'import Set from "../{set_id}"\n\n'
        "const card: Card = {\n"
        "    set: Set,\n"
        "    variants: [\n"
        f'        {{ type: "{finish}", thirdParty: {{ cardmarket: 1 }} }},\n'
        "    ],\n"
        "}\n\n"
        "export default card\n"
    )


class SemicolonlessPinnedSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        source_finish.clear_source_finish_runtime_state()

    @staticmethod
    def _card(
        *,
        card_id: str,
        set_id: str,
        local_id: str,
        full_number: str,
        name: str,
    ) -> mm.CanonicalCard:
        return mm.CanonicalCard(
            status="EXACT",
            card_id=card_id,
            set_id=set_id,
            set_name=set_id,
            local_id=local_id,
            full_number=full_number,
            name=name,
            language_code="ja",
            variants={
                "normal": True,
                "holo": False,
                "reverse": False,
                "firstEdition": False,
            },
            reason="TCGDEX_EXACT_SET_LOCALID",
        )

    def test_bellibolt_semicolonless_upstream_style_is_accepted(self):
        card = self._card(
            card_id="SV3-112",
            set_id="SV3",
            local_id="112",
            full_number="112/108",
            name="Bellibolt",
        )
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, _semicolonless_source("SV3")),
        ) as get:
            corrected = source_finish.apply_source_pinned_finish(card)

        self.assertEqual(get.call_count, 1)
        self.assertIn("/data-asia/SV/SV3/112.ts", get.call_args.args[0])
        self.assertFalse(corrected.variants["normal"])
        self.assertTrue(corrected.variants["holo"])
        self.assertFalse(corrected.variants["reverse"])
        self.assertFalse(corrected.variants["firstEdition"])

    def test_crocalor_semicolonless_upstream_style_is_accepted(self):
        card = self._card(
            card_id="SV1a-079",
            set_id="SV1a",
            local_id="079",
            full_number="079/073",
            name="Crocalor",
        )
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, _semicolonless_source("SV1a")),
        ):
            corrected = source_finish.apply_source_pinned_finish(card)

        self.assertFalse(corrected.variants["normal"])
        self.assertTrue(corrected.variants["holo"])
        self.assertFalse(corrected.variants["reverse"])

    def test_exact_import_line_stays_fail_closed_with_trailing_tokens(self):
        card = self._card(
            card_id="SV3-112",
            set_id="SV3",
            local_id="112",
            full_number="112/108",
            name="Bellibolt",
        )
        malformed = _semicolonless_source("SV3").replace(
            'import Set from "../SV3"\n',
            'import Set from "../SV3" + unexpected\n',
        )
        with patch.object(
            source_finish._SESSION,
            "get",
            return_value=_Response(200, malformed),
        ):
            self.assertIs(source_finish.apply_source_pinned_finish(card), card)


if __name__ == "__main__":
    unittest.main()
