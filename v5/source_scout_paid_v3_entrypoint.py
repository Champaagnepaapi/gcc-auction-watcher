from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base
from . import source_scout_paid_entrypoint as paid
from . import source_scout_paid_v2_entrypoint as v2


PPT_EVIDENCE: list[dict[str, object]] = []
PPT_PROBES: list[dict[str, object]] = []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _payload_rows(payload: object) -> list[Mapping[str, object]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, Mapping)]
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, Mapping)]
    if isinstance(data, Mapping):
        return [data]
    return []


def _set_id(row: Mapping[str, object]) -> str:
    for key in ("id", "setId", "set_id", "code", "setCode", "set_code"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _set_name(row: Mapping[str, object]) -> str:
    for key in ("name", "setName", "set_name"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _exact_jp_set(identity, code: str, rows: Sequence[Mapping[str, object]]) -> Mapping[str, object] | None:
    expected_name = scout.norm(identity.set)
    expected_code = scout.norm(code)
    matches: list[Mapping[str, object]] = []
    for row in rows:
        name = scout.norm(_set_name(row))
        row_id = scout.norm(_set_id(row))
        if expected_name and name == expected_name:
            matches.append(row)
            continue
        if expected_code and row_id == expected_code:
            matches.append(row)
    return matches[0] if len(matches) == 1 else None


def _request(
    client: scout.SafeClient,
    key: str,
    url: str,
    params: Mapping[str, object],
) -> tuple[object | None, object | None]:
    response, payload = client.request(
        "GET",
        url,
        headers={"Authorization": f"Bearer {key}"},
        params=dict(params),
    )
    if response:
        base._update_quota(client.runtime, response)
    return response, payload


def _append_evidence(
    *,
    index: int,
    card: scout.PanelCard,
    identity_status: str,
    tcg_id: str,
    kind: str,
    payload: object,
) -> None:
    PPT_EVIDENCE.append(
        {
            "provider": "pokemonpricetracker",
            "retrieved_at": _utc_now(),
            "panel_index": index,
            "card_label": card.label,
            "tcgdex_id": card.tcgdex_id,
            "tcgdex_language": card.tcgdex_language,
            "identity_status": identity_status,
            "evidence_kind": kind,
            "canonical_identity": {
                "name": card.identity.card_name,
                "set": card.identity.set,
                "card_number": card.identity.card_number,
                "language": card.identity.language,
                "finish": card.identity.finish,
                "edition": card.identity.edition,
            },
            "provider_tcgplayer_id": tcg_id,
            "provider_payload": payload,
        }
    )


def _apply_deep_row(obs: scout.Observation, row: Mapping[str, object]) -> None:
    if row.get("priceHistory"):
        obs.history = "180D_RETURNED"
    graded, psa10 = paid._graded_from_ppt(row)
    if graded:
        obs.graded_available = True
    if psa10 is not None:
        obs.psa10_usd = psa10
    cardmarket = paid._cardmarket_value(row)
    if cardmarket is not None:
        obs.raw_eur = cardmarket
    ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
    try:
        if ebay.get("totalSales") is not None:
            obs.liquidity = int(ebay["totalSales"])
    except (TypeError, ValueError):
        pass


def pokemonpricetracker_api(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """API-plan benchmark with deterministic JP set resolution.

    EN keeps the previously working name+number search.
    FR uses the exact English TCGdex twin only as a market anchor.
    JP first resolves the Japanese PPT set, then fetches that set and matches the
    collector number. This avoids relying on PPT's Japanese free-text search,
    which returned zero candidates for the benchmark panel.

    Deep evidence is requested separately for history, eBay graded data, and
    Cardmarket. Each successful provider response is retained raw and can be
    ingested independently into Neon.
    """
    client = scout.SafeClient("pokemonpricetracker", call_cap=90, interval=1.10)
    anchor_client = scout.SafeClient("tcgdex_ppt_anchor", call_cap=10, interval=0.05)
    anchor_cache = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str, str]] = []

    for index, card in enumerate(panel):
        language = scout.lang(card.identity.language)
        identity = card.identity
        anchor_only = False
        code = v2._set_code(card)
        rows: list[Mapping[str, object]] = []
        exact: list[Mapping[str, object]] = []
        probe: dict[str, object] = {
            "card_label": card.label,
            "tcgdex_id": card.tcgdex_id,
            "language": language,
            "expected_set": identity.set,
            "expected_set_code": code,
            "expected_number": identity.card_number,
            "steps": [],
        }

        if language == "fr":
            anchor = base._english_anchor(card, anchor_client, anchor_cache)
            if anchor is None:
                obs = scout.Observation("pokemonpricetracker", card.label)
                obs.identity = "UNRESOLVED"
                out.append(obs)
                continue
            identity = anchor
            anchor_only = True

        if language == "ja":
            set_response, set_payload = _request(
                client,
                key,
                "https://www.pokemonpricetracker.com/api/v2/sets",
                {"language": "japanese", "search": identity.set or "", "limit": 20},
            )
            set_rows = _payload_rows(set_payload)
            provider_set = _exact_jp_set(identity, code, set_rows)
            probe["steps"].append(
                {
                    "step": "set_search",
                    "http": getattr(set_response, "status_code", None),
                    "candidate_count": len(set_rows),
                    "candidates": [
                        {"id": _set_id(row), "name": _set_name(row)} for row in set_rows[:20]
                    ],
                }
            )
            if provider_set is not None:
                provider_set_id = _set_id(provider_set)
                card_response, card_payload = _request(
                    client,
                    key,
                    "https://www.pokemonpricetracker.com/api/v2/cards",
                    {"language": "japanese", "setId": provider_set_id, "limit": 100},
                )
                rows = paid._rows(card_payload)
                exact = v2._match(identity, rows, set_code=code, ignore_name=True)
                probe["steps"].append(
                    {
                        "step": "set_cards",
                        "http": getattr(card_response, "status_code", None),
                        "provider_set_id": provider_set_id,
                        "candidate_count": len(rows),
                        "matched": len(exact),
                        "candidates": v2._jp_candidate_summary(rows),
                    }
                )
            else:
                # Direct set-name filters are a bounded fallback when the set
                # search endpoint uses a different display name than TCGdex.
                for field in ("set", "setName"):
                    card_response, card_payload = _request(
                        client,
                        key,
                        "https://www.pokemonpricetracker.com/api/v2/cards",
                        {"language": "japanese", field: identity.set or "", "limit": 100},
                    )
                    rows = paid._rows(card_payload)
                    exact = v2._match(identity, rows, set_code=code, ignore_name=True)
                    probe["steps"].append(
                        {
                            "step": f"cards_{field}",
                            "http": getattr(card_response, "status_code", None),
                            "candidate_count": len(rows),
                            "matched": len(exact),
                            "candidates": v2._jp_candidate_summary(rows),
                        }
                    )
                    if exact:
                        break
        else:
            search_text = " ".join(filter(None, (identity.card_name, identity.card_number)))
            for params in (
                {"search": search_text, "setName": identity.set or "", "limit": 10},
                {"search": search_text, "limit": 10},
            ):
                response, payload = _request(
                    client,
                    key,
                    "https://www.pokemonpricetracker.com/api/v2/cards",
                    params,
                )
                rows = paid._rows(payload)
                exact = v2._match(identity, rows, set_code=code, ignore_name=False)
                if exact:
                    break

        obs = scout.Observation("pokemonpricetracker", card.label)
        if len(exact) == 1:
            row = exact[0]
            obs.identity = "ANCHOR_ONLY" if anchor_only else "EXACT"
            prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            obs.raw_usd = scout.num(prices.get("market"), prices.get("low"))
            obs.freshness = scout.freshest(prices.get("lastUpdated"), row.get("updatedAt"))
            variants = row.get("variants") if isinstance(row.get("variants"), Mapping) else {}
            obs.variant = scout.variant_status(
                card.identity,
                list(variants.keys()) + [prices.get("primaryPrinting"), row.get("printing")],
            )
            obs.language = "NOT_EXPOSED" if anchor_only else "EXACT"
            tcg_id = row.get("tcgPlayerId") or row.get("tcgplayerId")
            if tcg_id:
                depth.append((index, str(tcg_id), language))
            else:
                probe["missing_tcgPlayerId"] = True
                probe["matched_row_keys"] = sorted(str(value) for value in row.keys())
        elif len(exact) > 1:
            obs.identity = "AMBIGUOUS"
        elif rows:
            obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            obs.identity = "UNRESOLVED"

        if language == "ja" or (len(exact) == 1 and not (exact[0].get("tcgPlayerId") or exact[0].get("tcgplayerId"))):
            probe["identity_status"] = obs.identity
            PPT_PROBES.append(probe)
        out.append(obs)

    for index, tcg_id, language in depth:
        card = panel[index]
        lang_params = {"language": "japanese"} if language == "ja" else {}
        requests = (
            (
                "history",
                {
                    "tcgPlayerId": tcg_id,
                    "includeHistory": "true",
                    "days": 180,
                    "maxDataPoints": 180,
                    **lang_params,
                },
            ),
            (
                "ebay",
                {"tcgPlayerId": tcg_id, "includeEbay": "true", "days": 180, **lang_params},
            ),
            (
                "cardmarket",
                {"tcgPlayerId": tcg_id, "includeCardmarket": "true", **lang_params},
            ),
        )
        deep_probe: dict[str, object] = {
            "card_label": card.label,
            "tcgdex_id": card.tcgdex_id,
            "language": language,
            "tcgPlayerId": tcg_id,
            "deep": [],
        }
        for kind, params in requests:
            response, payload = _request(
                client,
                key,
                "https://www.pokemonpricetracker.com/api/v2/cards",
                params,
            )
            rows = paid._rows(payload)
            deep_probe["deep"].append(
                {
                    "kind": kind,
                    "http": getattr(response, "status_code", None),
                    "rows": len(rows),
                }
            )
            if not response or response.status_code != 200 or not rows:
                continue
            row = rows[0]
            _apply_deep_row(out[index], row)
            _append_evidence(
                index=index,
                card=card,
                identity_status=out[index].identity,
                tcg_id=tcg_id,
                kind=kind,
                payload=payload,
            )
        PPT_PROBES.append(deep_probe)

    return out, client.runtime


def _write_evidence() -> None:
    Path("pokemonpricetracker_evidence.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider": "pokemonpricetracker",
                "generated_at": _utc_now(),
                "evidence_count": len(PPT_EVIDENCE),
                "evidence": PPT_EVIDENCE,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    Path("pokemonpricetracker_probe.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "provider": "pokemonpricetracker",
                "generated_at": _utc_now(),
                "probe_count": len(PPT_PROBES),
                "probes": PPT_PROBES,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    PPT_EVIDENCE.clear()
    PPT_PROBES.clear()
    base.pokemonpricetracker_api = pokemonpricetracker_api
    result = base.main()
    _write_evidence()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
