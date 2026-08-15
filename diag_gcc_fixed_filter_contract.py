from __future__ import annotations

import json
from typing import Any

import requests

URL = "https://api.gradedcardcenter.com/on-sale-items"
BASE = {
    "sellingTypes": "FIXED_PRICE",
    "categories": "Pokemon",
    "itemTypes": "CARDS",
    "status": "ON_SALE",
    "page": 1,
    "limit": 24,
    "includeCounts": "true",
}
HEADERS = {"Accept": "application/json", "x-device-platform": "web", "User-Agent": "Mozilla/5.0"}


def query(extra: dict[str, Any]) -> tuple[int, dict[str, Any] | None]:
    params = dict(BASE)
    params.update(extra)
    r = requests.get(URL, params=params, headers=HEADERS, timeout=20)
    try:
        payload = r.json()
    except Exception:
        payload = None
    return r.status_code, payload if isinstance(payload, dict) else None


def ids(payload: dict[str, Any] | None) -> list[str]:
    if not payload or not isinstance(payload.get("results"), list):
        return []
    return [str(row.get("id")) for row in payload["results"] if isinstance(row, dict) and row.get("id")]


def count(payload: dict[str, Any] | None) -> int:
    if not payload or not isinstance(payload.get("results"), list):
        return -1
    return len(payload["results"])


def main() -> int:
    status, base = query({"sortType": "MOST_RECENT"})
    print(f"BASE MOST_RECENT status={status} rows={count(base)} ids={ids(base)[:3]}")

    # The public web UI serializes multi-select filters as JSON arrays in the URL.
    # Use impossible values: a recognized filter should normally return zero rows;
    # an ignored parameter will usually leave the same first-page IDs unchanged.
    candidates = [
        "languages",
        "gradingCompanies",
        "grades",
        "editions",
        "extensions",
        "series",
        "characters",
        "years",
        "manufacturingYears",
    ]
    base_ids = ids(base)
    for key in candidates:
        for encoded in (json.dumps(["__KB_NO_MATCH_9F3C__"]), "__KB_NO_MATCH_9F3C__"):
            s, payload = query({"sortType": "MOST_RECENT", key: encoded})
            current = ids(payload)
            print(
                f"FILTER key={key} mode={'json-array' if encoded.startswith('[') else 'scalar'} "
                f"status={s} rows={count(payload)} same_as_base={current == base_ids} ids={current[:3]}"
            )

    for sort_type in ("MOST_RECENT", "OLDEST", "PRICE_ASC", "PRICE_DESC", "__INVALID_SORT__"):
        s, payload = query({"sortType": sort_type})
        print(f"SORT value={sort_type} status={s} rows={count(payload)} ids={ids(payload)[:3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
