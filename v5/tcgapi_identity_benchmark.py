from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Mapping, Sequence

import requests

BASE_URL = "https://api.tcgapi.dev/v1/search"
HTTP_CALL_CAP = 18
STOP_DAILY_REMAINING = 15
REPORT_JSON = Path("tcgapi_identity_benchmark.json")
REPORT_MD = Path("tcgapi_identity_benchmark.md")


@dataclass(frozen=True)
class Target:
    tcgdex_id: str
    name: str
    set_name: str
    number: str
    language: str = "en"


# Same 18-card panel as the PokemonPriceTracker benchmark from 2026-08-15.
PANEL = (
    Target("swsh7-215", "Umbreon VMAX", "Evolving Skies", "215"),
    Target("swsh8-271", "Gengar VMAX", "Fusion Strike", "271"),
    Target("swsh11-186", "Giratina V", "Lost Origin", "186"),
    Target("swsh12-186", "Lugia V", "Silver Tempest", "186"),
    Target("swsh9-154", "Charizard V", "Brilliant Stars", "154"),
    Target("swsh7-218", "Rayquaza VMAX", "Evolving Skies", "218"),
    Target("swsh7-205", "Leafeon VMAX", "Evolving Skies", "205"),
    Target("swsh7-212", "Sylveon VMAX", "Evolving Skies", "212"),
    Target("swsh8-270", "Espeon VMAX", "Fusion Strike", "270"),
    Target("swsh7-192", "Dragonite V", "Evolving Skies", "192"),
    Target("swsh6-201", "Blaziken VMAX", "Chilling Reign", "201"),
    Target("swsh5-155", "Tyranitar V", "Battle Styles", "155"),
    Target("swsh10-172", "Machamp V", "Astral Radiance", "172"),
    Target("swsh11-180", "Aerodactyl V", "Lost Origin", "180"),
    Target("swsh4-188", "Pikachu VMAX", "Vivid Voltage", "188"),
    Target("base1-4", "Charizard", "Base Set", "4"),
    Target("neo1-9", "Lugia", "Neo Genesis", "9"),
    Target("base1-58", "Pikachu", "Base Set", "58"),
)


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _number(value: object) -> str:
    raw = str(value or "").strip()
    numerator = raw.split("/", 1)[0].strip()
    if numerator.isdigit():
        return str(int(numerator))
    return numerator.casefold()


def _rows(payload: object) -> list[Mapping[str, object]]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, Sequence) or isinstance(data, (str, bytes)):
        return []
    return [row for row in data if isinstance(row, Mapping)]


def _remaining(response, payload: object) -> int | None:
    raw = response.headers.get("X-RateLimit-Remaining")
    if raw is None and isinstance(payload, Mapping):
        rate = payload.get("rate_limit")
        if isinstance(rate, Mapping):
            raw = rate.get("daily_remaining")
    try:
        return int(str(raw)) if raw is not None else None
    except (TypeError, ValueError):
        return None


def classify(target: Target, rows: Sequence[Mapping[str, object]]) -> tuple[str, list[dict[str, object]]]:
    exact: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("product_type") or "Cards") != "Cards":
            continue
        if _norm(row.get("name")) != _norm(target.name):
            continue
        if _norm(row.get("set_name")) != _norm(target.set_name):
            continue
        if _number(row.get("number")) != _number(target.number):
            continue
        exact.append(
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "set_name": row.get("set_name"),
                "number": row.get("number"),
                "printing": row.get("printing"),
                "foil_only": row.get("foil_only"),
            }
        )
    if len(exact) == 1:
        # tcgapi.dev's documented card/search schema does not expose language.
        # This is a macro exact only; language remains explicitly unproven.
        return "MACRO_EXACT_LANGUAGE_UNPROVEN", exact
    if len(exact) > 1:
        return "AMBIGUOUS", exact
    return "NO_MATCH", []


def main() -> int:
    key = os.getenv("TCGAPI_DEV_API_KEY", "").strip()
    if not key:
        raise SystemExit("TCGAPI_DEV_API_KEY missing")

    session = requests.Session()
    headers = {"Accept": "application/json", "X-API-Key": key}
    results: list[dict[str, object]] = []
    calls = 0
    daily_remaining = None

    for target in PANEL:
        if calls >= HTTP_CALL_CAP:
            break
        response = session.get(
            BASE_URL,
            headers=headers,
            params={
                "q": target.name,
                "game": "pokemon",
                "type": "Cards",
                "per_page": 100,
                "page": 1,
            },
            timeout=15,
        )
        calls += 1
        if response.status_code != 200:
            results.append(
                {"target": asdict(target), "status": f"HTTP_{response.status_code}", "exact": []}
            )
            if response.status_code == 429:
                break
            continue
        try:
            payload = response.json()
        except Exception:
            results.append({"target": asdict(target), "status": "JSON_ERROR", "exact": []})
            continue
        daily_remaining = _remaining(response, payload)
        status, exact = classify(target, _rows(payload))
        results.append({"target": asdict(target), "status": status, "exact": exact})
        if daily_remaining is not None and daily_remaining <= STOP_DAILY_REMAINING:
            break

    macro_exact = sum(row["status"] == "MACRO_EXACT_LANGUAGE_UNPROVEN" for row in results)
    ambiguous = sum(row["status"] == "AMBIGUOUS" for row in results)
    no_match = sum(row["status"] == "NO_MATCH" for row in results)
    failures = len(results) - macro_exact - ambiguous - no_match
    report = {
        "cards_attempted": len(results),
        "http_calls": calls,
        "macro_exact_language_unproven": macro_exact,
        "ambiguous": ambiguous,
        "no_match": no_match,
        "failures": failures,
        "daily_remaining": daily_remaining,
        "language_field_documented": False,
        "microvariant_authority": False,
        "results": results,
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# tcgapi.dev identity benchmark",
        "",
        f"- Cards attempted: `{len(results)}`",
        f"- HTTP calls: `{calls}` / cap `{HTTP_CALL_CAP}`",
        f"- Macro exact, language unproven: `{macro_exact}`",
        f"- Ambiguous: `{ambiguous}`",
        f"- No match: `{no_match}`",
        f"- Failures: `{failures}`",
        f"- Daily remaining: `{daily_remaining}`",
        "- Language accepted as proof: `NO`",
        "- Microvariant accepted as proof: `NO`",
        "",
        "| TCGdex target | Status | Exact candidates |",
        "|---|---|---:|",
    ]
    for row in results:
        target = row["target"]
        lines.append(f"| {target['tcgdex_id']} | {row['status']} | {len(row['exact'])} |")
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
