from __future__ import annotations

import json
import os
from dataclasses import asdict
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
    out = [scout.Observation("pokemonpricetracker", card.label) for card in panel]
    grouped = opportunity._group_by_print(panel)
    index_by_key = {(card.tcgdex_id, scout.lang(card.identity.language)): i for i, card in enumerate(panel)}
    depth: list[tuple[int, str]] = []

    for tcgdex_id, localized in grouped.items():
        if client.runtime.blocked:
            break
        en = localized.get("en")
        fr = localized.get("fr")
        if en is None:
            continue
        code = v2._set_code(en)
        attempts = [
            {
                "search": " ".join(filter(None, (en.identity.card_name, en.identity.card_number))),
                "setName": en.identity.set or "",
                "limit": 10,
            },
            {
                "search": " ".join(filter(None, (en.identity.card_name, en.identity.card_number))),
                "limit": 10,
            },
        ]
        rows: list[Mapping[str, object]] = []
        exact: list[Mapping[str, object]] = []
        for params in attempts:
            response, payload = client.request(
                "GET",
                "https://www.pokemonpricetracker.com/api/v2/cards",
                headers={"Authorization": f"Bearer {key}"},
                params=params,
            )
            if response:
                v3._update_quota(client.runtime, response)
            if not response or response.status_code != 200:
                continue
            rows = paid._rows(payload)
            exact = v2._match(en.identity, rows, set_code=code)
            if exact:
                break
        en_index = index_by_key.get((tcgdex_id, "en"))
        fr_index = index_by_key.get((tcgdex_id, "fr"))
        if len(exact) == 1:
            shallow = _shallow_observation(en, exact[0])
            if en_index is not None:
                out[en_index] = shallow
            if fr is not None and fr_index is not None:
                out[fr_index] = _copy_anchor(shallow, fr)
            tcg_id = exact[0].get("tcgPlayerId") or exact[0].get("tcgplayerId")
            if tcg_id and en_index is not None:
                depth.append((en_index, str(tcg_id)))
        elif len(exact) > 1:
            if en_index is not None:
                out[en_index].identity = "AMBIGUOUS"
            if fr_index is not None:
                out[fr_index].identity = "AMBIGUOUS"
        elif rows:
            if en_index is not None:
                out[en_index].identity = "MISMATCH_OR_INSUFFICIENT"
            if fr_index is not None:
                out[fr_index].identity = "MISMATCH_OR_INSUFFICIENT"
        else:
            if en_index is not None:
                out[en_index].identity = "UNRESOLVED"
            if fr_index is not None:
                out[fr_index].identity = "UNRESOLVED"

    v2.PPT_EVIDENCE.clear()
    v2.PPT_JP_PROBES.clear()
    for en_index, tcg_id in depth:
        if client.runtime.blocked:
            break
        card = panel[en_index]
        retrieved_at = v3._utc_now()
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
            v3._update_quota(client.runtime, response)
        if not response or response.status_code != 200:
            continue
        rows = paid._rows(payload)
        if not rows:
            continue
        row = rows[0]
        target = out[en_index]
        target.history = "180D_RETURNED" if row.get("priceHistory") else "NONE"
        target.graded_available, target.psa10_usd = paid._graded_from_ppt(row)
        target.raw_eur = paid._cardmarket_value(row)
        ebay = row.get("ebay") if isinstance(row.get("ebay"), Mapping) else {}
        try:
            target.liquidity = int(ebay["totalSales"]) if ebay.get("totalSales") is not None else None
        except (TypeError, ValueError):
            pass
        fr_index = index_by_key.get((card.tcgdex_id, "fr"))
        if fr_index is not None:
            out[fr_index] = _copy_anchor(target, panel[fr_index])
        v2.PPT_EVIDENCE.append(
            {
                "provider": "pokemonpricetracker",
                "retrieved_at": retrieved_at,
                "panel_index": en_index,
                "card_label": card.label,
                "tcgdex_id": card.tcgdex_id,
                "tcgdex_language": card.tcgdex_language,
                "identity_status": target.identity,
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
    v2._write_evidence()
    return out, client.runtime


def _summary(provider: str, rows: list[scout.Observation], runtime: scout.Runtime) -> dict[str, object]:
    summary = scout.summary(provider, rows, runtime)
    summary["identity_anchor"] = sum(row.identity == "ANCHOR_ONLY" for row in rows)
    return summary


def _markdown(report: Mapping[str, object]) -> str:
    providers = report.get("providers") if isinstance(report.get("providers"), Mapping) else {}
    lines = [
        "# PPT opportunity-panel validation",
        "",
        f"- Cards: `{report.get('panel_size')}`",
        "- CMAPI calls: `0` (secret absent from workflow)",
        "",
        "| Provider | Exact | Anchor | RAW EUR | PSA10 USD | Graded | History | Calls |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for provider in ("tcgdex", "pokemonpricetracker"):
        row = providers.get(provider) if isinstance(providers.get(provider), Mapping) else {}
        lines.append(
            f"| {provider} | {row.get('identity_exact', 0)} | {row.get('identity_anchor', 0)} | "
            f"{row.get('raw_eur', 0)} | {row.get('psa10_usd', 0)} | {row.get('graded_available', 0)} | "
            f"{row.get('history', 0)} | {row.get('calls', 0)} |"
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
            "tcgdex": [asdict(row) for row in tcgdex_rows],
            "pokemonpricetracker": [asdict(row) for row in ppt_rows],
        },
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    rendered = _markdown(report)
    REPORT_MD.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())