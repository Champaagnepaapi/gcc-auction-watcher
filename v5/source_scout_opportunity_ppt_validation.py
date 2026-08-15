from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping

from . import source_scout_benchmark as scout
from . import source_scout_opportunity_benchmark as opportunity
from . import source_scout_paid_entrypoint as paid
from . import source_scout_paid_v2_entrypoint as v2
from . import source_scout_paid_v3_entrypoint as v3


PPT_CALL_CAP = 60
PPT_INTERVAL_SECONDS = 2.20
REPORT_JSON = Path("source_scout_opportunity_ppt_report.json")
REPORT_MD = Path("source_scout_opportunity_ppt_report.md")


def _copy_anchor(source: scout.Observation, card: scout.PanelCard) -> scout.Observation:
    out = scout.Observation("pokemonpricetracker", card.label)
    out.identity = "ANCHOR_ONLY"
    out.variant = source.variant
    out.language = "NOT_EXPOSED"
    out.raw_usd = source.raw_usd
    out.raw_eur = source.raw_eur
    out.psa10_usd = source.psa10_usd
    out.psa10_eur = source.psa10_eur
    out.graded_available = source.graded_available
    out.history = source.history
    out.freshness = source.freshness
    out.liquidity = source.liquidity
    out.error = source.error
    return out


def _shallow_observation(card: scout.PanelCard, row: Mapping[str, object]) -> scout.Observation:
    obs = scout.Observation("pokemonpricetracker", card.label)
    obs.identity = "EXACT"
    prices = row.get("prices") if isinstance(row.get("prices"), Mapping) else {}
    obs.raw_usd = scout.num(prices.get("market"), prices.get("low"))
    obs.freshness = scout.freshest(prices.get("lastUpdated"), row.get("updatedAt"))
    variants = row.get("variants") if isinstance(row.get("variants"), Mapping) else {}
    obs.variant = scout.variant_status(
        card.identity,
        list(variants.keys()) + [prices.get("primaryPrinting"), row.get("printing")],
    )
    obs.language = "EXACT"
    return obs


def run_ppt(panel: list[scout.PanelCard], key: str) -> tuple[list[scout.Observation], scout.Runtime]:
    client = scout.SafeClient(
        "pokemonpricetracker_opportunity_validation",
        call_cap=PPT_CALL_CAP,
        interval=PPT_INTERVAL_SECONDS,
        response_cap=2_000_000,
        total_cap=100_000_000,
    )
    grouped = opportunity._group_by_print(panel)
    index_by_key = {
        (card.tcgdex_id, scout.lang(card.identity.language)): index
        for index, card in enumerate(panel)
    }
    observations = [scout.Observation("pokemonpricetracker", card.label) for card in panel]
    v3.PPT_EVIDENCE.clear()
    v3.PPT_PROBES.clear()

    for tcgdex_id, localized in grouped.items():
        if client.runtime.blocked:
            break
        en = localized.get("en")
        fr = localized.get("fr")
        if en is None:
            continue
        code = v2._set_code(en)
        search_text = " ".join(filter(None, (en.identity.card_name, en.identity.card_number)))
        exact: list[Mapping[str, object]] = []
        rows: list[Mapping[str, object]] = []
        for params in (
            {"search": search_text, "setName": en.identity.set or "", "limit": 10},
            {"search": search_text, "limit": 10},
        ):
            response, payload = v3._request(
                client,
                key,
                "https://www.pokemonpricetracker.com/api/v2/cards",
                params,
            )
            rows = paid._rows(payload)
            exact = v2._match(en.identity, rows, set_code=code, ignore_name=False)
            if exact:
                break

        en_index = index_by_key[(tcgdex_id, "en")]
        fr_index = index_by_key.get((tcgdex_id, "fr"))
        if len(exact) != 1:
            observations[en_index].identity = "AMBIGUOUS" if len(exact) > 1 else (
                "MISMATCH_OR_INSUFFICIENT" if rows else "UNRESOLVED"
            )
            if fr_index is not None:
                observations[fr_index].identity = "UNRESOLVED"
            continue

        row = exact[0]
        en_obs = _shallow_observation(en, row)
        tcg_id = str(row.get("tcgPlayerId") or row.get("tcgplayerId") or "").strip()
        if tcg_id:
            for kind, params in (
                (
                    "history",
                    {
                        "tcgPlayerId": tcg_id,
                        "includeHistory": "true",
                        "days": 180,
                        "maxDataPoints": 180,
                    },
                ),
                (
                    "ebay",
                    {"tcgPlayerId": tcg_id, "includeEbay": "true", "days": 180},
                ),
                (
                    "cardmarket",
                    {"tcgPlayerId": tcg_id, "includeCardmarket": "true"},
                ),
            ):
                response, payload = v3._request(
                    client,
                    key,
                    "https://www.pokemonpricetracker.com/api/v2/cards",
                    params,
                )
                deep_rows = paid._rows(payload)
                if not response or response.status_code != 200 or not deep_rows:
                    continue
                v3._apply_deep_row(en_obs, deep_rows[0])
                v3._append_evidence(
                    index=en_index,
                    card=en,
                    identity_status="EXACT",
                    tcg_id=tcg_id,
                    kind=kind,
                    payload=payload,
                )
        observations[en_index] = en_obs
        if fr is not None and fr_index is not None:
            observations[fr_index] = _copy_anchor(en_obs, fr)

    v3._write_evidence()
    return observations, client.runtime


def _summary(provider: str, rows: list[scout.Observation], runtime: scout.Runtime) -> dict[str, object]:
    result = scout.summary(provider, rows, runtime)
    result["identity_anchor"] = sum(row.identity == "ANCHOR_ONLY" for row in rows)
    return result


def _markdown(report: Mapping[str, object]) -> str:
    providers = report.get("providers") if isinstance(report.get("providers"), Mapping) else {}
    lines = [
        "# Opportunity PPT validation",
        "",
        f"- Cards: `{report.get('panel_size')}` (12 unique prints × EN/FR)",
        f"- PPT calls: `{providers.get('pokemonpricetracker', {}).get('calls', 0)}` / `{PPT_CALL_CAP}`",
        f"- PPT quota remaining: `{providers.get('pokemonpricetracker', {}).get('quota_remaining')}`",
        "",
        "| Provider | Exact | Anchor | RAW USD | RAW EUR | PSA10 USD | Graded | History | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in ("tcgdex", "pokemonpricetracker"):
        row = providers.get(provider, {}) if isinstance(providers.get(provider), Mapping) else {}
        lines.append(
            f"| {provider} | {row.get('identity_exact', 0)} | {row.get('identity_anchor', 0)} | "
            f"{row.get('raw_usd', 0)} | {row.get('raw_eur', 0)} | {row.get('psa10_usd', 0)} | "
            f"{row.get('graded', 0)} | {row.get('history', 0)} | {row.get('calls', 0)} |"
        )
    lines += [
        "",
        "CMAPI is intentionally not called by this validation.",
        "No purchase, bid, checkout, payment or paid grading action is present.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("POKEMONPRICETRACKER_API_KEY missing")
    panel, panel_diag = opportunity.build_opportunity_panel()
    tcgdex_rows, tcgdex_runtime = scout.tcgdex(panel)
    ppt_rows, ppt_runtime = run_ppt(panel, key)
    scout.PLAN["pokemonpricetracker"] = "API $9.99/mo; 20k credits/day; 180d history; eBay graded; Cardmarket EUR beta"
    report = {
        "generated_at": v3._utc_now(),
        "mode": "OPPORTUNITY_PPT_VALIDATION_NO_CMAPI",
        "panel_size": len(panel),
        "panel_diagnostics": panel_diag,
        "safety": {
            "purchase": 0,
            "bid": 0,
            "checkout": 0,
            "payment": 0,
            "paid_grading": 0,
            "cmapi_calls": 0,
        },
        "panel": [
            {
                "card": card.label,
                "tcgdex_id": card.tcgdex_id,
                "language": scout.lang(card.identity.language),
            }
            for card in panel
        ],
        "providers": {
            "tcgdex": _summary("tcgdex", tcgdex_rows, tcgdex_runtime),
            "pokemonpricetracker": _summary("pokemonpricetracker", ppt_rows, ppt_runtime),
        },
        "observations": {
            "tcgdex": [row.as_dict() for row in tcgdex_rows],
            "pokemonpricetracker": [row.as_dict() for row in ppt_rows],
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = _markdown(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
