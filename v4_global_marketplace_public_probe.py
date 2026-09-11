"""Bounded anonymous public-surface evidence for unwired V4 Japan providers.

Diagnostic only: no identity promotion, valuation, login or transaction. Keep
transport blockage distinct from an unproven empty JavaScript shell.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


SURFACES = (
    ("mercari", "https://jp.mercari.com/search?keyword=PSA10%20Pokemon", r"/item/m\d+"),
    ("snkrdunk", "https://snkrdunk.com/en/search/result?keyword=PSA10%20Pokemon", r"/(?:en/)?apparels/\d+/used/\d+"),
)

SNAPSHOT = r"""() => {
 const root = document.querySelector('main,[role=main]');
 return {container:!!root, title:document.title.slice(0,160),
 headings:[...document.querySelectorAll('h1,h2,[role=alert]')].map(e=>e.innerText.slice(0,200)).slice(0,8),
 links:[...document.querySelectorAll('a[href]')].slice(0,1800).map(a=>a.href),
 buttons:[...document.querySelectorAll('button,[role=button]')].filter(e=>e.offsetParent!==null).map(e=>e.innerText.slice(0,80)).filter(Boolean).slice(-12)};
}"""


def probe(page, market, url, item_pattern):
    errors = []
    host = urlsplit(url).hostname
    def response_seen(response):
        parsed = urlsplit(response.url)
        family = re.search(r"/(?:v\d+/)?(search|entities|items|products|listings|inventory)(?:/|:|$)", parsed.path)
        if len(errors) < 12 and response.status >= 400 and family:
            if (parsed.hostname or "").endswith(("mercari.jp", "mercari.com", "snkrdunk.com")):
                errors.append({"host": parsed.hostname, "endpoint_family": family.group(1), "http": response.status})
    result = {"market": market, "state": "CONTENT_UNPROVEN", "http": None,
              "observations": 0, "urls": [], "complete": False, "provider_errors": errors}
    page.on("response", response_seen)
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        result["http"] = response.status if response else None
        if result["http"] is not None and result["http"] >= 400:
            result["state"] = "HTTP_BLOCKED" if result["http"] in {401, 403, 429} else "HTTP_ERROR"
            return result
        if urlsplit(page.url).hostname != host or urlsplit(page.url).path != urlsplit(url).path:
            result["state"] = "UNEXPECTED_REDIRECT"
            return result
        for _ in range(3):
            page.wait_for_timeout(3000)
            snapshot = page.evaluate(SNAPSHOT)
            result["observations"] += 1
            urls = set()
            for raw in snapshot.get("links", []):
                parsed = urlsplit(str(raw))
                if parsed.scheme == "https" and parsed.hostname == host and re.fullmatch(item_pattern, parsed.path):
                    urls.add(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", "")))
            result["snapshot"] = {k: snapshot.get(k) for k in ("container", "title", "headings", "buttons")}
            result["urls"] = sorted(urls)[:100]
            if urls:
                result["state"] = "RESULTS"
                break
    except Exception as error:
        result["state"] = "INSPECTION_ERROR"
        result["error_class"] = type(error).__name__
    finally:
        page.remove_listener("response", response_seen)
    return result


def main():
    from playwright.sync_api import sync_playwright
    results = []
    with sync_playwright() as runtime:
        browser = runtime.chromium.launch(headless=True)
        try:
            for market, url, pattern in SURFACES:
                context = browser.new_context()
                try:
                    result = probe(context.new_page(), market, url, pattern)
                    results.append(result)
                    print("[V4_PUBLIC_SURFACE] " + json.dumps(result, ensure_ascii=False), flush=True)
                finally:
                    context.close()
        finally:
            browser.close()
    path = Path("global_marketplace_out/public_surface_probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notifications": False, "transactions": False, "surfaces": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
