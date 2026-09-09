"""P1-P4 integration contract, bootstrapped by the actual Global runner.

Each case gets a fresh process: real installers (runner.main --help), V2 + V3,
TCGdex resolvers/recovery and final Fanatics gates. Only Session.request is
replaced. No mocked resolver, synthetic EXACT, installer reset or network.
Pinned fixture: tcgdex/cards-database@af33c9ac882e2acfadffaf19e8083aa976d12983.
Run: python -m unittest tests_global.test_v4_global_marketplace_fanatics_runtime_contract -v
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import unquote, urlparse
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PIN = "af33c9ac882e2acfadffaf19e8083aa976d12983"
FIXTURES = ROOT / "tests_global" / "fixtures" / "tcgdex_af33c9ac"
LIVE = "2023 Pokemon Japanese Scarlet & Violet 151 Master Ball Reverse Holo Pikachu #025 PSA 10 GEM"
SIMPLE = "2023 Pokemon Japanese Scarlet & Violet 151 Pikachu Master Ball #025 PSA 10 GEM"


class SourceInterrupted(BaseException):
    """Exercise finally even when a source call aborts resolution."""


class CatalogueHTTP:
    def __init__(self, case):
        self.case = case
        self.calls = []
        self.unexpected = []

    def request(self, session, method, url, **kwargs):
        import requests

        self.calls.append((method, url, kwargs.get("params")))
        parsed = urlparse(url)
        path = unquote(parsed.path)
        assert method.upper() == "GET", (method, url)
        status, payload = 404, {}
        if parsed.hostname == "raw.githubusercontent.com":
            prefix = f"/tcgdex/cards-database/{PIN}/"
            assert path.startswith(prefix), url
            relative = path[len(prefix):]
            fixture = FIXTURES / relative
            if fixture.is_file():
                if self.case == "exception_cleanup" and relative.endswith("/025.ts"):
                    raise SourceInterrupted()
                if self.case != "missing_proof":
                    status, payload = 200, fixture.read_text(encoding="utf-8")
                    if self.case == "poke_only":
                        payload = payload.replace('foil: "masterball"', 'foil: "pokeball"')
                    if self.case == "wrong_source_set" and relative.endswith("/025.ts"):
                        payload = payload.replace('from "../SV2a"', 'from "../SV10"')
                    if self.case == "missing_source_name" and relative.endswith("/025.ts"):
                        payload = payload.replace('id: "Pikachu",', '')
                    if self.case == "attack_name_is_not_card_name" and relative.endswith("/025.ts"):
                        payload = payload.replace('id: "Pikachu",', '').replace('id: "Charge",', 'id: "Pikachu",')
        elif parsed.hostname == "api.tcgdex.net":
            card = {
                "id": "SV2a-025", "localId": "025", "name": "ピカチュウ",
                "set": {"id": "SV2a", "name": "ポケモンカード151",
                        "cardCount": {"official": 165, "total": 210}},
                "variants": {"normal": True, "holo": False, "reverse": True},
            }
            if self.case == "wrong_rest_set":
                card["set"]["id"] = "SV10"
            if self.case == "wrong_rest_local":
                card["localId"] = "026"
            if self.case == "wrong_rest_card_id":
                card["id"] = "SV2a-026"
            if self.case == "wrong_rest_name":
                card["name"] = "ライチュウ"
            if self.case == "wrong_rest_count":
                card["set"]["cardCount"]["official"] = 166
            if self.case == "wrong_detail_foil":
                card["variants_detailed"] = [{"type": "reverse", "foil": "pokeball"}]
            if self.case == "wrong_detail_language":
                card["variants_detailed"] = [{"type": "reverse", "foil": "masterball", "languages": ["en"]}]
            if self.case == "malformed_details":
                card["variants_detailed"] = "not-a-variant-list"
            if self.case == "compatible_details":
                card["variants_detailed"] = [{"type": "reverse", "foil": "masterball", "languages": ["ja"]}]
            if path.endswith("/ja/sets/SV2a/25") or path.endswith("/ja/sets/SV2a/025"):
                status, payload = 200, card
            elif path.endswith("/ja/cards/SV2a-025"):
                status, payload = 200, card
            elif path.endswith("/cards") or path.endswith("/sets"):
                status, payload = 200, []
            # Ordinary cross-locale fallback is deliberately available in this
            # case. An absent special source proof must still veto the result.
            if self.case == "cross_locale_missing_proof":
                alias_card = dict(card, name="Pikachu")
                if path.endswith("/id/cards/SV2a-025"):
                    status, payload = 200, alias_card
                elif path.endswith("/id/cards"):
                    params = kwargs.get("params") or {}
                    if params.get("name") == "eq:Pikachu":
                        status, payload = 200, [alias_card]
        else:
            self.unexpected.append(url)
            raise AssertionError(f"Unexpected HTTP boundary: {url}")
        if self.case == "cross_locale_missing_proof" and parsed.hostname == "raw.githubusercontent.com":
            status, payload = 404, {}
        response = requests.Response()
        response.status_code = status
        response.url = url
        response.encoding = "utf-8"
        response._content = (payload if isinstance(payload, str) else json.dumps(payload)).encode("utf-8")
        return response


def run_case(case):
    sys.path.insert(0, str(ROOT))
    import requests

    http = CatalogueHTTP(case)
    with contextlib.ExitStack() as boundary:
        boundary.enter_context(patch.object(requests.sessions.Session, "request",
                               lambda session, method, url, **kw: http.request(session, method, url, **kw)))
        with contextlib.redirect_stderr(io.StringIO()):
            import v4_global_marketplace_notify_resilient as runner
            with contextlib.redirect_stdout(io.StringIO()), patch.object(sys, "argv", ["runner", "--help"]):
                try:
                    runner.main()
                except SystemExit as exit_status:
                    assert exit_status.code == 0
                else:
                    raise AssertionError("runner --help must exit before marketplace I/O")
                runner.confirmed.install_global_external_market_stack()

            import v4_canonical_multimarket as canonical
            import v4_global_fanatics_native_identity as v1
            import v4_global_marketplace_fanatics_native_v2 as v2
            import v4_global_marketplace_fanatics_native_v3 as v3
            import v4_global_marketplace_fanatics_source_pinned_sets as source_sets
            import v4_tcgdex_generalized_coordinate_recovery as generalized
            import v4_tcgdex_japanese_set_aliases as shared

            title = LIVE if case in {"live", "parser_dimensions", "poke_positive", "wrong_name_live"} else SIMPLE
            proof_text = ""
            if case in {"wrong_name", "wrong_name_plain"}:
                title = title.replace("Pikachu", "Charizard")
                if case == "wrong_name_plain":
                    title = title.replace(" Master Ball", "")
            elif case == "wrong_name_live":
                title = title.replace("Pikachu", "Charizard")
            elif case == "wrong_title_set":
                title = title.replace("Scarlet & Violet 151", "SV Glory Of The Rocket Gang")
            elif case == "wrong_title_local":
                title = title.replace("#025", "#026")
            elif case == "wrong_language":
                title = title.replace("Japanese", "English")
            elif case == "conflicting_balls":
                title = title.replace("Master Ball", "Master Ball Poke Ball")
            elif case == "conflicting_finish":
                title = title.replace("Master Ball", "Master Ball Reverse Non-Holo")
            elif case == "poke_positive":
                title = title.replace("Master Ball", "Poke Ball")
            elif case == "conflicting_provider_language":
                title = title.replace("Japanese", "JPN")
                proof_text = "Card Language: English"
            proof_text = proof_text or title

            if case == "parser_dimensions":
                strict, _ = v2.fanatics_coordinate_candidates(title)
                flexible, _ = v3._flexible_candidates(title)
                assert strict and flexible, "Both real parsers must participate"
                dimensions = {(c.finish, c.variant) for c in (*strict, *flexible)}
                assert dimensions == {("reverse", "master_ball")}, dimensions
                combined, _ = v3.fanatics_coordinate_candidates_v3(title)
                assert len(combined) == 1 and combined[0].name == "Pikachu", combined
                return

            aliases_before = dict(generalized._SET_ALIASES_BY_KEY)
            shared_before = tuple(shared._ALIASES)
            # Pre-existing negative state at the precise key must survive the
            # temporary Fanatics alias after success AND abort.
            flexible, _ = v3._flexible_candidates(title)
            rows = [c for c in flexible if c.set_name == "Scarlet & Violet 151" and c.name in {"Pikachu", "Charizard"}]
            if rows:
                lot = v1._lot_for_coordinate(rows[0])
                key = generalized._lot_components(lot)[-1]
                generalized._RECOVERY_NEGATIVE_CACHE.add(key)
            before_negative = set(generalized._RECOVERY_NEGATIVE_CACHE)
            before_positive = dict(generalized._RECOVERY_CACHE)

            if case == "exception_cleanup":
                assert rows, flexible
                try:
                    v3._resolve_coordinate_v3(rows[0], title=title, proof_text=proof_text,
                                              resolver=canonical.resolve_tcgdex_card)
                except SourceInterrupted:
                    pass
                else:
                    raise AssertionError("The real source boundary was not reached")
            else:
                result = v3.resolve_fanatics_native_identity_v3(
                    title, proof_text=proof_text, resolver=canonical.resolve_tcgdex_card)
                print(json.dumps({"case": case, "status": result.status, "reason": result.reason,
                                  "identity": repr(result.identity)}, ensure_ascii=False))
                positive = case in {"live", "poke_positive", "success_cleanup", "compatible_details"}
                if positive:
                    assert result.status == "EXACT", result
                    expected_ball = "poke_ball" if case == "poke_positive" else "master_ball"
                    assert result.identity.finish == "reverse", result
                    assert result.identity.variant == expected_ball, result
                    assert result.identity.language == "ja" and result.identity.grade == "10", result
                    assert result.identity.name == "Pikachu", result
                    import v4_tcgdex_detailed_variants as detailed
                    assert detailed._expected_from_global_identity(result.identity) == {
                        "finish": "reverse", "special_finish": expected_ball,
                    }
                    assert any(f"/{PIN}/data-asia/SV/SV2a/025.ts" in url for _, url, _ in http.calls)
                else:
                    assert result.status != "EXACT", result
                # Also exercise each real flexible coordinate directly through
                # the INSTALLED resolver. P4 must not hide an unsafe inner EXACT.
                if not positive:
                    for coordinate in flexible:
                        identity, reason = v3._resolve_coordinate_v3(
                            coordinate, title=title, proof_text=proof_text,
                            resolver=canonical.resolve_tcgdex_card)
                        assert identity is None, (case, coordinate, identity, reason)

            assert generalized._SET_ALIASES_BY_KEY == aliases_before
            assert tuple(shared._ALIASES) == shared_before
            assert not http.unexpected, http.unexpected
            assert generalized._RECOVERY_CACHE == before_positive
            assert before_negative <= generalized._RECOVERY_NEGATIVE_CACHE
            for alias in source_sets._SOURCE_ALIASES:
                assert generalized._alias_key("ja", alias.listing_set) not in generalized._SET_ALIASES_BY_KEY
            if case in {"success_cleanup", "exception_cleanup"} and rows:
                # Identical input in the shared resolver (also used by Magi)
                # cannot consume the transient Fanatics alias or recovered card.
                result = canonical.resolve_tcgdex_card(v1._lot_for_coordinate(rows[0]))
                assert result.status != "EXACT", result


class FanaticsRealRuntimeContractTests(unittest.TestCase):
    def check_case(self, case):
        child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "--case", case],
                               cwd=ROOT, capture_output=True, text=True, timeout=40)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)


for _case in (
    "live", "parser_dimensions", "wrong_name", "wrong_name_plain", "wrong_title_set", "wrong_rest_set",
    "wrong_title_local", "wrong_rest_local", "wrong_rest_card_id", "wrong_language",
    "poke_only", "missing_proof", "wrong_source_set", "conflicting_balls",
    "conflicting_finish", "cross_locale_missing_proof", "poke_positive",
    "success_cleanup", "exception_cleanup",
    "wrong_name_live", "missing_source_name", "attack_name_is_not_card_name",
    "wrong_rest_name", "wrong_rest_count", "conflicting_provider_language",
    "wrong_detail_foil", "wrong_detail_language", "malformed_details", "compatible_details",
):
    setattr(FanaticsRealRuntimeContractTests, "test_" + _case,
            lambda self, case=_case: self.check_case(case))


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--case":
        run_case(sys.argv[2])
    else:
        unittest.main()
