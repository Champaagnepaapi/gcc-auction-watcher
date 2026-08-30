from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / "mac" / "robot-kb-local"
for candidate in (ROOT, LOCAL):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

import robot_kb_cardova_psa_api_identity_probe as probe


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class CardovaPsaApiIdentityProbeTests(unittest.TestCase):
    def record(self, **updates):
        value = {
            "source": "cardova_public_past_auction",
            "source_native_record_id": "01TEST",
            "source_url": "https://www.cardova.co.jp/en/auction/card/01TEST",
            "provider_sale_status": "PAID_COMPLETED",
            "provider_sale_status_proven": True,
            "sale_evidence_ready": True,
            "currency": "JPY",
            "currency_proven": True,
            "final_bid_jpy": 5000000,
            "auction_end_at_utc": "2026-01-01T00:00:00+00:00",
            "certification_number": "153603277",
            "card_name": "Mario Pikachu",
            "set_name": "Pokemon TCG: Japanese XY Promo Mario Pikachu Special Box",
            "collector_number": "#294/XY-P",
            "language": "Japanese",
            "grader": "PSA",
            "grade": "10",
        }
        value.update(updates)
        return value

    def payload(self, **updates):
        cert = {
            "CertNumber": "153603277",
            "SpecID": 123,
            "Year": "2016",
            "Brand": "POKEMON JAPANESE XY PROMO",
            "Category": "TCG Cards",
            "CardNumber": "294/XY-P",
            "Subject": "MARIO PIKACHU",
            "Variety": "SPECIAL BOX",
            "GradeDescription": "GEM MT 10",
            "CardGrade": "GEM MT 10",
        }
        cert.update(updates)
        return {"PSACert": cert}

    def canonical(self, status="EXACT", **updates):
        value = {
            "status": status,
            "reason": "TCGDEX_TEST_EXACT" if status == "EXACT" else "no match",
            "language_code": "ja",
            "card_id": "XY-P-294",
            "set_id": "XY-P",
            "set_name": "XY Promos",
            "local_id": "294",
        }
        value.update(updates)
        return SimpleNamespace(**value)

    def test_official_api_payload_projects_to_existing_exact_surface(self):
        item, reason = probe.api_payload_to_item(self.payload())
        self.assertEqual(reason, "PSA_API_ITEM_READY")
        self.assertIsNotNone(item)
        self.assertEqual(item["Cert Number"], "153603277")
        self.assertEqual(item["Item Grade"], "GEM MT 10")
        self.assertEqual(item["Brand/Title"], "POKEMON JAPANESE XY PROMO")
        self.assertEqual(item["Subject"], "MARIO PIKACHU")
        self.assertEqual(item["Card Number"], "294/XY-P")
        self.assertEqual(item["Variety/Pedigree"], "SPECIAL BOX")
        ok, surface_reason = probe.html_probe._cardova_psa_surface_gate(self.record(), item)
        self.assertTrue(ok)
        self.assertEqual(surface_reason, "PSA_SURFACE_EXACT")

    def test_payload_fail_closed_for_invalid_or_missing_cert_data(self):
        item, reason = probe.api_payload_to_item({"IsValidRequest": False, "PSACert": self.payload()["PSACert"]})
        self.assertIsNone(item)
        self.assertEqual(reason, "PSA_API_INVALID_REQUEST")

        item, reason = probe.api_payload_to_item({"PSACert": None})
        self.assertIsNone(item)
        self.assertEqual(reason, "PSA_API_NO_CERT_DATA")

        item, reason = probe.api_payload_to_item(self.payload(CertNumber="bad"))
        self.assertIsNone(item)
        self.assertEqual(reason, "PSA_API_CERT_MALFORMED")

    def test_api_url_is_exact_psa_public_cert_endpoint_only(self):
        self.assertTrue(
            probe._safe_api_url(
                "https://api.psacard.com/publicapi/cert/GetByCertNumber/153603277"
            )
        )
        for url in (
            "http://api.psacard.com/publicapi/cert/GetByCertNumber/153603277",
            "https://www.psacard.com/cert/153603277/psa",
            "https://evil.example/publicapi/cert/GetByCertNumber/153603277",
            "https://api.psacard.com/publicapi/cert/GetByCertNumber/153603277?x=1",
            "https://api.psacard.com/publicapi/order/GetProgress/153603277",
        ):
            with self.subTest(url=url):
                self.assertFalse(probe._safe_api_url(url))

    def test_fetch_uses_bearer_header_without_exposing_token(self):
        token = "secret-token-value-123456"
        session = FakeSession(FakeResponse(200, self.payload()))
        item, reason = probe.fetch_psa_api_item(session, token, "153603277")
        self.assertEqual(reason, "PSA_API_ITEM_READY")
        self.assertIsNotNone(item)
        self.assertEqual(len(session.calls), 1)
        url, kwargs = session.calls[0]
        self.assertEqual(
            url,
            "https://api.psacard.com/publicapi/cert/GetByCertNumber/153603277",
        )
        self.assertEqual(kwargs["headers"]["Authorization"], f"Bearer {token}")
        self.assertNotIn(token, reason)

    def test_fetch_auth_and_rate_limit_are_fail_visible(self):
        for status, expected in (
            (401, "PSA_API_AUTH_401"),
            (403, "PSA_API_AUTH_403"),
            (429, "PSA_API_HTTP_429"),
        ):
            with self.subTest(status=status):
                item, reason = probe.fetch_psa_api_item(
                    FakeSession(FakeResponse(status, {})),
                    "secret-token-value-123456",
                    "153603277",
                )
                self.assertIsNone(item)
                self.assertEqual(reason, expected)

    def test_keychain_loader_returns_token_without_logging_contract(self):
        calls = []

        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return SimpleNamespace(returncode=0, stdout="secret-token-value-123456\n")

        token = probe.load_token_from_keychain(runner=runner)
        self.assertEqual(token, "secret-token-value-123456")
        self.assertEqual(calls[0][0][:3], ["security", "find-generic-password", "-s"])
        self.assertTrue(calls[0][1]["capture_output"])

    def test_run_records_requires_api_surface_then_tcgdex_and_microvariant(self):
        original = probe.paid_identity.install_tcgdex_stack_once
        probe.paid_identity.install_tcgdex_stack_once = lambda: None
        try:
            item, _ = probe.api_payload_to_item(self.payload())

            def resolver(identity):
                return None, self.canonical()

            def micro(identity, canonical):
                return True, "EXACT", "TEST_EXACT", {"finish": "holo"}

            payload = probe.run_records(
                [self.record()],
                fetcher=lambda record: (item, "PSA_API_ITEM_READY"),
                max_records=1,
                resolver=resolver,
                microvariant_checker=micro,
            )
        finally:
            probe.paid_identity.install_tcgdex_stack_once = original

        self.assertEqual(payload["psa_identity_surface_exact_count"], 1)
        self.assertEqual(payload["macro_identity_exact_count"], 1)
        self.assertEqual(payload["exact_microvariant_count"], 1)
        self.assertFalse(payload["psa_api_circuit_open"])
        self.assertEqual(payload["records"][0]["psa_identity_source"], "PSA_PUBLIC_API_GET_BY_CERT_NUMBER")
        self.assertFalse(payload["records"][0]["sale_transaction_ready"])

    def test_run_records_opens_circuit_on_auth_failure(self):
        original = probe.paid_identity.install_tcgdex_stack_once
        probe.paid_identity.install_tcgdex_stack_once = lambda: None
        try:
            payload = probe.run_records(
                [self.record(source_native_record_id="a"), self.record(source_native_record_id="b")],
                fetcher=lambda record: (None, "PSA_API_AUTH_401"),
                max_records=2,
            )
        finally:
            probe.paid_identity.install_tcgdex_stack_once = original
        self.assertTrue(payload["psa_api_circuit_open"])
        self.assertEqual(payload["blocked"].get("PSA_API_AUTH_401"), 1)
        self.assertEqual(payload["blocked"].get("PSA_API_CIRCUIT_OPEN"), 1)

    def test_safety_summary_stays_read_only_and_keychain_only(self):
        summary = probe.safe_summary()
        self.assertEqual(summary["psa_identity_source"], "PSA_PUBLIC_API_GET_BY_CERT_NUMBER")
        self.assertEqual(summary["psa_token_source"], "MACOS_KEYCHAIN")
        self.assertFalse(summary["psa_html_scraping"])
        self.assertFalse(summary["psa_token_persisted_in_output"])
        for key in (
            "robot_kb_write",
            "sale_transaction_ready",
            "sale_transaction_stored",
            "v4_economic_use",
            "notification_sent",
            "automatic_purchase",
            "automatic_bid",
            "automatic_offer",
            "automatic_checkout",
            "automatic_payment",
            "fuzzy_matching",
            "translation_assumed",
            "provider_alias_table_added",
        ):
            self.assertIs(summary[key], False, key)


if __name__ == "__main__":
    unittest.main()
