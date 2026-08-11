from __future__ import annotations

import io
import unittest

from PIL import Image

from v5.card_number_ocr import (
    CardNumberOCRConfig,
    LocalCardNumberOCR,
    extract_card_number_tokens,
    render_card_number_ocr_counters,
)


def image_bytes():
    image = Image.new("RGB", (300, 420), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def candidate(card_id, number):
    return {
        "id": card_id,
        "name": "Charizard",
        "cardNumber": number,
        "set": {"name": "Base Set"},
        "productType": "single",
    }


class SequenceRunner:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = 0

    def __call__(self, _png_bytes, _psm, _timeout):
        self.calls += 1
        return self.outputs.pop(0) if self.outputs else ""


class LocalCardNumberOCRTests(unittest.TestCase):
    def test_extracts_and_normalizes_slash_collector_numbers_only(self):
        tokens = extract_card_number_tokens(
            "HP 120  collector 004 / 102  damage 90  alt SV107/SV122"
        )
        self.assertEqual(tokens, ("4/102", "sv107/sv122"))
        self.assertEqual(extract_card_number_tokens("HP 120 year 2024 damage 90"), ())

    def test_missing_number_accepts_two_independent_votes_when_candidate_exists(self):
        runner = SequenceRunner(["004/102", "004 / 102", "", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True, minimum_votes=2, override_minimum_votes=3),
            runner=runner,
        )
        result = ocr.resolve(
            [image_bytes()],
            [candidate("a", "004/102"), candidate("b", "11/108")],
            None,
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.normalized_number, "4/102")
        self.assertEqual(result.votes, 2)
        self.assertEqual(result.candidate["id"], "a")
        self.assertFalse(result.overrides_structured_number)

    def test_structured_number_override_requires_three_votes(self):
        runner = SequenceRunner(["004/102", "004/102", "", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True, minimum_votes=2, override_minimum_votes=3),
            runner=runner,
        )
        result = ocr.resolve(
            [image_bytes()],
            [candidate("a", "004/102"), candidate("b", "999/999")],
            "999/999",
        )
        self.assertFalse(result.matched)
        self.assertEqual(result.normalized_number, "4/102")
        self.assertEqual(ocr.counters.structured_number_overrides, 0)

        runner = SequenceRunner(["004/102", "004/102", "004/102", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True, minimum_votes=2, override_minimum_votes=3),
            runner=runner,
        )
        result = ocr.resolve(
            [image_bytes()],
            [candidate("a", "004/102"), candidate("b", "999/999")],
            "999/999",
        )
        self.assertTrue(result.matched)
        self.assertTrue(result.overrides_structured_number)
        self.assertEqual(ocr.counters.structured_number_overrides, 1)

    def test_token_not_present_in_candidate_pool_is_never_accepted(self):
        runner = SequenceRunner(["777/777", "777/777", "777/777", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True),
            runner=runner,
        )
        result = ocr.resolve(
            [image_bytes()],
            [candidate("a", "004/102")],
            None,
        )
        self.assertFalse(result.matched)
        self.assertEqual(ocr.counters.candidate_tokens_seen, 0)

    def test_same_number_on_two_candidates_remains_ambiguous(self):
        runner = SequenceRunner(["004/102", "004/102", "004/102", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True),
            runner=runner,
        )
        result = ocr.resolve(
            [image_bytes()],
            [candidate("a", "004/102"), candidate("variant", "004/102")],
            None,
        )
        self.assertFalse(result.matched)
        self.assertEqual(ocr.counters.rejected_candidate_ambiguous, 1)

    def test_renderer_never_exposes_ocr_text(self):
        secret_text = "004/102 PRIVATE SELLER NOTE"
        runner = SequenceRunner([secret_text, secret_text, "", ""])
        ocr = LocalCardNumberOCR(
            CardNumberOCRConfig(enabled=True),
            runner=runner,
        )
        ocr.resolve([image_bytes()], [candidate("a", "004/102")], None)
        rendered = render_card_number_ocr_counters(ocr)
        self.assertNotIn("PRIVATE SELLER NOTE", rendered)
        self.assertIn("persisted images/OCR text: 0", rendered)


if __name__ == "__main__":
    unittest.main()
