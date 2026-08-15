from __future__ import annotations

import json
import os
import statistics
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import quote

from . import source_scout_benchmark as scout
from . import source_scout_cmapi_v2_entrypoint as cmapi_v2
from . import source_scout_cmapi_v3_entrypoint as cmapi
from . import source_scout_language_entrypoint as language
from . import source_scout_paid_v2_entrypoint as ppt
from .models import CardIdentity


# High-value/high-liquidity proxy pool. The run does not trust these labels for
# identity: every EN and FR localized card is re-read from TCGdex and only pairs
# resolving in both languages are retained. First 12 valid pairs => 24 cards.
CANDIDATE_TCGDEX_IDS: tuple[str, ...] = (
    "swsh7-215",   # Umbreon VMAX
    "swsh8-271",   # Gengar VMAX
    "swsh11-186",  # Giratina V
    "swsh12-186",  # Lugia V
    "swsh9-154",   # Charizard V
    "swsh7-218",   # Rayquaza VMAX
    "swsh7-205",   # Leafeon VMAX
    "swsh7-212",   # Sylveon VMAX
    "swsh8-270",   # Espeon VMAX
    "swsh7-192",   # Dragonite V
    "swsh6-201",   # Blaziken VMAX
    "swsh5-155",   # Tyranitar V
    "swsh10-172",  # Machamp V
    "swsh11-180",  # Aerodactyl V
    "swsh4-188",   # Pikachu VMAX
)
UNIQUE_PRINT_TARGET = 12
LANGUAGES = ("en", "fr")

# RapidAPI Basic: 100/day then paid overage. The first live response MUST expose
# remaining quota. We stop at 40 remaining and can never make >50 calls/run.
CMAPI_MAX_CALLS = 50
CMAPI_STOP_REMAINING = 40
CMAPI_INTERVAL_SECONDS = 2.2
CMAPI_RESPONSE_CAP = 2_000_000
CMAPI_TOTAL_CAP = 24_000_000

REPORT_JSON = Path("source_scout_opportunity_report.json")
REPORT_MD = Path("source_scout_opportunity_report.md")
CMAPI_EVIDENCE = Path("cmapi_opportunity_evidence.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _detail_to_card(payload: Mapping[str, object], tcgdex_id: str, lang_code: str) -> scout.PanelCard | None:
    set_row = payload.get("set") if isinstance(payload.get("set"), Mapping) else {}
    name = str(payload.get("name") or "").strip()
    set_name = str(set_row.get("name") or "").strip()
    number = str(payload.get("localId") or "").strip()
    if not (name and set_name and number):
        return None
    return scout.PanelCard(
        identity=CardIdentity(
            game="Pokémon TCG",
            card_name=name,
            set=set_name,
            card_number=number,
            language=lang_code,
            finish=language._finish(payload.get("variants")),
        ),
        tcgdex_id=tcgdex_id,
        tcgdex_language=lang_code,
        marketplace="CURATED_LIQUIDITY_PROXY_TCGDEX",
    )


def build_opportunity_panel() -> tuple[list[scout.PanelCard], dict[str, object]]:
    client = scout.SafeClient(
        "tcgdex_opportunity_seed",
        call_cap=60,
        interval=0.04,
        response_cap=2_000_000,
        total_cap=40_000_000,
    )
    panel: list[scout.PanelCard] = []
    accepted: list[str] = []
    rejected: list[dict[str, object]] = []

    for tcgdex_id in CANDIDATE_TCGDEX_IDS:
        if len(accepted) >= UNIQUE_PRINT_TARGET or client.runtime.blocked:
            break
        pair: list[scout.PanelCard] = []
        errors: list[str] = []
        for lang_code in LANGUAGES:
            response, payload = client.request(
                "GET",
                f"https://api.tcgdex.net/v2/{lang_code}/cards/{quote(tcgdex_id, safe='')}",
            )
            if not response or response.status_code != 200 or not isinstance(payload, Mapping):
                errors.append(f"{lang_code}:HTTP_{getattr(response, 'status_code', 'REQUEST')}")
                continue
            card = _detail_to_card(payload, tcgdex_id, lang_code)
            if card is None:
                errors.append(f"{lang_code}:INCOMPLETE_IDENTITY")
                continue
            pair.append(card)
        if len(pair) == len(LANGUAGES):
            panel.extend(pair)
            accepted.append(tcgdex_id)
        else:
            rejected.append({"tcgdex_id": tcgdex_id, "errors": errors})

    diagnostics = {
        "mode": "CURATED_HIGH_VALUE_LIQUIDITY_PROXY_EN_FR",
        "unique_print_target": UNIQUE_PRINT_TARGET,
        "accepted_prints": accepted,
        "rejected_candidates": rejected,
        "cards": len(panel),
        "tcgdex_seed_calls": client.runtime.calls,
        "tcgdex_seed_bytes": client.runtime.bytes_read,
    }
    if len(accepted) < 10:
        raise RuntimeError(f"Opportunity panel too small: {len(accepted)} valid EN/FR pairs")
    return panel, diagnostics


def _group_by_print(panel: Sequence[scout.PanelCard]) -> dict[str, dict[str, scout.PanelCard]]:
    output: dict[str, dict[str, scout.PanelCard]] = {}
    for card in panel:
        output.setdefault(card.tcgdex_id, {})[scout.lang(card.identity.language)] = card
    return output


def _current_cmapi_observation(card: scout.PanelCard, row: Mapping[str, object], *, fr_anchor: bool) -> scout.Observation:
    obs = scout.Observation("cmapi", card.label)
    obs.identity = "ANCHOR_ONLY" if fr_anchor else "EXACT"
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    cardmarket = prices.get("cardmarket") if isinstance(prices.get("cardmarket"), Mapping) else {}
    ebay = prices.get("ebay") if isinstance(prices.get("ebay"), Mapping) else {}
    tcgplayer = prices.get("tcg_player") if isinstance(prices.get("tcg_player"), Mapping) else {}

    if fr_anchor:
        obs.raw_eur = scout.num(
            cardmarket.get("lowest_near_mint_FR"),
            cardmarket.get("lowest_near_mint_FR_EU_only"),
        )
        obs.language = "EXACT" if obs.raw_eur is not None else "NOT_EXPOSED"
    else:
        obs.raw_eur = scout.num(
            cardmarket.get("lowest_near_mint"),
            cardmarket.get("7d_average"),
            cardmarket.get("30d_average"),
        )
        obs.language = "NOT_EXPOSED"

    if str(tcgplayer.get("currency") or "").upper() == "USD":
        obs.raw_usd = scout.num(tcgplayer.get("market_price"), tcgplayer.get("mid_price"))

    graded = ebay.get("graded") if isinstance(ebay.get("graded"), Mapping) else {}
    obs.graded_available = bool(graded)
    psa = graded.get("psa") if isinstance(graded.get("psa"), Mapping) else {}
    psa10 = psa.get("10") if isinstance(psa.get("10"), Mapping) else {}
    if str(ebay.get("currency") or "USD").upper() == "USD":
        obs.psa10_usd = scout.num(psa10.get("median_price"))
    try:
        obs.liquidity = sum(
            int(grade_row.get("sample_size") or 0)
            for grader_row in graded.values()
            if isinstance(grader_row, Mapping)
            for grade_row in grader_row.values()
            if isinstance(grade_row, Mapping)
        ) or None
    except (TypeError, ValueError):
        obs.liquidity = None
    return obs


def _cmapi_request(
    client: scout.SafeClient,
    key: str,
    host: str,
    path: str,
    params: Mapping[str, object],
) -> tuple[object | None, object | None]:
    before = client.runtime.calls
    response, payload = cmapi._request(client, key, host, path, params)
    # Paid-overage safety depends on a provider-reported daily quota. If the
    # first actual request does not expose it, stop immediately instead of
    # guessing remaining usage.
    if client.runtime.calls > before and client.runtime.calls == 1 and client.runtime.quota_remaining is None:
        client.runtime.blocked = True
        client.runtime.errors.append("CMAPI_QUOTA_HEADER_REQUIRED")
    return response, payload


def cmapi_opportunity(
    panel: Sequence[scout.PanelCard], key: str
) -> tuple[list[scout.Observation], scout.Runtime, dict[str, object]]:
    cmapi.MAX_CMAPI_CALLS = CMAPI_MAX_CALLS
    cmapi.STOP_IF_REMAINING_AT_OR_BELOW = CMAPI_STOP_REMAINING
    cmapi.CALL_TRACE.clear()
    host = os.getenv("CMAPI_RAPIDAPI_HOST", cmapi.CMAPI_HOST).strip() or cmapi.CMAPI_HOST
    client = scout.SafeClient(
        "cmapi_opportunity",
        call_cap=CMAPI_MAX_CALLS,
        interval=CMAPI_INTERVAL_SECONDS,
        response_cap=CMAPI_RESPONSE_CAP,
        total_cap=CMAPI_TOTAL_CAP,
    )
    grouped = _group_by_print(panel)
    observations = [scout.Observation("cmapi", card.label) for card in panel]
    index_by_key = {(card.tcgdex_id, scout.lang(card.identity.language)): i for i, card in enumerate(panel)}
    evidence_cards: list[dict[str, object]] = []
    sold_cards = 0
    sold_offers = 0

    for tcgdex_id, localized in grouped.items():
        if client.runtime.blocked:
            break
        en = localized.get("en")
        fr = localized.get("fr")
        if en is None:
            continue
        query = " ".join(filter(None, (en.identity.card_name, en.identity.card_number)))
        retrieved_at = _now()
        response, payload = _cmapi_request(
            client,
            key,
            host,
            cmapi.SEARCH_PATH,
            {"search": query, "sort": "relevance"},
        )
        rows = cmapi_v2._rows(payload)
        exact = [
            row
            for row in rows
            if scout.candidate_identity(
                en.identity,
                name=row.get("name"),
                set_name=cmapi_v2._set_name(row),
                number=cmapi_v2._number(row),
            )
            == "EXACT"
        ]
        evidence: dict[str, object] = {
            "tcgdex_id": tcgdex_id,
            "retrieved_at": retrieved_at,
            "canonical_en": {
                "name": en.identity.card_name,
                "set": en.identity.set,
                "number": en.identity.card_number,
                "language": "en",
            },
            "canonical_fr": {
                "name": fr.identity.card_name if fr else None,
                "set": fr.identity.set if fr else None,
                "number": fr.identity.card_number if fr else None,
                "language": "fr",
            },
            "search_http": getattr(response, "status_code", None),
            "search_payload": payload if getattr(response, "status_code", None) == 200 else None,
            "identity_status": "UNRESOLVED",
            "matched_card": None,
            "history": {},
            "ebay_psa10_sold_offers": None,
        }
        if len(exact) != 1:
            if len(exact) > 1:
                evidence["identity_status"] = "AMBIGUOUS"
            evidence_cards.append(evidence)
            continue

        row = exact[0]
        evidence["identity_status"] = "EXACT_EN_ANCHOR"
        evidence["matched_card"] = {
            "id": row.get("id"),
            "name": row.get("name"),
            "set_name": cmapi_v2._set_name(row),
            "card_number": cmapi_v2._number(row),
            "tcgid": cmapi._tcgid(row),
            "cardmarket_id": row.get("cardmarket_id") or row.get("cardmarketId"),
            "tcgplayer_id": row.get("tcgplayer_id") or row.get("tcgplayerId"),
        }
        en_index = index_by_key.get((tcgdex_id, "en"))
        fr_index = index_by_key.get((tcgdex_id, "fr"))
        if en_index is not None:
            observations[en_index] = _current_cmapi_observation(en, row, fr_anchor=False)
        if fr is not None and fr_index is not None:
            observations[fr_index] = _current_cmapi_observation(fr, row, fr_anchor=True)

        lookup = cmapi._lookup_params(row, en)
        today = date.today()
        for lang_code in LANGUAGES:
            if client.runtime.blocked:
                break
            history_response, history_payload = _cmapi_request(
                client,
                key,
                host,
                cmapi.HISTORY_PATH,
                {
                    **lookup,
                    "date_from": str(today - timedelta(days=60)),
                    "date_to": str(today),
                    "sort": "desc",
                    "lang": lang_code,
                    "page": 1,
                },
            )
            summary = {
                "http": getattr(history_response, "status_code", None),
                "error": cmapi._safe_error(history_payload),
                **cmapi._history_summary(history_payload),
                "payload": history_payload if getattr(history_response, "status_code", None) == 200 else None,
            }
            evidence_history = evidence.get("history")
            if isinstance(evidence_history, dict):
                evidence_history[lang_code] = summary
            idx = index_by_key.get((tcgdex_id, lang_code))
            if idx is not None and summary.get("point_count"):
                observations[idx].history = "RECENT_RETURNED"

        if not client.runtime.blocked:
            offers_response, offers_payload = _cmapi_request(
                client,
                key,
                host,
                cmapi.EBAY_OFFERS_PATH,
                {**lookup, "company": "PSA", "grade": "10", "per_page": 20, "page": 1},
            )
            offers_summary = {
                "http": getattr(offers_response, "status_code", None),
                "error": cmapi._safe_error(offers_payload),
                **cmapi._offers_summary(offers_payload),
                "payload": offers_payload if getattr(offers_response, "status_code", None) == 200 else None,
            }
            evidence["ebay_psa10_sold_offers"] = offers_summary
            count = int(offers_summary.get("offer_count") or 0)
            if count:
                sold_cards += 1
                sold_offers += count
        evidence_cards.append(evidence)

    evidence_doc = {
        "schema_version": 1,
        "provider": "cmapi",
        "generated_at": _now(),
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "max_calls": CMAPI_MAX_CALLS,
            "stop_remaining": CMAPI_STOP_REMAINING,
            "actual_calls": client.runtime.calls,
            "quota_remaining": client.runtime.quota_remaining,
            "blocked": client.runtime.blocked,
            "errors": client.runtime.errors,
        },
        "sold_cards": sold_cards,
        "sold_offers": sold_offers,
        "cards": evidence_cards,
        "call_trace": cmapi.CALL_TRACE,
    }
    CMAPI_EVIDENCE.write_text(
        json.dumps(evidence_doc, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    return observations, client.runtime, evidence_doc


class _ConservativeSafeClient(scout.SafeClient):
    def __init__(self, provider: str, *, call_cap: int, interval: float = 0.0, **kwargs: object) -> None:
        if provider == "pokemonpricetracker":
            interval = max(interval, 2.2)
        super().__init__(provider, call_cap=call_cap, interval=interval, **kwargs)


def _run_ppt(panel: Sequence[scout.PanelCard], key: str):
    original = scout.SafeClient
    ppt.PPT_EVIDENCE.clear()
    ppt.PPT_JP_PROBES.clear()
    scout.SafeClient = _ConservativeSafeClient
    try:
        rows, runtime = ppt.pokemonpricetracker_api(panel, key)
    finally:
        scout.SafeClient = original
    ppt._write_evidence()
    return rows, runtime


def _by_language(panel: Sequence[scout.PanelCard], rows: Sequence[scout.Observation]) -> dict[str, object]:
    output: dict[str, object] = {}
    for lang_code in LANGUAGES:
        subset = [row for card, row in zip(panel, rows) if scout.lang(card.identity.language) == lang_code]
        output[lang_code] = {
            "cards": len(subset),
            "exact": sum(row.identity == "EXACT" for row in subset),
            "anchor": sum(row.identity == "ANCHOR_ONLY" for row in subset),
            "raw_usd": sum(row.raw_usd is not None for row in subset),
            "raw_eur": sum(row.raw_eur is not None for row in subset),
            "psa10_usd": sum(row.psa10_usd is not None for row in subset),
            "graded": sum(row.graded_available for row in subset),
            "history": sum(row.history not in {"NONE", "PLAN_GATED", "ENDPOINT_NOT_AVAILABLE"} for row in subset),
            "liquidity": sum(row.liquidity is not None for row in subset),
        }
    return output


def _agreement(panel: Sequence[scout.PanelCard], rows_by_provider: Mapping[str, Sequence[scout.Observation]]) -> dict[str, object]:
    deviations: dict[str, list[float]] = {provider: [] for provider in rows_by_provider}
    comparable = 0
    for index in range(len(panel)):
        values: list[tuple[str, float]] = []
        for provider, rows in rows_by_provider.items():
            if index >= len(rows):
                continue
            value = rows[index].raw_eur
            if isinstance(value, (int, float)) and value > 0:
                values.append((provider, float(value)))
        if len(values) < 2:
            continue
        comparable += 1
        median = statistics.median(value for _, value in values)
        for provider, value in values:
            deviations[provider].append(abs(value - median) / median * 100)
    return {
        "eur_comparable_cards": comparable,
        "median_absolute_pct_deviation": {
            provider: round(statistics.median(values), 2) if values else None
            for provider, values in deviations.items()
        },
    }


def _render(report: Mapping[str, object]) -> str:
    providers = report.get("providers") if isinstance(report.get("providers"), Mapping) else {}
    by_language = report.get("by_language") if isinstance(report.get("by_language"), Mapping) else {}
    cmapi_summary = report.get("cmapi_evidence_summary") if isinstance(report.get("cmapi_evidence_summary"), Mapping) else {}
    lines = [
        "# Opportunity-panel Source Scout",
        "",
        f"- Cards: `{report.get('panel_size')}` ({report.get('unique_prints')} unique prints × EN/FR)",
        f"- CMAPI calls: `{cmapi_summary.get('calls')}` / `{CMAPI_MAX_CALLS}`",
        f"- CMAPI quota remaining: `{cmapi_summary.get('quota_remaining')}`",
        f"- CMAPI cards with PSA10 individual SOLD: `{cmapi_summary.get('sold_cards')}`",
        f"- CMAPI individual SOLD rows returned: `{cmapi_summary.get('sold_offers')}`",
        "",
        "| Provider | Exact | Anchor | RAW EUR | PSA10 USD | Graded | History | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in ("tcgdex", "poketrace", "pokemonpricetracker", "cmapi"):
        row = providers.get(provider) if isinstance(providers.get(provider), Mapping) else {}
        lines.append(
            f"| {provider} | {row.get('identity_exact', 0)} | {row.get('identity_anchor', 0)} | "
            f"{row.get('raw_eur', 0)} | {row.get('psa10_usd', 0)} | {row.get('graded', 0)} | "
            f"{row.get('history', 0)} | {row.get('calls', 0)} |"
        )
    for lang_code in LANGUAGES:
        lines += ["", f"## {lang_code.upper()}", "", "| Provider | Exact | Anchor | RAW EUR | Graded | History |", "|---|---:|---:|---:|---:|---:|"]
        for provider in ("tcgdex", "poketrace", "pokemonpricetracker", "cmapi"):
            provider_lang = by_language.get(provider) if isinstance(by_language.get(provider), Mapping) else {}
            row = provider_lang.get(lang_code) if isinstance(provider_lang.get(lang_code), Mapping) else {}
            lines.append(
                f"| {provider} | {row.get('exact', 0)} | {row.get('anchor', 0)} | {row.get('raw_eur', 0)} | "
                f"{row.get('graded', 0)} | {row.get('history', 0)} |"
            )
    lines += ["", "No purchase, bid, checkout, payment or paid grading action is present in this benchmark."]
    return "\n".join(lines) + "\n"


def main() -> int:
    poketrace_key = os.getenv("POKETRACE_API_KEY", "").strip()
    ppt_key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    cmapi_key = os.getenv("CMAPI_RAPIDAPI_KEY", "").strip()
    missing = [name for name, value in (
        ("POKETRACE_API_KEY", poketrace_key),
        ("POKEMONPRICETRACKER_API_KEY", ppt_key),
        ("CMAPI_RAPIDAPI_KEY", cmapi_key),
    ) if not value]
    if missing:
        print("OPPORTUNITY_BENCHMARK_FAILED: missing " + ", ".join(missing))
        return 1

    panel, diagnostics = build_opportunity_panel()
    tcgdex_rows, tcgdex_runtime = scout.tcgdex(panel)
    poketrace_rows, poketrace_runtime = language.poketrace_corrected(panel, poketrace_key)
    ppt_rows, ppt_runtime = _run_ppt(panel, ppt_key)
    cmapi_rows, cmapi_runtime, cmapi_evidence = cmapi_opportunity(panel, cmapi_key)

    rows_by_provider = {
        "tcgdex": tcgdex_rows,
        "poketrace": poketrace_rows,
        "pokemonpricetracker": ppt_rows,
        "cmapi": cmapi_rows,
    }
    runtimes = {
        "tcgdex": tcgdex_runtime,
        "poketrace": poketrace_runtime,
        "pokemonpricetracker": ppt_runtime,
        "cmapi": cmapi_runtime,
    }
    providers = {
        provider: scout.summary(provider, rows_by_provider[provider], runtimes[provider])
        for provider in rows_by_provider
    }
    by_language = {
        provider: _by_language(panel, rows)
        for provider, rows in rows_by_provider.items()
    }
    report = {
        "generated_at": _now(),
        "mode": "READ_ONLY_HIGH_VALUE_LIQUIDITY_PROXY_EN_FR",
        "panel_size": len(panel),
        "unique_prints": len({card.tcgdex_id for card in panel}),
        "panel_fingerprint": scout.fingerprint(panel),
        "panel_diagnostics": diagnostics,
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "paid_grading": 0,
            "cmapi_max_calls": CMAPI_MAX_CALLS,
            "cmapi_stop_remaining": CMAPI_STOP_REMAINING,
        },
        "panel": [
            {
                "card": card.label,
                "tcgdex_id": card.tcgdex_id,
                "language": scout.lang(card.identity.language),
                "finish": card.identity.finish,
            }
            for card in panel
        ],
        "providers": providers,
        "by_language": by_language,
        "eur_agreement": _agreement(panel, rows_by_provider),
        "cmapi_evidence_summary": {
            "calls": cmapi_runtime.calls,
            "quota_remaining": cmapi_runtime.quota_remaining,
            "blocked": cmapi_runtime.blocked,
            "errors": cmapi_runtime.errors,
            "sold_cards": cmapi_evidence.get("sold_cards"),
            "sold_offers": cmapi_evidence.get("sold_offers"),
        },
        "observations": {
            provider: [row.__dict__ for row in rows]
            for provider, rows in rows_by_provider.items()
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    rendered = _render(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
