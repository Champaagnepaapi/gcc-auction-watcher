from __future__ import annotations

import json
import os
import statistics
import sys
from typing import Mapping, Sequence
from urllib.parse import quote

from . import source_scout_benchmark as scout
from .models import CardIdentity

# Robot Pokémon purchase scope: only English, French, and Japanese cards matter.
LANGUAGES: Sequence[str] = ("en", "fr", "ja")
CARDS_PER_LANGUAGE = 6
PANEL_SIZE = len(LANGUAGES) * CARDS_PER_LANGUAGE


def _spread_indices(length: int, count: int = 14) -> tuple[int, ...]:
    if length <= 0:
        return ()
    if length <= count:
        return tuple(range(length - 1, -1, -1))
    raw = [round(i * (length - 1) / (count - 1)) for i in range(count)]
    return tuple(dict.fromkeys(reversed(raw)))


def _finish(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    if value.get("holo") is True:
        return "Holo"
    if value.get("reverse") is True:
        return "Reverse Holo"
    return None


def build_language_panel(_client_id: str, _client_secret: str, size: int):
    target = min(size, PANEL_SIZE)
    client = scout.SafeClient(
        "tcgdex_language_seed",
        call_cap=120,
        interval=0.04,
        response_cap=2_000_000,
        total_cap=70_000_000,
    )
    panel: list[scout.PanelCard] = []
    diagnostics: dict[str, object] = {
        "mode": "LANGUAGE_STRATIFIED_TCGDEX_EN_FR_JA",
        "purchase_scope_languages": list(LANGUAGES),
        "languages": {},
    }

    for language in LANGUAGES:
        if len(panel) >= target or client.runtime.blocked:
            break
        before = len(panel)
        response, sets_payload = client.request(
            "GET", f"https://api.tcgdex.net/v2/{quote(language, safe='')}/sets"
        )
        sets = sets_payload if isinstance(sets_payload, list) else []
        if not response or response.status_code != 200:
            diagnostics["languages"][language] = {
                "seeded": 0,
                "error": f"HTTP_{getattr(response, 'status_code', 'REQUEST')}",
            }
            continue

        candidates = []
        for index in _spread_indices(len(sets)):
            row = sets[index]
            if not isinstance(row, Mapping):
                continue
            count = row.get("cardCount") if isinstance(row.get("cardCount"), Mapping) else {}
            try:
                total = int(count.get("total") or 0)
            except (TypeError, ValueError):
                total = 0
            if total >= 10 and row.get("id"):
                candidates.append(str(row["id"]))

        used_sets: set[str] = set()
        for set_id in candidates:
            if (
                len(panel) - before >= CARDS_PER_LANGUAGE
                or len(panel) >= target
                or client.runtime.blocked
            ):
                break
            set_response, set_payload = client.request(
                "GET",
                f"https://api.tcgdex.net/v2/{quote(language, safe='')}/sets/{quote(set_id, safe='')}",
            )
            if (
                not set_response
                or set_response.status_code != 200
                or not isinstance(set_payload, Mapping)
            ):
                continue
            cards = set_payload.get("cards")
            set_name = str(set_payload.get("name") or "").strip()
            if not isinstance(cards, list) or not cards or not set_name:
                continue
            chosen = None
            for card_index in (len(cards) // 2, 0, len(cards) - 1):
                if 0 <= card_index < len(cards) and isinstance(cards[card_index], Mapping):
                    chosen = cards[card_index]
                    break
            if not isinstance(chosen, Mapping):
                continue
            card_id = str(chosen.get("id") or "").strip()
            if not card_id:
                continue
            detail_response, detail = client.request(
                "GET",
                f"https://api.tcgdex.net/v2/{quote(language, safe='')}/cards/{quote(card_id, safe='')}",
            )
            if (
                not detail_response
                or detail_response.status_code != 200
                or not isinstance(detail, Mapping)
            ):
                continue
            name = str(detail.get("name") or chosen.get("name") or "").strip()
            local_id = str(detail.get("localId") or chosen.get("localId") or "").strip()
            detail_set = detail.get("set") if isinstance(detail.get("set"), Mapping) else {}
            canonical_set = str(detail_set.get("name") or set_name).strip()
            if not name or not local_id or not canonical_set or set_id in used_sets:
                continue
            used_sets.add(set_id)
            panel.append(
                scout.PanelCard(
                    identity=CardIdentity(
                        game="Pokémon TCG",
                        card_name=name,
                        set=canonical_set,
                        card_number=local_id,
                        language=language,
                        finish=_finish(detail.get("variants")),
                    ),
                    tcgdex_id=card_id,
                    tcgdex_language=language,
                    marketplace="TCGDEX_LANGUAGE_SEED",
                )
            )

        diagnostics["languages"][language] = {"seeded": len(panel) - before}

    diagnostics["panel_size"] = len(panel)
    diagnostics["tcgdex_seed_calls"] = client.runtime.calls
    diagnostics["tcgdex_seed_bytes"] = client.runtime.bytes_read
    diagnostics["tcgdex_seed_blocked"] = client.runtime.blocked
    return panel, diagnostics


def _english_anchor(
    card: scout.PanelCard,
    client: scout.SafeClient,
    cache: dict[str, CardIdentity | None],
) -> CardIdentity | None:
    if scout.lang(card.identity.language) == "en":
        return card.identity
    if card.tcgdex_id in cache:
        return cache[card.tcgdex_id]
    response, payload = client.request(
        "GET",
        f"https://api.tcgdex.net/v2/en/cards/{quote(card.tcgdex_id, safe='')}",
    )
    if not response or response.status_code != 200 or not isinstance(payload, Mapping):
        cache[card.tcgdex_id] = None
        return None
    set_row = payload.get("set") if isinstance(payload.get("set"), Mapping) else {}
    name = str(payload.get("name") or "").strip()
    set_name = str(set_row.get("name") or "").strip()
    number = str(payload.get("localId") or "").strip()
    if not (name and set_name and number):
        cache[card.tcgdex_id] = None
        return None
    identity = CardIdentity(
        game="Pokémon TCG",
        card_name=name,
        set=set_name,
        card_number=number,
        language="en",
        finish=card.identity.finish,
    )
    cache[card.tcgdex_id] = identity
    return identity


def _update_quota(runtime: scout.Runtime, response: object) -> None:
    headers = getattr(response, "headers", {})
    for header in (
        "X-RateLimit-Daily-Remaining",
        "x-ratelimit-daily-remaining",
        "X-RateLimit-Remaining",
        "x-ratelimit-remaining",
    ):
        if header in headers:
            try:
                runtime.quota_remaining = int(float(headers[header]))
            except (TypeError, ValueError):
                pass


def _cardmarket_value(row: Mapping[str, object]) -> float | None:
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    candidates = [
        row.get("cardmarket"),
        row.get("cardMarket"),
        prices.get("cardmarket"),
        prices.get("cardMarket"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        value = scout.num(
            candidate.get("trendPrice"),
            candidate.get("trend"),
            candidate.get("marketPrice"),
            candidate.get("market"),
            candidate.get("avg7"),
            candidate.get("avg30"),
            candidate.get("lowPrice"),
            candidate.get("low"),
        )
        if value is not None:
            return value
    return None


def _graded_from_ppt(row: Mapping[str, object]) -> tuple[bool, float | None]:
    ebay = row.get("ebay") or row.get("ebayData") or row.get("gradedPrices")
    if not isinstance(ebay, Mapping):
        return False, None
    psa10 = ebay.get("psa10") or ebay.get("PSA_10") or ebay.get("PSA10")
    if isinstance(psa10, Mapping):
        price = scout.num(
            psa10.get("avg"),
            psa10.get("average"),
            psa10.get("median"),
            psa10.get("market"),
            psa10.get("price"),
        )
    else:
        price = scout.num(psa10)
    return bool(ebay), price


def pokemonpricetracker_api(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Paid API-plan benchmark: identity first, then 180d + graded + Cardmarket."""
    client = scout.SafeClient("pokemonpricetracker", call_cap=45, interval=0.08)
    anchor_client = scout.SafeClient("tcgdex_ppt_anchor", call_cap=10, interval=0.03)
    anchor_cache: dict[str, CardIdentity | None] = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str]] = []

    for index, card in enumerate(panel):
        language = scout.lang(card.identity.language)
        identity_for_search = card.identity
        anchor_only = False
        if language == "fr":
            anchor = _english_anchor(card, anchor_client, anchor_cache)
            if anchor is not None:
                identity_for_search = anchor
                anchor_only = True

        query = " ".join(
            filter(
                None,
                (
                    identity_for_search.card_name,
                    identity_for_search.set,
                    identity_for_search.card_number,
                ),
            )
        )
        params: dict[str, object] = {"search": query, "limit": 10}
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
            _update_quota(client.runtime, response)
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            obs.error = f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"
            out.append(obs)
            continue

        rows = scout.maps(payload.get("data"))
        exact = [
            row
            for row in rows
            if scout.candidate_identity(
                identity_for_search,
                name=row.get("name"),
                set_name=row.get("setName") or row.get("set_name"),
                number=row.get("number") or row.get("cardNumber"),
            )
            == "EXACT"
        ]
        if len(exact) == 1:
            row = exact[0]
            obs.identity = "ANCHOR_ONLY" if anchor_only else "EXACT"
            prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            obs.raw_usd = scout.num(
                prices.get("market"), prices.get("mid"), prices.get("low")
            )
            obs.freshness = scout.freshest(
                prices.get("lastUpdated"), row.get("updatedAt")
            )
            obs.variant = scout.variant_status(
                card.identity, [row.get("printing"), row.get("variant")]
            )
            if anchor_only:
                obs.language = "NOT_EXPOSED"
            else:
                obs.language = scout.language_status(
                    card.identity, [row.get("language")]
                )
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
            _update_quota(client.runtime, response)
        if not response or response.status_code != 200 or not isinstance(payload, Mapping):
            continue
        row = payload.get("data")
        if isinstance(row, list):
            row = row[0] if row else None
        if not isinstance(row, Mapping):
            continue
        out[index].history = "180D_RETURNED" if row.get("priceHistory") else "NONE"
        graded, psa10 = _graded_from_ppt(row)
        out[index].graded_available = graded
        out[index].psa10_usd = psa10
        out[index].raw_eur = _cardmarket_value(row) or out[index].raw_eur

    return out, client.runtime


def _fr_language_slice(
    tier: Mapping[str, object], language_code: str = "FR"
) -> tuple[float | None, int]:
    values: list[float] = []
    counts = 0

    top_language = tier.get("language")
    if isinstance(top_language, Mapping):
        row = top_language.get(language_code)
        if isinstance(row, Mapping):
            value = scout.num(
                row.get("median7d"),
                row.get("median30d"),
                row.get("avg"),
                row.get("low"),
            )
            if value is not None:
                values.append(value)
            try:
                counts += int(row.get("saleCount") or 0)
            except (TypeError, ValueError):
                pass

    country = tier.get("country")
    if isinstance(country, Mapping):
        for country_row in country.values():
            if not isinstance(country_row, Mapping):
                continue
            language = country_row.get("language")
            if not isinstance(language, Mapping):
                continue
            row = language.get(language_code)
            if not isinstance(row, Mapping):
                continue
            value = scout.num(
                row.get("median7d"),
                row.get("median30d"),
                row.get("avg"),
                row.get("low"),
            )
            if value is not None:
                values.append(value)
            try:
                counts += int(row.get("saleCount") or 0)
            except (TypeError, ValueError):
                pass

    return (statistics.median(values) if values else None), counts


def _poketrace_exact_rows(
    card: scout.PanelCard,
    identity_for_match: CardIdentity,
    rows: Sequence[Mapping[str, object]],
    language: str,
) -> list[Mapping[str, object]]:
    if language != "ja":
        return [
            row
            for row in rows
            if scout.candidate_identity(
                identity_for_match,
                name=row.get("name"),
                set_name=(
                    row.get("set", {}).get("name")
                    if isinstance(row.get("set"), Mapping)
                    else None
                ),
                number=row.get("cardNumber") or row.get("number"),
            )
            == "EXACT"
        ]

    number_matches = [
        row
        for row in rows
        if scout.number_ok(
            card.identity.card_number, row.get("cardNumber") or row.get("number")
        )
    ]
    if len(number_matches) == 1:
        return number_matches

    set_token = card.tcgdex_id.rsplit("-", 1)[0].casefold()
    narrowed = []
    for row in number_matches:
        set_row = row.get("set") if isinstance(row.get("set"), Mapping) else {}
        set_name = str(set_row.get("name") or "")
        slug = str(set_row.get("slug") or "")
        if set_token and (
            set_token in scout.norm(set_name).replace(" ", "")
            or set_token in scout.norm(slug).replace(" ", "")
        ):
            narrowed.append(row)
    return narrowed


def poketrace_corrected(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime]:
    """Use PokeTrace's game split and CardMarket FR language slices correctly."""
    client = scout.SafeClient("poketrace", call_cap=80, interval=0.20)
    anchor_client = scout.SafeClient("tcgdex_poketrace_anchor", call_cap=10, interval=0.03)
    anchor_cache: dict[str, CardIdentity | None] = {}
    out: list[scout.Observation] = []
    depth: list[tuple[int, str, str]] = []

    for index, card in enumerate(panel):
        language = scout.lang(card.identity.language)
        identity_for_match = card.identity
        if language == "fr":
            anchor = _english_anchor(card, anchor_client, anchor_cache)
            if anchor is None:
                out.append(
                    scout.Observation(
                        "poketrace", card.label, error="NO_ENGLISH_TCGDEX_ANCHOR"
                    )
                )
                continue
            identity_for_match = anchor

        if language == "ja":
            set_token = card.tcgdex_id.rsplit("-", 1)[0]
            search_term = f"{set_token} {card.identity.card_number}".strip()
            game = "pokemon-japanese"
        else:
            search_term = " ".join(
                filter(
                    None,
                    (
                        identity_for_match.card_name,
                        identity_for_match.card_number,
                    ),
                )
            )
            game = "pokemon"

        exact_rows: list[tuple[str, Mapping[str, object]]] = []
        for market in ("US", "EU"):
            response, payload = client.request(
                "GET",
                "https://api.poketrace.com/v1/cards",
                headers={"X-API-Key": key},
                params={
                    "search": search_term,
                    "market": market,
                    "game": game,
                    "limit": 20,
                    "product_type": "single",
                },
            )
            if response:
                _update_quota(client.runtime, response)
            if not response or response.status_code != 200 or not isinstance(payload, Mapping):
                continue
            rows = scout.maps(payload.get("data"))
            matches = _poketrace_exact_rows(
                card, identity_for_match, rows, language
            )
            for row in matches:
                exact_rows.append((market, row))

        obs = scout.Observation("poketrace", card.label)
        if not exact_rows:
            obs.identity = "UNRESOLVED"
            out.append(obs)
            continue

        obs.identity = "EXACT"
        obs.variant = scout.variant_status(
            card.identity, [row.get("variant") for _, row in exact_rows]
        )
        if language in {"en", "ja"}:
            obs.language = "EXACT"

        liquidity = 0
        fr_language_seen = False
        for market, row in exact_rows:
            prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
            if market == "US":
                tp = (
                    prices.get("tcgplayer")
                    if isinstance(prices.get("tcgplayer"), Mapping)
                    else {}
                )
                eb = (
                    prices.get("ebay")
                    if isinstance(prices.get("ebay"), Mapping)
                    else {}
                )
                raw = (
                    tp.get("NEAR_MINT")
                    if isinstance(tp.get("NEAR_MINT"), Mapping)
                    else {}
                )
                if not raw:
                    raw = (
                        eb.get("NEAR_MINT")
                        if isinstance(eb.get("NEAR_MINT"), Mapping)
                        else {}
                    )
                obs.raw_usd = (
                    scout.num(raw.get("avg"), raw.get("median7d"), raw.get("low"))
                    or obs.raw_usd
                )
                grade_keys = [
                    k
                    for k in eb
                    if any(
                        tag in str(k).upper()
                        for tag in ("PSA_", "BGS_", "CGC_", "SGC_")
                    )
                ]
                if grade_keys:
                    obs.graded_available = True
                    psa10 = (
                        eb.get("PSA_10")
                        if isinstance(eb.get("PSA_10"), Mapping)
                        else {}
                    )
                    obs.psa10_usd = scout.num(
                        psa10.get("median7d"), psa10.get("avg"), psa10.get("low")
                    )
                    if row.get("id"):
                        depth.append(
                            (
                                index,
                                str(row["id"]),
                                "PSA_10" if "PSA_10" in eb else grade_keys[0],
                            )
                        )
                for source in (tp, eb):
                    nm = (
                        source.get("NEAR_MINT")
                        if isinstance(source.get("NEAR_MINT"), Mapping)
                        else {}
                    )
                    try:
                        liquidity += int(nm.get("saleCount") or 0)
                    except (TypeError, ValueError):
                        pass
            else:
                cm = (
                    prices.get("cardmarket")
                    if isinstance(prices.get("cardmarket"), Mapping)
                    else {}
                )
                agg = (
                    cm.get("AGGREGATED")
                    if isinstance(cm.get("AGGREGATED"), Mapping)
                    else {}
                )
                unsold = (
                    prices.get("cardmarket_unsold")
                    if isinstance(prices.get("cardmarket_unsold"), Mapping)
                    else {}
                )
                nm = (
                    unsold.get("NEAR_MINT")
                    if isinstance(unsold.get("NEAR_MINT"), Mapping)
                    else {}
                )
                if language == "fr":
                    fr_price, fr_count = _fr_language_slice(nm, "FR")
                    if fr_price is not None:
                        obs.raw_eur = fr_price
                        fr_language_seen = True
                    liquidity += fr_count
                else:
                    obs.raw_eur = (
                        scout.num(
                            agg.get("avg"), agg.get("avg7d"), agg.get("avg30d")
                        )
                        or obs.raw_eur
                    )
                    try:
                        liquidity += int(nm.get("saleCount") or 0)
                    except (TypeError, ValueError):
                        pass

            obs.freshness = scout.freshest(
                obs.freshness, row.get("lastUpdated")
            )

        if language == "fr":
            obs.language = "EXACT" if fr_language_seen else "NOT_EXPOSED"
            if not fr_language_seen:
                obs.identity = "ANCHOR_ONLY"

        obs.liquidity = liquidity or None
        obs.history = "AVAILABLE_PRO"
        out.append(obs)

    seen_depth: set[int] = set()
    for index, card_id, tier in depth:
        if index in seen_depth:
            continue
        seen_depth.add(index)
        response, payload = client.request(
            "GET",
            f"https://api.poketrace.com/v1/cards/{quote(card_id, safe='')}/prices/{quote(tier, safe='')}/history",
            headers={"X-API-Key": key},
            params={"period": "30d", "limit": 30},
        )
        if response:
            _update_quota(client.runtime, response)
        if (
            response
            and response.status_code == 200
            and isinstance(payload, Mapping)
            and payload.get("data")
        ):
            out[index].history = "30D_RETURNED"

    return out, client.runtime


def _skip_cmapi_until_usage_confirmed(panel, _key):
    # RapidAPI Basic has paid overage. A local per-run cap cannot account for
    # requests made outside this workflow, so fail closed until current daily
    # usage is explicitly confirmed before a dedicated CMAPI run.
    return (
        [
            scout.Observation(
                "cmapi", card.label, error="SKIPPED_PAID_OVERAGE_SAFETY"
            )
            for card in panel
        ],
        scout.Runtime(blocked=True),
    )


def _language_summary(report: Mapping[str, object]) -> dict[str, object]:
    panel = report.get("panel") if isinstance(report.get("panel"), list) else []
    observations = (
        report.get("observations")
        if isinstance(report.get("observations"), Mapping)
        else {}
    )
    output: dict[str, object] = {}
    for provider in scout.PROVIDERS:
        rows = (
            observations.get(provider)
            if isinstance(observations.get(provider), list)
            else []
        )
        provider_out: dict[str, object] = {}
        for language in LANGUAGES:
            indices = [
                i
                for i, card in enumerate(panel)
                if isinstance(card, Mapping) and card.get("language") == language
            ]
            subset = [
                rows[i]
                for i in indices
                if i < len(rows) and isinstance(rows[i], Mapping)
            ]
            provider_out[language] = {
                "cards": len(indices),
                "tested": sum(
                    row.get("error") != "SKIPPED_PAID_OVERAGE_SAFETY"
                    for row in subset
                ),
                "identity_exact": sum(
                    row.get("identity") == "EXACT" for row in subset
                ),
                "identity_anchor": sum(
                    row.get("identity") == "ANCHOR_ONLY" for row in subset
                ),
                "variant_exact": sum(
                    row.get("variant") == "EXACT" for row in subset
                ),
                "language_exact": sum(
                    row.get("language") == "EXACT" for row in subset
                ),
                "raw_usd": sum(
                    row.get("raw_usd") is not None for row in subset
                ),
                "raw_eur": sum(
                    row.get("raw_eur") is not None for row in subset
                ),
                "graded": sum(
                    bool(row.get("graded_available")) for row in subset
                ),
                "history": sum(
                    row.get("history")
                    not in {"NONE", "PLAN_GATED", "ENDPOINT_NOT_AVAILABLE"}
                    for row in subset
                ),
            }
        output[provider] = provider_out
    return output


def _language_markdown(report: Mapping[str, object]) -> str:
    lines = [
        scout.markdown(report).rstrip(),
        "",
        "## By purchase-scope language",
        "",
    ]
    summary = (
        report.get("language_summary")
        if isinstance(report.get("language_summary"), Mapping)
        else {}
    )
    for language in LANGUAGES:
        lines += [
            f"### {language.upper()}",
            "",
            "| Provider | Exact ID | Anchor | RAW USD | RAW EUR | Graded | History |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for provider in scout.PROVIDERS:
            prow = (
                summary.get(provider)
                if isinstance(summary.get(provider), Mapping)
                else {}
            )
            row = (
                prow.get(language)
                if isinstance(prow.get(language), Mapping)
                else {}
            )
            lines.append(
                f"| {provider} | {row.get('identity_exact', 0)}/{row.get('tested', 0)} | "
                f"{row.get('identity_anchor', 0)} | {row.get('raw_usd', 0)} | "
                f"{row.get('raw_eur', 0)} | {row.get('graded', 0)} | "
                f"{row.get('history', 0)} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    scout.build_panel = build_language_panel
    scout.PANEL_SIZE = PANEL_SIZE
    os.environ["SOURCE_SCOUT_PANEL_SIZE"] = str(PANEL_SIZE)

    # The user activated PokemonPriceTracker API ($9.99/mo): benchmark the
    # paid features now, including 180-day history, eBay graded and Cardmarket.
    scout.PLAN["pokemonpricetracker"] = (
        "API $9.99/mo; 20k credits/day; 180d history; Japanese; "
        "eBay graded; Cardmarket EUR beta"
    )
    scout.pokemonpricetracker = pokemonpricetracker_api

    # Re-test PokeTrace with its documented game split and EU language slices.
    scout.poketrace = poketrace_corrected

    # CMAPI remains fail-closed for this run.
    scout.cmapi = _skip_cmapi_until_usage_confirmed
    os.environ["SOURCE_SCOUT_ENABLE_CMAPI"] = "false"

    try:
        report = scout.run()
    except Exception as exc:
        print(
            f"SOURCE_SCOUT_LANGUAGE_FAILED: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    report["language_summary"] = _language_summary(report)
    with open(
        os.getenv("SOURCE_SCOUT_JSON", "source_scout_report.json"),
        "w",
        encoding="utf-8",
    ) as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    rendered = _language_markdown(report)
    with open(
        os.getenv("SOURCE_SCOUT_MARKDOWN", "source_scout_report.md"),
        "w",
        encoding="utf-8",
    ) as handle:
        handle.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
