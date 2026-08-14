from __future__ import annotations

import os
from typing import Mapping

from .source_scout_benchmark import SafeClient, maps


def slim(row: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": row.get("name"),
        "setName": row.get("setName") or row.get("set_name"),
        "number": row.get("cardNumber") or row.get("number"),
        "language": row.get("language"),
        "tcgPlayerId": row.get("tcgPlayerId") or row.get("tcgplayerId"),
        "topLevelKeys": sorted(str(k) for k in row.keys()),
    }


def main() -> int:
    key = os.getenv("POKEMONPRICETRACKER_API_KEY", "").strip()
    if not key:
        print("PPT_PROBE_SKIPPED: missing key")
        return 0

    probes = [
        ("EN", {"search": "Shieldon 061", "setName": "Pitch Black", "limit": 5}),
        ("FR-anchor", {"search": "Morpeko V 37", "setName": "Shining Fates", "limit": 5}),
        ("JA", {"search": "ボチ 047", "language": "japanese", "limit": 5}),
    ]
    client = SafeClient("ppt_schema_probe", call_cap=6, interval=0.1)
    for label, params in probes:
        response, payload = client.request(
            "GET",
            "https://www.pokemonpricetracker.com/api/v2/cards",
            headers={"Authorization": f"Bearer {key}"},
            params=params,
        )
        status = getattr(response, "status_code", None)
        print(f"PPT_PROBE {label} status={status} params={params}")
        rows = maps(payload.get("data")) if isinstance(payload, Mapping) else []
        print(f"PPT_PROBE {label} candidates={len(rows)}")
        for row in rows[:5]:
            print(f"PPT_PROBE {label} candidate={slim(row)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
