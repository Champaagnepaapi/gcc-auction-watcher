"""Identity contradictions against the installed Global valuation runtime."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_case(case):
    import requests
    calls = []

    def request(session, method, url, **kwargs):
        assert method.upper() == "GET"
        calls.append((url, kwargs.get("params", {})))
        host, path = urlsplit(url).hostname, urlsplit(url).path
        payload, status = {}, 200
        if host == "api.poketrace.com":
            if path.endswith("/auth/info"):
                plan = "Free" if "free" in case else "Pro"
                payload = {"data": {"active": True, "user": {"plan": plan}}}
                if case.endswith("unknown_plan"):
                    payload["data"]["user"] = {}
                for code in (401, 403, 429):
                    if case.endswith("auth_" + str(code)):
                        status, payload = code, {"code": "UPGRADE_REQUIRED" if code == 403 else "UNAUTHORIZED"}
            elif path.endswith("/cards"):
                row = {"id": "fixture-pt", "name": "Pikachu", "cardNumber": "25/165", "game": "pokemon-japanese", "productType": "single", "set": {"name": "151"}, "variant": "Normal", "prices": {"ebay": {"NEAR_MINT": {"avg": 5, "saleCount": 4}}}}
                payload = {"data": [] if case.endswith("empty") else [row], "pagination": {"hasMore": False}}
                if case.endswith("search_403"):
                    status, payload = 403, {"code": "UPGRADE_REQUIRED"}
                if case.endswith("malformed"):
                    payload = {"unexpected": True}
            else:
                raise AssertionError(path)
        elif host in {"www.pricecharting.com", "pricecharting.com"}:
            name, category = "Pikachu #025", "Pokemon Japanese 151"
            if case.endswith("wrong_name"):
                name = "Flying Pikachu #025"
            if case.endswith("wrong_set"):
                category = "Pokemon Japanese Base Set"
            if case.endswith("wrong_language"):
                category = "Pokemon English 151"
            if case.endswith("wrong_variant"):
                name = "Pikachu [Poke Ball] #025"
            if case.endswith("both_variants"):
                name = "Pikachu [Master Ball Poke Ball] #025"
            if case.endswith("missing_variant"):
                name = "Pikachu #025"
            if case.endswith("valid_variant"):
                name = "Pikachu [Master Ball] #025"
            row = {"id": "fixture-025", "product-name": name,
                   "console-name": category, "manual-only-price": 10000, "status": "success"}
            if case.startswith("pc_api"):
                payload = {"status": "success", "products": [row]} if path == "/api/products" else row
            else:
                if path == "/search-products":
                    payload = '<a href="/game/pokemon-japanese-151/pikachu-25">Pikachu #025</a>'
                else:
                    payload = f'<h1>{name} ({category})</h1><h2>Full Price Guide: {name} ({category})</h2><div>PSA 10 $100.00</div><p>All prices are the current market price</p>'
        elif host == "api.tcgdex.net":
            row = {"id": "SV2a-025", "localId": "025", "name": "Pikachu",
                   "set": {"id": "SV2a", "name": "151", "cardCount": {"official": 165, "total": 210}},
                   "variants": {"normal": True, "holo": False, "reverse": False, "firstEdition": False}}
            if case.startswith("coordinate_names_"):
                row.update(id="SV2a-169", localId="169", name="リザード")
                if case.endswith("wrong_rest_name"):
                    row["name"] = "リザードン"
            if case.startswith("pt_native_"):
                row.update(id="SV8-136", localId="136", name="ピカチュウex")
                row["set"] = {"id": "SV8", "name": "Super Electric Breaker", "cardCount": {"official": 106}}
            if case.startswith("ppt_sv8a_"):
                row.update(id="SV8a-209", localId="209", name="サンダースex")
                row["set"] = {"id": "SV8a", "name": "テラスタルフェスex", "cardCount": {"official": 187}}
            if path.endswith("/sets"):
                payload = [row["set"]]
            elif "/cards/" in path or "/sets/SV2a/" in path or "/sets/SV8/" in path or "/sets/SV8a/" in path:
                payload = row
            elif path.endswith("/cards"):
                payload = [row]
            else:
                status = 404
            if case.endswith("unresolved") or case.startswith(("source_alias_", "rest_alias_")):
                status, payload = 404, {}
                if case.startswith(("source_alias_", "rest_alias_")) and path.endswith(("/cards", "/sets")):
                    status, payload = 200, []
                if case.startswith("rest_alias_") and path.endswith("/ja/sets/SV8/112"):
                    status, payload = 200, {"id": "SV8-112", "localId": "112", "name": "レアコイル",
                        "set": {"id": "SV8", "name": "超電ブレイカー", "cardCount": {"official": 106}},
                        "variants": {"holo": True}}
        elif host == "www.pokemonpricetracker.com":
            row = {"id": "fixture-ppt", "name": "Pikachu", "setName": "151",
                   "setId": "23599", "cardNumber": "25/165", "language": "japanese",
                   "externalCatalogId": "SV2a-025", "tcgPlayerId": "fixture-025",
                   "ebay": {"salesByGrade": {"psa10": {"count": 5, "medianPrice": 100,
                                                        "lastSaleDate": "2026-09-09"}}}}
            if case.startswith("ppt_sv8a_"):
                row.update(name="Jolteon ex", setName="SV8a: Terastal Fest ex", setId="23821", cardNumber="209/187", externalCatalogId="SV8a-209")
            change = not case.endswith("deep_name") or "tcgPlayerId" in kwargs.get("params", {})
            if change:
                if case.endswith(("wrong_name", "deep_name")):
                    row["name"] = "Charizard"
                if case.endswith("wrong_set"):
                    row["setName"] = "Base Set"
                if case.endswith("wrong_catalog"):
                    row["externalCatalogId"] = "base1-4"
                if case.endswith("wrong_denominator"):
                    row["cardNumber"] = "25/999"
                if case.endswith("wrong_language"):
                    row["language"] = "english"
                if case.endswith("wrong_variant"):
                    row["variant"] = "Master Ball"
                if case.endswith("unicode_name"):
                    row["name"] = "リザードン"
                if case.endswith("unicode_set"):
                    row["setName"] = "別のセット"
                if case.endswith("fallback_variant"):
                    row.pop("externalCatalogId")
                    row["setName"] = "SV2a: Pokemon Card 151"
                    row["variant"] = "Master Ball"
                if case.endswith("prefix_wrong_set"):
                    row.pop("externalCatalogId")
                    row["setName"] = "SV2a: Base Set"
                if case.endswith("deep_coordinate") and "tcgPlayerId" in kwargs.get("params", {}):
                    row["tcgPlayerId"] = "contradictory-coordinate"
            payload = {"data": [row]}
        elif host == "raw.githubusercontent.com":
            status = 404
            if case.startswith("ppt_sv8a_") and path.endswith("/data-asia/SV/SV8a/209.ts"):
                status = 200
                payload = 'import Set from "../SV8a";\nconst card: Card = {\n set: Set,\n name: {ja: "サンダースex", id: "Jolteon ex"},\n variants: [{type: "normal"}]\n};'
            if case.startswith("coordinate_names_") and path.endswith("/data-asia/SV/SV2a/169.ts") and not case.endswith("missing_source"):
                status = 200
                names = 'ja: "リザード", id: "Charmeleon",'
                if case.endswith("missing_native"):
                    names = 'id: "Charmeleon",'
                payload = 'import Set from "../SV2a";\nconst card: Card = {\n set: Set,\n name: {' + names + '},\n variants: [{type: "holo"}]\n};'
            if case.startswith("source_alias_") and path.endswith("/data-asia/SV/SV8/112.ts"):
                # Relevant root-name / finish fields of immutable SV8-112
                # (af33c9ac): レアコイル, never ピカチュウ.
                status = 200
                payload = 'import Set from "../SV8";\nconst card: Card = {\n set: Set,\n name: {ja: "レアコイル"},\n variants: [{type: "holo"}]\n};'
        else:
            raise AssertionError(f"Unexpected HTTP boundary {host} {path}")
        response = requests.Response()
        response.status_code, response.url, response.encoding = status, url, "utf-8"
        if host == "www.pokemonpricetracker.com":
            response.headers.update({"X-Api-Calls-Consumed": "1", "X-Ratelimit-Daily-Remaining": "20000"})
        response._content = (payload if isinstance(payload, str) else json.dumps(payload)).encode()
        return response

    with patch.object(requests.sessions.Session, "request", request):
        import v4_global_marketplace_notify_resilient as runner
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with patch.object(sys, "argv", ["runner", "--help"]):
                try:
                    runner.main()
                except SystemExit as result:
                    assert result.code == 0
            runner.confirmed.install_global_external_market_stack()
        import v4_global_economic_confirmation as econ
        from v4_global_market_core import CommercialIdentity
        identity = CommercialIdentity("Pikachu", "151", "25/165", "ja", "PSA", "10")
        if case.startswith("ppt_sv8a_"):
            identity = CommercialIdentity("Jolteon ex", "Festival Terastal ex", "209/187", "ja", "PSA", "10")
        lot = econ._lot_for_identity(identity)
        if case.startswith("pt_access_"):
            import os
            import watcher
            import v4_canonical_multimarket as mm
            from datetime import datetime, timezone
            lot, canonical = econ.resolve_global_canonical(identity)
            assert canonical.status == "EXACT", canonical
            budget = mm.RequestBudget()
            with patch.object(mm, "POKETRACE_API_KEY", "fixture"), patch.object(mm, "POKETRACE_ENABLED", True), patch.object(mm, "POKETRACE_PACING_SECONDS", 0), patch.dict(os.environ, {"GLOBAL_POKETRACE_CAPABILITY_PROBE": "true" if case.endswith("free_probe") else "false"}):
                evidence = mm._poketrace_evidence(lot, canonical, budget, datetime.now(timezone.utc))
                again = mm._poketrace_evidence(lot, canonical, budget, datetime.now(timezone.utc)) if "free" in case else evidence
            print(case, evidence.status, evidence.note, "requests", budget.poketrace_requests)
            if case.endswith("empty"):
                assert evidence.status == watcher.EXTERNAL_CLEAN_NO_MATCH, evidence
            elif case.endswith("missing_tier"):
                assert evidence.status == watcher.EXTERNAL_CLEAN_INSUFFICIENT, evidence
            elif case.endswith("auth_429"):
                assert evidence.status == watcher.EXTERNAL_RATE_LIMITED, evidence
            else:
                assert evidence.status in watcher.EXTERNAL_RETRY_STATUSES, evidence
                assert evidence.status not in watcher.EXTERNAL_CACHEABLE_STATUSES, evidence
                if "free" in case or case.endswith("403"):
                    assert "ACCESS_RESTRICTED" in evidence.note, evidence
            assert evidence.estimate is None and again.estimate is None
            if "free" in case:
                assert budget.poketrace_requests == (2 if case.endswith("free_probe") else 1), calls
            fallback = watcher.ExternalMarketEvidence("fixture", watcher.EXTERNAL_CLEAN_NO_MATCH, watcher.EVIDENCE_UNAVAILABLE, "fixture")
            combined = mm._combine_retry_with_fallback(evidence, fallback)
            if evidence.status in watcher.EXTERNAL_RETRY_STATUSES:
                assert combined.status == evidence.status
            return
        if case.startswith("pt_native_"):
            import v4_canonical_multimarket as mm
            identity = CommercialIdentity("ピカチュウex", "Super Electric Breaker", "136/106", "ja", "PSA", "10")
            lot, canonical = econ.resolve_global_canonical(identity)
            assert canonical.status == "EXACT", canonical
            candidate = {"name": "リザードンex" if case.endswith("wrong_name") else "ピカチュウex", "cardNumber": "136/106", "game": "pokemon-japanese", "productType": "single", "set": {"name": "Super Electric Breaker"}, "variant": "Normal"}
            actual = mm._candidate_exact_for_canonical(lot, canonical, candidate)
            print(case, actual)
            assert actual == case.endswith("_valid"), candidate
            return
        if case.startswith("coordinate_names_"):
            identity = CommercialIdentity("Charizard" if case.endswith("wrong_name") else "Charmeleon", "Base Set" if case.endswith("wrong_set") else "151", "169/165", "ja", "PSA", "10")
            lot, canonical = econ.resolve_global_canonical(identity)
            print(case, canonical)
            assert (canonical.status == "EXACT") == case.endswith("_valid"), canonical
            if canonical.status == "EXACT":
                assert canonical.name == "Charmeleon" and canonical.card_id == "SV2a-169"
            return
        if case.startswith(("source_alias_", "rest_alias_")):
            identity = CommercialIdentity("レアコイル" if case.endswith("_valid") else "ピカチュウ", "Super Electric Breaker", "112/106", "ja", "PSA", "10")
            lot, canonical = econ.resolve_global_canonical(identity)
            print(case, canonical)
            assert (canonical.status == "EXACT") == case.endswith("_valid"), canonical
            return
        if case.startswith("pc_"):
            import v4_pricecharting_valuation as pc
            if case.endswith(("wrong_variant", "both_variants", "missing_variant", "valid_variant")):
                lot.variant = "master ball"
            provider = pc.PriceChartingProvider(pc.PriceChartingConfig(
                token="fixture" if case.startswith("pc_api") else None,
                public_request_interval_seconds=0, minimum_request_interval_seconds=0), requests.Session())
            result = provider.lookup(lot)
        elif case.startswith("pt_gate"):
            import v4_canonical_multimarket as mm
            lot, canonical = econ.resolve_global_canonical(identity)
            assert canonical.status == "EXACT", canonical
            candidate = {"name": "Pikachu (Japanese)", "cardNumber": "25/165", "game": "pokemon-japanese", "productType": "single", "set": {"name": "151"}, "variant": "Normal"}
            if case.endswith("wrong_set"):
                candidate["set"]["name"] = "SV2a: Base Set"
            if case.endswith("both_editions"):
                lot.variant = "First Edition"
                candidate["variant"] = "Normal First Edition Unlimited"
            if case.endswith("both_balls"):
                lot.variant = "Master Ball"
                candidate["variant"] = "Normal Master Ball Poke Ball"
            actual = mm._candidate_exact_for_canonical(lot, canonical, candidate)
            print(case, actual)
            assert actual == case.endswith("_valid"), candidate
            return
        else:
            import v4_global_ppt_confirmation as ppt
            from ecb_fx import ECBCurrencyConverter
            from decimal import Decimal
            from datetime import datetime, timezone
            lot, canonical = econ.resolve_global_canonical(identity)
            assert (canonical.status == "EXACT") == (not case.endswith("unresolved")), (canonical, calls)
            # FX is a separate transport boundary, never an identity/EXACT mock.
            with patch.object(ECBCurrencyConverter, "convert", lambda self, amount, *a: Decimal(amount)):
                result = runner.confirmed.fetch_snapshot(identity, api_key="fixture", budget=ppt.PptBudget(interval_seconds=0),
                    session=requests.Session(), fx=ECBCurrencyConverter(), canonical=canonical,
                    now=datetime(2026, 9, 10, tzinfo=timezone.utc))
        positive = case.endswith(("_valid", "_valid_variant"))
        print(case, result.status, result.note)
        assert (result.status == "MATCHED") == positive, result


class ValuationIdentityRuntimeTests(unittest.TestCase):
    def check_case(self, case):
        child = subprocess.run([sys.executable, "-B", __file__, case], cwd=ROOT,
                               text=True, capture_output=True, timeout=45)
        self.assertEqual(child.returncode, 0, child.stdout + child.stderr)


for provider in ("pc_api", "pc_public"):
    for scenario in ("valid", "valid_variant", "wrong_name", "wrong_set", "wrong_language",
                     "wrong_variant", "both_variants", "missing_variant"):
        case = f"{provider}_{scenario}"
        setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("valid", "wrong_name", "wrong_set", "wrong_catalog", "wrong_denominator", "wrong_language", "wrong_variant", "deep_name", "unresolved", "unicode_name", "unicode_set", "fallback_variant", "prefix_wrong_set", "deep_coordinate"):
    case = "ppt_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("valid", "wrong_set", "both_editions", "both_balls"):
    case = "pt_gate_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for route in ("source_alias_", "rest_alias_"):
    for scenario in ("valid", "wrong_name"):
        case = route + scenario
        setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("valid", "wrong_name", "wrong_rest_name", "wrong_set", "missing_source", "missing_native"):
    case = "coordinate_names_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("valid", "wrong_name"):
    case = "pt_native_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("free", "free_probe", "auth_401", "auth_403", "auth_429", "search_403", "unknown_plan", "empty", "missing_tier", "malformed"):
    case = "pt_access_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))
for scenario in ("valid", "wrong_set", "wrong_language", "wrong_catalog"):
    case = "ppt_sv8a_" + scenario
    setattr(ValuationIdentityRuntimeTests, "test_" + case, lambda self, case=case: self.check_case(case))

if __name__ == "__main__":
    if len(sys.argv) == 2:
        run_case(sys.argv[1])
    else:
        unittest.main()
