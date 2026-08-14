from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base
from . import source_scout_paid_entrypoint as paid


PPT_EVIDENCE: list[dict[str, object]] = []
PPT_JP_PROBES: list[dict[str, object]] = []


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _set_code(card: scout.PanelCard) -> str:
    return str(card.tcgdex_id or "").split("-", 1)[0].strip()


def _row_set_values(row: Mapping[str, object]) -> list[object]:
    values: list[object] = []
    for key in ("setName", "set_name", "setId", "set_id", "setCode", "set_code", "set"):
        value = row.get(key)
        if isinstance(value, Mapping):
            for nested_key in ("id", "name", "code", "setId", "setCode"):
                nested = value.get(nested_key)
                if nested not in (None, ""):
                    values.append(nested)
        elif value not in (None, ""):
            values.append(value)
    return values


def _set_ok(expected: object, actual_values: Sequence[object], code: str = "") -> bool:
    left = scout.norm(expected)
    code_norm = scout.norm(code)
    if not left and not code_norm:
        return False
    for actual in actual_values:
        right = scout.norm(actual)
        if not right:
            continue
        if code_norm and (right == code_norm or code_norm in right.split()):
            return True
        if left and (left == right or right.endswith(left) or left.endswith(right)):
            return True
        if left:
            try:
                if scout._set_similarity(expected, actual, None) >= 0.86:
                    return True
            except Exception:
                pass
    return False


def _match(
    identity,
    rows: Sequence[Mapping[str, object]],
    *,
    set_code: str = "",
    ignore_name: bool = False,
) -> list[Mapping[str, object]]:
    exact: list[Mapping[str, object]] = []
    for row in rows:
        name = row.get("name")
        number = row.get("cardNumber") or row.get("number")
        if not ignore_name:
            if not name or scout._normalize_card_name(name) != scout._normalize_card_name(identity.card_name):
                continue
        if identity.set and not _set_ok(identity.set, _row_set_values(row), set_code):
            continue
        if identity.card_number and not scout.number_ok(identity.card_number, number):
            continue
        exact.append(row)
    return exact


def _jp_candidate_summary(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    summaries: list[dict[str, object]] = []
    for row in rows[:20]:
        summaries.append(
            {
                "name": row.get("name"),
                "cardNumber": row.get("cardNumber") or row.get("number"),
                "set_values": [str(value) for value in _row_set_values(row)],
                "tcgPlayerId": row.get("tcgPlayerId") or row.get("tcgplayerId"),
                "language": row.get("language"),
            }
        )
    return summaries


def pokemonpricetracker_api(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Paid PPT probe with provider-native EN/FR/JP matching.

    EN: card name + collector number, tolerant provider set prefixes.
    FR: corresponding EN TCGdex anchor, then Cardmarket EUR/graded/history.
    JP: language=japanese; query by collector number first and validate using
    provider set id/name/code + exact collector number. Card display names are
    deliberately not identity evidence because provider JP rows may expose an
    English display name.

    For every resolved deep lookup, the complete provider response is retained
    in-memory and written after the benchmark to a sidecar JSON file. This is
    intentionally raw provider evidence, not a rewritten valuation.
    """
    client = scout.SafeClient("pokemonpricetracker", call_cap=60, interval=0.08)
    anchor_client = scout.SafeClient("tcgdex_ppt_anchor", call_cap=10, interval=0.03)
    anchor_cache = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str, str]] = []

    for index, card in enumerate(panel):
        language = scout.lang(card.identity.language)
        identity = card.identity
        anchor_only = False
        code = _set_code(card)

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
            attempts: list[dict[str, object]] = [
                {"language": "japanese", "search": identity.card_number or "", "limit": 100},
                {"language": "japanese", "search": identity.card_name or "", "limit": 100},
            ]
        else:
            attempts = [
                {
                    "search": " ".join(filter(None, (identity.card_name, identity.card_number))),
                    "setName": identity.set or "",
                    "limit": 10,
                },
                {
                    "search": " ".join(filter(None, (identity.card_name, identity.card_number))),
                    "limit": 10,
                },
            ]

        rows: list[Mapping[str, object]] = []
        exact: list[Mapping[str, object]] = []
        attempted_queries: list[dict[str, object]] = []
        request_error: str | None = None
        for params in attempts:
            if not str(params.get("search") or "").strip():
                continue
            attempted_queries.append({key: value for key, value in params.items() if key != "limit"})
            response, payload = client.request(
                "GET",
                "https://www.pokemonpricetracker.com/api/v2/cards",
                headers={"Authorization": f"Bearer {key}"},
                params=params,
            )
            if response:
                base._update_quota(client.runtime, response)
            if not response or response.status_code != 200:
                request_error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"
                continue
            rows = paid._rows(payload)
            exact = _match(
                identity,
                rows,
                set_code=code,
                ignore_name=(language == "ja"),
            )
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
        elif len(exact) > 1:
            obs.identity = "AMBIGUOUS"
        elif rows:
            obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            obs.identity = "UNRESOLVED"
            if request_error:
                obs.error = request_error

        if language == "ja" and len(exact) != 1:
            PPT_JP_PROBES.append(
                {
                    "card_label": card.label,
                    "tcgdex_id": card.tcgdex_id,
                    "expected": {
                        "name": identity.card_name,
                        "set": identity.set,
                        "set_code": code,
                        "card_number": identity.card_number,
                    },
                    "queries": attempted_queries,
                    "identity_status": obs.identity,
                    "candidate_count_last_attempt": len(rows),
                    "candidates": _jp_candidate_summary(rows),
                }
            )
        out.append(obs)

    for index, tcg_id, language in depth:
        retrieved_at = _utc_now()
        params: dict[str, object] = {
            "tcgPlayerId": tcg_id,
            "includeHistory": "true",
            "includeEbay": "true",
            "includeCardmarket": "true",
            "days": 180,
            "maxDataPoints": 180,
        }
        if language == "ja":
            params["language"] = "japanese"
        response, payload = client.request(
            "GET",
            "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params=params,
        )
        if response:
            base._update_quota(client.runtime, response)
        if not response or response.status_code != 200:
            continue
        rows = paid._rows(payload)
        if not rows:
            continue
        row = rows[0]
        out[index].history = "180D_RETURNED" if row.get("priceHistory") else "NONE"
        graded, psa10 = paid._graded_from_ppt(row)
        out[index].graded_available = graded
        out[index].psa10_usd = psa10
        out[index].raw_eur = paid._cardmarket_value(row)
        ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
        try:
            if ebay.get("totalSales") is not None:
                out[index].liquidity = int(ebay["totalSales"])
        except (TypeError, ValueError):
            pass

        card = panel[index]
        PPT_EVIDENCE.append(
            {
                "provider": "pokemonpricetracker",
                "retrieved_at": retrieved_at,
                "panel_index": index,
                "card_label": card.label,
                "tcgdex_id": card.tcgdex_id,
                "tcgdex_language": card.tcgdex_language,
                "identity_status": out[index].identity,
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

    return out, client.runtime


def _write_evidence() -> None:
    document = {
        "schema_version": 1,
        "provider": "pokemonpricetracker",
        "generated_at": _utc_now(),
        "evidence_count": len(PPT_EVIDENCE),
        "evidence": PPT_EVIDENCE,
    }
    Path("pokemonpricetracker_evidence.json").write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    Path("pokemonpricetracker_jp_probe.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "provider": "pokemonpricetracker",
                "generated_at": _utc_now(),
                "probe_count": len(PPT_JP_PROBES),
                "probes": PPT_JP_PROBES,
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    # Only replace the provider function. Do not monkeypatch the base parser
    # helpers: the paid helper functions intentionally fall back to them, and
    # replacing them with the paid helpers creates infinite recursion.
    PPT_EVIDENCE.clear()
    PPT_JP_PROBES.clear()
    base.pokemonpricetracker_api = pokemonpricetracker_api
    result = base.main()
    _write_evidence()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
