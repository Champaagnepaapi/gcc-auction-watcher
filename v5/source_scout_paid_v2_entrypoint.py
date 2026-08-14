from __future__ import annotations

from typing import Mapping, Sequence

from . import source_scout_benchmark as scout
from . import source_scout_language_entrypoint as base
from . import source_scout_paid_entrypoint as paid


def _set_code(card: scout.PanelCard) -> str:
    return str(card.tcgdex_id or "").split("-", 1)[0].strip()


def _set_ok(expected: object, actual: object, code: str = "") -> bool:
    left = scout.norm(expected)
    right = scout.norm(actual)
    if not left or not right:
        return False
    if left == right or right.endswith(left) or left.endswith(right):
        return True
    code_norm = scout.norm(code)
    if code_norm and code_norm in right.split():
        return True
    try:
        return scout._set_similarity(expected, actual, None) >= 0.86
    except Exception:
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
        set_name = row.get("setName") or row.get("set_name")
        number = row.get("cardNumber") or row.get("number")
        if not ignore_name:
            if not name or scout._normalize_card_name(name) != scout._normalize_card_name(identity.card_name):
                continue
        if identity.set and not _set_ok(identity.set, set_name, set_code):
            continue
        if identity.card_number and not scout.number_ok(identity.card_number, number):
            continue
        exact.append(row)
    return exact


def pokemonpricetracker_api(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Paid PPT probe with tolerant provider-native set/number matching.

    EN: card name + collector number, tolerant provider set prefixes.
    FR: corresponding EN TCGdex anchor, then Cardmarket EUR/graded/history.
    JP: language=japanese and strict set-code + collector-number identity; card
    names are not trusted because the provider currently returns many JP rows
    with English display names.
    """
    client = scout.SafeClient("pokemonpricetracker", call_cap=60, interval=0.08)
    anchor_client = scout.SafeClient("tcgdex_ppt_anchor", call_cap=10, interval=0.03)
    anchor_cache = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str]] = []

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
            search_text = " ".join(filter(None, (code, identity.card_number)))
        else:
            search_text = " ".join(filter(None, (identity.card_name, identity.card_number)))

        params: dict[str, object] = {
            "search": search_text,
            "setName": code if language == "ja" else (identity.set or ""),
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

        rows = paid._rows(payload)
        exact = _match(
            identity,
            rows,
            set_code=code,
            ignore_name=(language == "ja"),
        )

        if not exact:
            fallback_params: dict[str, object] = {
                "search": search_text,
                "limit": 20 if language == "ja" else 10,
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
                rows = paid._rows(payload2)
                exact = _match(
                    identity,
                    rows,
                    set_code=code,
                    ignore_name=(language == "ja"),
                )

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

    return out, client.runtime


def main() -> int:
    # Only replace the provider function. Do not monkeypatch the base parser
    # helpers: the paid helper functions intentionally fall back to them, and
    # replacing them with the paid helpers creates infinite recursion.
    base.pokemonpricetracker_api = pokemonpricetracker_api
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
