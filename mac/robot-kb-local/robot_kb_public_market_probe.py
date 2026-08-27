from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from playwright.sync_api import sync_playwright

import v4_cardova_public_inventory as cardova
import v4_global_comc_hardening as comc
import v4_global_marketplace_scan as scan
import v4_global_retrieval_hardening_v2 as retrieval_v2


def _safe_path(value: object) -> str:
    try:
        parsed = urlsplit(str(value or ""))
    except Exception:
        return ""
    host = (parsed.hostname or "").casefold()
    if not host:
        return ""
    return f"{host}{parsed.path}"


def _json_shape(value: object) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {
            "type": "object",
            "keys": sorted(str(key) for key in value.keys())[:24],
        }
    if isinstance(value, list):
        keys: set[str] = set()
        mapping_rows = 0
        for row in value[:50]:
            if isinstance(row, Mapping):
                mapping_rows += 1
                keys.update(str(key) for key in row.keys())
        return {
            "type": "array",
            "length": len(value),
            "mapping_rows_sample": mapping_rows,
            "row_keys": sorted(keys)[:24],
        }
    return {"type": type(value).__name__}


def _probe_fanatics(page: Any) -> dict[str, Any]:
    json_paths: Counter[str] = Counter()
    json_shapes: dict[str, dict[str, Any]] = {}

    def on_response(response: Any) -> None:
        try:
            request = response.request
            if str(request.method or "").upper() != "GET":
                return
            content_type = str(response.headers.get("content-type") or "").casefold()
            if "json" not in content_type:
                return
            path = _safe_path(response.url)
            if not path or "fanaticscollect.com" not in path:
                return
            json_paths[path] += 1
            if path not in json_shapes:
                try:
                    json_shapes[path] = _json_shape(response.json())
                except Exception:
                    json_shapes[path] = {"type": "unreadable-json"}
        except Exception:
            return

    page.on("response", on_response)
    try:
        page.goto(scan.FANATICS_BROWSE, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(3500)
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(900)
        hrefs = page.evaluate(
            "() => Array.from(document.querySelectorAll('a[href]')).map(a => a.href).filter(Boolean)"
        )
        html = page.content()
        body = page.locator("body").inner_text(timeout=5000)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass

    routes: list[str] = []
    for href in hrefs if isinstance(hrefs, list) else []:
        canonical = retrieval_v2._canonical_fanatics_url(str(href))
        if canonical and canonical not in routes:
            routes.append(canonical)
    for match in retrieval_v2.FANATICS_ROUTE_RE.finditer(html):
        canonical = retrieval_v2._canonical_fanatics_url(match.group(0))
        if canonical and canonical not in routes:
            routes.append(canonical)

    return {
        "anchor_count": len(hrefs) if isinstance(hrefs, list) else 0,
        "buy_now_routes": len(routes),
        "body_has_all_items": "All Items" in body,
        "body_has_sign_in": "sign in" in body.casefold(),
        "json_get_paths": dict(json_paths.most_common(12)),
        "json_shapes": {key: json_shapes[key] for key, _count in json_paths.most_common(8)},
    }


def _probe_comc(page: Any) -> dict[str, Any]:
    urls = {
        "legacy_current": scan._comc_page_url(1),
        "canonical_text_first": (
            "https://www.comc.com/Cards/Pokemon%2Csn%2CvText%2Ci100%2CaGraded%2CrPSA%2Cg10"
        ),
        "graded_text_control": "https://www.comc.com/Cards/Pokemon%2Csn%2CvText%2Ci100%2CaGraded",
    }
    output: dict[str, Any] = {}
    for name, url in urls.items():
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(900)
            rows = comc._table_rows(page)
            body = page.locator("body").inner_text(timeout=5000)
            output[name] = {
                "rows": len(rows),
                "has_listings": "Listings " in body,
                "has_psa10": "PSA 10" in body or "PSA\u00a010" in body,
                "final_path": _safe_path(page.url),
                "title": page.title()[:160],
            }
        except Exception as error:
            output[name] = {"error": type(error).__name__}
    return output


def _probe_cardova(page: Any) -> dict[str, Any]:
    capture = cardova.capture_cardova_public_inventory(page, max_pages_each=2, settle_ms=1000)
    return {
        "status": capture.status,
        "pages_visited": capture.pages_visited,
        "json_responses": capture.json_responses,
        "raw_listing_rows": capture.raw_listing_rows,
        "accepted_rows": capture.accepted_rows,
        "rejected_rows": dict(capture.rejected_rows),
        "complete": capture.complete,
    }


def main() -> int:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="en-US",
            user_agent="Mozilla/5.0",
        )
        page = context.new_page()
        result = {
            "fanatics": _probe_fanatics(page),
            "comc": _probe_comc(page),
            "cardova": _probe_cardova(page),
            "safety": {
                "anonymous_fresh_context": True,
                "credentials_loaded": False,
                "writes": False,
                "automatic_purchase": False,
                "automatic_bid": False,
                "automatic_checkout": False,
                "automatic_payment": False,
            },
        }
        context.close()
        browser.close()
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
