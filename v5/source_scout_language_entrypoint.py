from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from typing import Mapping, Sequence
from urllib.parse import quote

from . import source_scout_benchmark as scout
from .models import CardIdentity

LANGUAGES: Sequence[str] = ("en", "fr", "de", "it", "es", "ja")
CARDS_PER_LANGUAGE = 3
PANEL_SIZE = len(LANGUAGES) * CARDS_PER_LANGUAGE


def _spread_indices(length: int, count: int = 10) -> tuple[int, ...]:
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
        call_cap=100,
        interval=0.04,
        response_cap=2_000_000,
        total_cap=60_000_000,
    )
    panel: list[scout.PanelCard] = []
    diagnostics: dict[str, object] = {"mode": "LANGUAGE_STRATIFIED_TCGDEX", "languages": {}}

    for language in LANGUAGES:
        if len(panel) >= target or client.runtime.blocked:
            break
        before = len(panel)
        response, sets_payload = client.request(
            "GET", f"https://api.tcgdex.net/v2/{quote(language, safe='')}/sets"
        )
        sets = sets_payload if isinstance(sets_payload, list) else []
        if not response or response.status_code != 200:
            diagnostics["languages"][language] = {"seeded": 0, "error": f"HTTP_{getattr(response, 'status_code', 'REQUEST')}"}
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
            if len(panel) - before >= CARDS_PER_LANGUAGE or len(panel) >= target or client.runtime.blocked:
                break
            set_response, set_payload = client.request(
                "GET", f"https://api.tcgdex.net/v2/{quote(language, safe='')}/sets/{quote(set_id, safe='')}"
            )
            if not set_response or set_response.status_code != 200 or not isinstance(set_payload, Mapping):
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
                "GET", f"https://api.tcgdex.net/v2/{quote(language, safe='')}/cards/{quote(card_id, safe='')}"
            )
            if not detail_response or detail_response.status_code != 200 or not isinstance(detail, Mapping):
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


def _skip_pokemonpricetracker(panel, _key):
    return (
        [scout.Observation("pokemonpricetracker", card.label, error="SKIPPED_DAILY_QUOTA_PRESERVATION") for card in panel],
        scout.Runtime(blocked=True),
    )


def _cmapi_one_per_language_factory(original):
    def wrapped(panel, key):
        first_indices: list[int] = []
        seen: set[str] = set()
        for index, card in enumerate(panel):
            language = scout.lang(card.identity.language)
            if language not in seen:
                seen.add(language)
                first_indices.append(index)
        sampled = [panel[index] for index in first_indices]
        sampled_rows, runtime = original(sampled, key)
        expanded = [scout.Observation("cmapi", card.label, error="SKIPPED_LANGUAGE_SAMPLE") for card in panel]
        for index, row in zip(first_indices, sampled_rows):
            expanded[index] = row
        return expanded, runtime
    return wrapped


def _language_summary(report: Mapping[str, object]) -> dict[str, object]:
    panel = report.get("panel") if isinstance(report.get("panel"), list) else []
    observations = report.get("observations") if isinstance(report.get("observations"), Mapping) else {}
    output: dict[str, object] = {}
    for provider in scout.PROVIDERS:
        rows = observations.get(provider) if isinstance(observations.get(provider), list) else []
        provider_out: dict[str, object] = {}
        for language in LANGUAGES:
            indices = [i for i, card in enumerate(panel) if isinstance(card, Mapping) and card.get("language") == language]
            subset = [rows[i] for i in indices if i < len(rows) and isinstance(rows[i], Mapping)]
            provider_out[language] = {
                "cards": len(indices),
                "tested": sum(row.get("error") not in {"SKIPPED_LANGUAGE_SAMPLE", "SKIPPED_DAILY_QUOTA_PRESERVATION"} for row in subset),
                "identity_exact": sum(row.get("identity") == "EXACT" for row in subset),
                "variant_exact": sum(row.get("variant") == "EXACT" for row in subset),
                "language_exact": sum(row.get("language") == "EXACT" for row in subset),
                "raw_usd": sum(row.get("raw_usd") is not None for row in subset),
                "raw_eur": sum(row.get("raw_eur") is not None for row in subset),
                "graded": sum(bool(row.get("graded_available")) for row in subset),
            }
        output[provider] = provider_out
    return output


def _language_markdown(report: Mapping[str, object]) -> str:
    lines = [scout.markdown(report).rstrip(), "", "## By language", ""]
    summary = report.get("language_summary") if isinstance(report.get("language_summary"), Mapping) else {}
    for language in LANGUAGES:
        lines += [f"### {language.upper()}", "", "| Provider | Exact ID | RAW USD | RAW EUR | Graded |", "|---|---:|---:|---:|---:|"]
        for provider in scout.PROVIDERS:
            prow = summary.get(provider) if isinstance(summary.get(provider), Mapping) else {}
            row = prow.get(language) if isinstance(prow.get(language), Mapping) else {}
            lines.append(
                f"| {provider} | {row.get('identity_exact', 0)}/{row.get('tested', 0)} | "
                f"{row.get('raw_usd', 0)} | {row.get('raw_eur', 0)} | {row.get('graded', 0)} |"
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    scout.build_panel = build_language_panel
    scout.PANEL_SIZE = PANEL_SIZE
    os.environ["SOURCE_SCOUT_PANEL_SIZE"] = str(PANEL_SIZE)

    # PokemonPriceTracker Free was already close to its daily credit ceiling in
    # the prior benchmark. Preserve the remaining free quota today.
    scout.pokemonpricetracker = _skip_pokemonpricetracker

    # CMAPI Basic can bill beyond its free allowance. Test only one card per
    # language (6 calls max) and stop with at least a 94-request header buffer.
    scout.CMAPI_CALL_CAP = 6
    scout.CMAPI_RESPONSE_CAP = 1_000_000
    scout.CMAPI_TOTAL_CAP = 6_000_000
    scout.CMAPI_REMAINING_BUFFER = 94
    scout.cmapi = _cmapi_one_per_language_factory(scout.cmapi)
    os.environ["SOURCE_SCOUT_ENABLE_CMAPI"] = "true"

    try:
        report = scout.run()
    except Exception as exc:
        print(f"SOURCE_SCOUT_LANGUAGE_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    report["language_summary"] = _language_summary(report)
    with open(os.getenv("SOURCE_SCOUT_JSON", "source_scout_report.json"), "w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    rendered = _language_markdown(report)
    with open(os.getenv("SOURCE_SCOUT_MARKDOWN", "source_scout_report.md"), "w", encoding="utf-8") as handle:
        handle.write(rendered)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
