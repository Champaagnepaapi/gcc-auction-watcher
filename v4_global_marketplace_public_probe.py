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
 text_length:(document.body?.innerText||'').length, script_count:document.scripts.length,
 forms:[...document.querySelectorAll('form')].map(f=>({action:new URL(f.action,location.href).pathname,method:f.method})).slice(0,4),
 inputs:[...document.querySelectorAll('input[type=search],input[type=text]')].map(e=>({name:e.name.slice(0,60),placeholder:e.placeholder.slice(0,80),visible:!!e.getClientRects().length})).slice(0,6),
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
            result["snapshot"] = {k: snapshot.get(k) for k in ("container", "title", "headings", "buttons", "text_length", "script_count", "forms", "inputs")}
            paths = sorted({urlsplit(str(u)).path for u in snapshot.get("links", []) if urlsplit(str(u)).hostname == host})
            result["snapshot"]["link_paths"] = paths[:25]
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


ITEM_FIELDS = ("カテゴリー", "ブランド", "商品の状態", "配送料の負担", "配送の方法", "発送までの日数", "言語", "枚数", "カード名", "カード番号", "シリーズ", "セット", "鑑定状況", "グレード", "種別", "Language", "Set", "Card Name", "Card Number", "Grading Company", "Grade", "Quantity")
PRODUCT_SNAPSHOT = r"""() => {
 const products=[];
 function visit(x, d=0) {
  if(!x || typeof x!=='object' || d>5) return;
  if(x['@type']==='Product' || (Array.isArray(x['@type']) && x['@type'].includes('Product'))) products.push(x);
  if(Array.isArray(x)) x.forEach(y=>visit(y,d+1));
  else if(x['@graph']) visit(x['@graph'],d+1);
 }
 for(const s of document.querySelectorAll('script[type="application/ld+json"]')) {try{visit(JSON.parse(s.textContent))}catch{}}
 const fields={};
 for(const row of document.querySelectorAll('tr,dl')) {
  const label=row.querySelector('th,dt')?.innerText?.trim();
  if(label) fields[label]=row.querySelector('td,dd')?.innerText?.trim()?.slice(0,160);
 }
 const allowed=new Set(['カテゴリー','商品の状態','配送料の負担','配送の方法','言語','枚数','カード名','カード番号','シリーズ','セット','鑑定状況','グレード','種別','Language','Set','Card Name','Card Number','Grading Company','Grade','Quantity']);
 // Item-scoped schema properties and visible labeled rows only. No seller,
 // account data or arbitrary description is returned by this extractor.
 if(products.length===1 && Array.isArray(products[0].additionalProperty)) {
  for(const p of products[0].additionalProperty) if(allowed.has(p.name) && typeof p.value==='string') fields[p.name]=p.value.slice(0,160);
 }
 for(const e of document.querySelectorAll('main p,main span,main div')) {
  if(e.children.length || !allowed.has(e.innerText.trim())) continue;
  const next=e.nextElementSibling || e.parentElement?.nextElementSibling;
  const value=next?.innerText?.trim();
  if(value && value.length<=160 && !fields[e.innerText.trim()]) fields[e.innerText.trim()]=value;
 }
 return {title:(document.querySelector('h1')?.innerText||'').slice(0,240), product:products.length===1?products[0]:{}, product_count:products.length, fields};
}"""


def inspect_public_item(page, url):
    result = {"url": url, "state": "CONTENT_UNPROVEN", "sold_proven": False}
    try:
        response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
        result["http"] = response.status if response else None
        if result["http"] is not None and result["http"] >= 400:
            result["state"] = "HTTP_BLOCKED" if result["http"] in {401, 403, 429} else "HTTP_ERROR"
            return result
        if (urlsplit(page.url).hostname, urlsplit(page.url).path) != (urlsplit(url).hostname, urlsplit(url).path):
            result["state"] = "UNEXPECTED_REDIRECT"
            return result
        snapshot = {}
        for _ in range(3):
            page.wait_for_timeout(3000)
            snapshot = page.evaluate(PRODUCT_SNAPSHOT)
            if snapshot.get("title") and snapshot.get("product"):
                break
        product = snapshot.get("product") or {}
        result["title"] = str(snapshot.get("title") or "")[:240]
        result["product_count"] = snapshot.get("product_count")
        result["product"] = {k: str(product[k])[:240] for k in ("name", "category", "sku") if k in product}
        offers = product.get("offers") or {}
        if isinstance(offers, dict):
            result["product"]["offers"] = {k: str(offers[k])[:100] for k in ("price", "priceCurrency", "availability", "itemCondition") if k in offers}
        fields = snapshot.get("fields") or {}
        result["fields"] = {k: str(fields[k])[:160] for k in ITEM_FIELDS if k in fields}
        if product and result["title"]:
            result["state"] = "PRODUCT_OBSERVED"
    except Exception as error:
        result["state"] = "INSPECTION_ERROR"
        result["error_class"] = type(error).__name__
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
                    for url in result["urls"][:3]:
                        item = inspect_public_item(context.new_page(), url)
                        print("[V4_PUBLIC_ITEM] " + json.dumps(item, ensure_ascii=False), flush=True)
                finally:
                    context.close()
        finally:
            browser.close()
    path = Path("global_marketplace_out/public_surface_probe.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"notifications": False, "transactions": False, "surfaces": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
