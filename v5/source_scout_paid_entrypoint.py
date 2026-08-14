from __future__ import annotations

from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base


def _cardmarket_value(row: Mapping[str, object]) -> float | None:
    direct = row.get("cardmarketPrices")
    if isinstance(direct, Mapping):
        value = scout.num(
            direct.get("marketEur"),
            direct.get("trendEur"),
            direct.get("lowEur"),
        )
        if value is not None:
            return value
    return base._cardmarket_value(row)


def _graded_from_ppt(row: Mapping[str, object]) -> tuple[bool, float | None]:
    ebay = row.get("ebay")
    if isinstance(ebay, Mapping):
        sales = ebay.get("salesByGrade")
        if isinstance(sales, Mapping):
            psa10 = sales.get("psa10")
            if isinstance(psa10, Mapping):
                return bool(sales), scout.num(
                    psa10.get("averagePrice"),
                    psa10.get("average"),
                    psa10.get("avg"),
                    psa10.get("median"),
                    psa10.get("price"),
                )
            return bool(sales), scout.num(psa10)
    return base._graded_from_ppt(row)


def _rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    return scout.maps(payload.get("data"))


def _match(identity, rows: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [
        row
        for row in rows
        if scout.candidate_identity(
            identity,
            name=row.get("name"),
            set_name=row.get("setName") or row.get("set_name"),
            number=row.get("cardNumber") or row.get("number"),
        )
        == "EXACT"
    ]


def pokemonpricetracker_api(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Provider-native paid API probe with EN/JP exact cards and EN anchors for FR."""
    client = scout.SafeClient("pokemonpricetracker", call_cap=60, interval=0.08)
    anchor_client = scout.SafeClient("tcgdex_ppt_anchor", call_cap=10, interval=0.03)
    anchor_cache = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str]] = []

    for index, card in enumerate(panel):
        language = scout.lang(card.identity.language)
        identity = card.identity
        anchor_only = False
        if language == "fr":
            anchor = base._english_anchor(card, anchor_client, anchor_cache)
            if anchor is None:
                obs = scout.Observation("pokemonpricetracker", card.label)
                obs.identity = "UNRESOLVED"
                out.append(obs)
                continue
            identity = anchor
            anchor_only = True

        params: dict[str, object] = {
            "search": " ".join(filter(None, (identity.card_name, identity.card_number))),
            "setName": identity.set or "",
            "limit": 10,
        }
        if language == "ja":
            params["language"] = "japanese"

        response, payload = client.request(
            "GET",
            "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params=params,
        )
        obs = scout.Observation("pokemonpricetracker", card.label)
        if response:
            base._update_quota(client.runtime, response)
        if not response or response.status_code != 200:
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"
            out.append(obs)
            continue

        rows = _rows(payload)
        exact = _match(identity, rows)

        # Provider set naming occasionally differs. One tightly bounded fallback
        # drops setName but keeps card name + collector number.
        if not exact:
            fallback_params: dict[str, object] = {
                "search": " ".join(filter(None, (identity.card_name, identity.card_number))),
                "limit": 10,
            }
            if language == "ja":
                fallback_params["language"] = "japanese"
            response2, payload2 = client.request(
                "GET",
                "https://www.pokemonpricetracker.com/api/v2/cards",
                headers={"Authorization": f"Bearer {key}"},
                params=fallback_params,
            )
            if response2:
                base._update_quota(client.runtime, response2)
            if response2 and response2.status_code == 200:
                rows = _rows(payload2)
                exact = _match(identity, rows)

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
                depth.append((index, str(tcg_id)))
        elif len(exact) > 1:
            obs.identity = "AMBIGUOUS"
        elif rows:
            obs.identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            obs.identity = "UNRESOLVED"
        out.append(obs)

    for index, tcg_id in depth:
        response, payload = client.request(
            "GET",
            "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params={
                "tcgPlayerId": tcg_id,
                "includeHistory": "true",
                "includeEbay": "true",
                "includeCardmarket": "true",
                "days": 180,
                "maxDataPoints": 180,
            },
        )
        if response:
            base._update_quota(client.runtime, response)
        if not response or response.status_code != 200:
            continue
        rows = _rows(payload)
        if not rows:
            continue
        row = rows[0]
        out[index].history = "180D_RETURNED" if row.get("priceHistory") else "NONE"
        graded, psa10 = _graded_from_ppt(row)
        out[index].graded_available = graded
        out[index].psa10_usd = psa10
        out[index].raw_eur = _cardmarket_value(row)
        ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
        try:
            if ebay.get("totalSales") is not None:
                out[index].liquidity = int(ebay["totalSales"])
        except (TypeError, ValueError):
            pass

    return out, client.runtime


def main() -> int:
    # Monkeypatch the language benchmark with the provider-native paid adapter.
    base.pokemonpricetracker_api = pokemonpricetracker_api
    base._cardmarket_value = _cardmarket_value
    base._graded_from_ppt = _graded_from_ppt
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
