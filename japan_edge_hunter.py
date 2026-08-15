"""Read-only Japan Edge Hunter.

Scans fixed asks on Mercari Japan, Magi and Yahoo! Flea Market and compares them
only with strict Japanese PSA 10 GCC SOLD anchors. Asks are never sales. No
purchase/bid/checkout/payment code exists here.
"""
from __future__ import annotations

import argparse, hashlib, json, os, re, unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import quote

import requests
from ecb_fx import ECBCurrencyConverter

GCC_API_URL = "https://api.gradedcardcenter.com/on-sale-items"
CARD_RE = re.compile(r"(?<![A-Z0-9])#?([A-Z0-9-]{1,12})\s*/\s*([A-Z0-9-]{1,12})(?![A-Z0-9])", re.I)
PSA10_RE = re.compile(r"\bPSA\s*(?:GEM\s*MT\s*)?10(?:\.0)?\b", re.I)
YEN_RE = re.compile(r"(?:[¥￥]\s*(\d{1,3}(?:,\d{3})+|\d{3,8})|(\d{1,3}(?:,\d{3})+|\d{3,8})\s*円)")
AUCTION = ("現在", "入札", "オークション", "auction", "bidding", "current bid")
MULTI = ("2枚", "3枚", "4枚", "5枚", "10枚", "セット販売", "まとめ売り", "連番", "bundle", "lot of", "set of")
JP = ("japanese", "japan", "jp", "jpn", "日本語", "日本版", "日本")

@dataclass(frozen=True)
class Identity:
    name: str; set_name: str; number: str; language: str; grader: str; grade: str; year: int
    edition: str = ""; attribute: str = ""; variety: str = ""; rarity: str = ""
    @property
    def key(self) -> str:
        return "|".join(norm(x) for x in (self.name,self.set_name,self.number,self.language,self.grader,self.grade,self.year,self.edition,self.attribute,self.variety,self.rarity))

@dataclass(frozen=True)
class Sold:
    identity: Identity; price_eur: float; sold_at: datetime; source_id: str

@dataclass(frozen=True)
class Reference:
    identity: Identity; fair_eur: float; sold_count: int; recent_90: int; evidence: str

@dataclass(frozen=True)
class Ask:
    provider: str; url: str; title: str; price_jpy: int; text: str = ""

@dataclass(frozen=True)
class Opportunity:
    provider: str; url: str; title: str; price_jpy: int; ask_eur: float; ask_chf: Optional[float]
    landed_eur: float; landed_chf: Optional[float]; fair_eur: float; discount_pct: float
    gcc_sold_count: int; gcc_recent_90: int; evidence: str; identity: Identity

@dataclass
class Diagnostics:
    gcc_pages: int=0; gcc_rows: int=0; eligible_sold: int=0; references: int=0; seeds: int=0
    provider_searches: int=0; search_candidates: int=0; cheap_candidates: int=0; detail_pages: int=0
    exact_candidates: int=0; identity_rejected: int=0; auctions_skipped: int=0; opportunities: int=0
    provider_errors: dict[str,int]=field(default_factory=dict)

@dataclass(frozen=True)
class Provider:
    code: str; search_url: str; item_re: re.Pattern[str]

PROVIDERS = (
    Provider("mercari", "https://jp.mercari.com/search?keyword={q}", re.compile(r"^https://jp\.mercari\.com/item/[A-Za-z0-9_-]+$",re.I)),
    Provider("magi", "https://magi.camp/items/search?forms_search_items%5Bkeyword%5D={q}&utf8=%E2%9C%93", re.compile(r"^https://magi\.camp/items/\d+$",re.I)),
    Provider("yahoo_fleamarket", "https://paypayfleamarket.yahoo.co.jp/search/{q}", re.compile(r"^https://paypayfleamarket\.yahoo\.co\.jp/item/[A-Za-z0-9_-]+$",re.I)),
)

def now_utc(): return datetime.now(timezone.utc)
def norm(v):
    s=unicodedata.normalize("NFKC",str(v or "")).casefold().strip(); s=re.sub(r"[‐‑‒–—−]","-",s)
    return re.sub(r"\s+"," ",re.sub(r"[^\w/+#.-]+"," ",s,flags=re.UNICODE)).strip()
def number(v):
    m=CARD_RE.search(unicodedata.normalize("NFKC",str(v or "")).upper().replace(" ",""));
    return f"{m.group(1).lstrip('0') or '0'}/{m.group(2).lstrip('0') or '0'}" if m else ""
def parse_time(v):
    if not isinstance(v,str) or not v.strip(): return None
    try:
        d=datetime.fromisoformat(v.strip().replace("Z","+00:00")); return d.astimezone(timezone.utc) if d.tzinfo else None
    except ValueError: return None
def contains(text, phrase):
    h,n=norm(text),norm(phrase)
    if not h or not n:return False
    if any("\u3040"<=c<="\u30ff" or "\u4e00"<=c<="\u9fff" for c in n): return n in h
    return f" {n} " in f" {h} "
def has_any(text, values): return any(contains(text,x) for x in values)
def number_tokens(text): return {number(m.group(0)) for m in CARD_RE.finditer(unicodedata.normalize("NFKC",text or "").upper())}
def current_text(text): return re.split(r"おすすめ|関連商品|類似商品|この商品を見ている人|Recommended|Related items?|Similar items?",text or "",maxsplit=1,flags=re.I)[0][:8000]
def parse_yen(text):
    vals=[]
    for m in YEN_RE.finditer(unicodedata.normalize("NFKC",text or "")):
        try:v=int((m.group(1) or m.group(2)).replace(",",""))
        except ValueError:continue
        if 300<=v<=50_000_000:vals.append(v)
    return min(vals) if vals else None

def sold_from_gcc(row: Mapping[str,Any]) -> Optional[Sold]:
    if str(row.get("status") or "").upper()!="SOLD": return None
    d=parse_time(row.get("soldAt")); sid=str(row.get("id") or "").strip(); item=row.get("item")
    cents=row.get("priceInCents"); p=(cents/100 if isinstance(cents,int) and not isinstance(cents,bool) and cents>0 else row.get("price"))
    if d is None or not sid or not isinstance(p,(int,float)) or p<=0 or not isinstance(item,Mapping):return None
    c=item.get("collectible")
    if not isinstance(c,Mapping) or norm(c.get("category"))!="pokemon" or norm(c.get("type"))!="cards" or norm(c.get("language"))!="japanese":return None
    if str(item.get("gradingCompany") or "").upper()!="PSA" or str(item.get("grade") or "").strip() not in {"10","10.0"}:return None
    ch=c.get("character"); name=str((ch or {}).get("englishName") or (ch or {}).get("name") or "").strip() if isinstance(ch,Mapping) else ""
    try:year=int(c.get("yearOfDistribution"))
    except (TypeError,ValueError):return None
    ident=Identity(name,str(c.get("set") or "").strip(),number(c.get("reference")),"Japanese","PSA","10",year,str(c.get("edition") or "").strip(),str(c.get("attribute") or "").strip(),str(c.get("variety") or "").strip(),str(c.get("rarity") or "").strip())
    if not ident.name or not ident.set_name or not ident.number or not 1996<=year<=2100:return None
    return Sold(ident,round(float(p),2),d,sid)

def references(sales: Iterable[Sold], now: Optional[datetime]=None) -> list[Reference]:
    n=now or now_utc(); groups={}
    for s in sales:
        age=(n-s.sold_at).total_seconds()/86400
        if 0<=age<=365: groups.setdefault(s.identity.key,[]).append(s)
    out=[]
    for vals in groups.values():
        vals.sort(key=lambda x:x.sold_at,reverse=True); recent=[x for x in vals if (n-x.sold_at).total_seconds()/86400<=90]
        basis=(recent[:10] if len(recent)>=2 else vals[:10] if len(vals)>=3 else [])
        if len(basis)<2:continue
        out.append(Reference(basis[0].identity,round(float(median([x.price_eur for x in basis])),2),len(basis),len(recent),"GCC_EXACT_SOLD_RECENT" if len(recent)>=2 else "GCC_EXACT_SOLD_365D"))
    return sorted(out,key=lambda r:(r.recent_90,r.sold_count,r.fair_eur),reverse=True)

def identity_check(ask: Ask, ident: Identity) -> tuple[bool,str]:
    text=current_text("\n".join(x for x in (ask.title,ask.text) if x))
    if has_any(text,AUCTION):return False,"ongoing_auction"
    if has_any(text,MULTI):return False,"multi_item_listing"
    if ident.number not in number_tokens(text):return False,"collector_number_unproven"
    if not PSA10_RE.search(unicodedata.normalize("NFKC",text)):return False,"psa10_unproven"
    if not has_any(text,JP):return False,"language_unproven"
    if not (contains(text,ident.set_name) or contains(text,ident.name)):return False,"card_or_set_unproven"
    ed=norm(ident.edition)
    if ed and (ident.year<=2003 or ed not in {"unlimited","standard"}) and not contains(text,ed):return False,"edition_unproven"
    for raw in (ident.attribute,ident.variety):
        t=norm(raw)
        if t and any(x in t for x in ("1st edition","first edition","shadowless","incorrect texture","error","stamp","stamped","reverse","master ball","pokeball")) and not contains(text,t):
            return False,"microvariant_unproven"
    return True,"strict_text_identity"

def landed_eur(jpy,jpy_per_eur,proxy=500,buffer_pct=12.0):
    return float((Decimal(jpy+max(0,proxy))/jpy_per_eur)*(Decimal(1)+Decimal(str(max(0,buffer_pct)))/100))
def evaluate(ask:Ask,ref:Reference,jpy_per_eur:Decimal,chf_per_eur:Optional[Decimal]=None,min_discount=30.0,proxy=500,buffer_pct=12.0):
    ok,_=identity_check(ask,ref.identity)
    if not ok:return None
    landed=landed_eur(ask.price_jpy,jpy_per_eur,proxy,buffer_pct); discount=(ref.fair_eur-landed)/ref.fair_eur*100 if ref.fair_eur>0 else 0
    if discount+1e-9<min_discount:return None
    ae=float(Decimal(ask.price_jpy)/jpy_per_eur); ac=float(Decimal(str(ae))*chf_per_eur) if chf_per_eur else None; lc=float(Decimal(str(landed))*chf_per_eur) if chf_per_eur else None
    return Opportunity(ask.provider,ask.url,ask.title,ask.price_jpy,round(ae,2),round(ac,2) if ac is not None else None,round(landed,2),round(lc,2) if lc is not None else None,ref.fair_eur,round(discount,1),ref.sold_count,ref.recent_90,ref.evidence,ref.identity)

def fetch_gcc(max_pages=20,diag:Optional[Diagnostics]=None):
    out=[]
    with requests.Session() as s:
        for p in range(1,max(1,max_pages)+1):
            r=s.get(GCC_API_URL,params={"sellingTypeGroup":"AUCTION","status":"SOLD","sortType":"MOST_RECENT","page":p,"limit":100,"includeCounts":"true" if p==1 else "false"},headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"},timeout=15); r.raise_for_status(); data=r.json(); rows=data.get("results") if isinstance(data,Mapping) else None
            if not isinstance(rows,list):raise RuntimeError(f"GCC SOLD page {p} malformed")
            if diag:diag.gcc_pages+=1;diag.gcc_rows+=len(rows)
            if not rows:break
            for row in rows:
                x=sold_from_gcc(row) if isinstance(row,Mapping) else None
                if x:out.append(x); diag and setattr(diag,"eligible_sold",diag.eligible_sold+1)
            if isinstance(data.get("info"),Mapping) and not data["info"].get("nextPage"):break
    return out

def canonical_url(provider:Provider,href:str):
    h=(href or "").strip()
    if h.startswith("/"):h={"mercari":"https://jp.mercari.com","magi":"https://magi.camp","yahoo_fleamarket":"https://paypayfleamarket.yahoo.co.jp"}[provider.code]+h
    h=h.split("#",1)[0].split("?",1)[0]
    return h if provider.item_re.match(h) else None

def collect(page,provider:Provider,ident:Identity,max_items=25):
    page.goto(provider.search_url.format(q=quote(f"{ident.number} PSA10",safe="")),wait_until="domcontentloaded",timeout=20000);page.wait_for_timeout(700)
    rows=page.evaluate(r"""() => Array.from(document.querySelectorAll('a[href]')).slice(0,1200).map(a=>{let n=a,t=(a.innerText||a.textContent||'').trim();for(let i=0;i<6&&n;i++,n=n.parentElement){const x=(n.innerText||n.textContent||'').trim();if(/[¥￥]|\d[\d,]*\s*円/.test(x)){t=x;break;}}return {href:a.href||'',anchor:(a.innerText||'').trim(),text:t};})""")
    out=[];seen=set()
    for row in rows if isinstance(rows,list) else []:
        if not isinstance(row,Mapping):continue
        u=canonical_url(provider,str(row.get("href") or ""));snip=str(row.get("text") or "")
        if not u or u in seen or has_any(snip,AUCTION):continue
        price=parse_yen(snip)
        if price is None:continue
        title=str(row.get("anchor") or "").strip() or next((x.strip() for x in snip.splitlines() if x.strip()),"")
        out.append(Ask(provider.code,u,title[:500],price,snip[:4000]));seen.add(u)
        if len(out)>=max_items:break
    return out

def detail(page,ask:Ask):
    page.goto(ask.url,wait_until="domcontentloaded",timeout=20000);page.wait_for_timeout(500)
    try:body=page.locator("body").inner_text(timeout=5000)
    except Exception:body=ask.text
    try:title=page.title().strip() or ask.title
    except Exception:title=ask.title
    return Ask(ask.provider,ask.url,title[:500],ask.price_jpy,(ask.text+"\n---DETAIL---\n"+body)[:30000])
def load_state(path):
    try:x=json.loads(path.read_text()) if path.exists() else {}
    except Exception:x={}
    return {"cursor":max(0,int(x.get("cursor",0))) if str(x.get("cursor",0)).isdigit() else 0,"notified":x.get("notified",{}) if isinstance(x.get("notified"),dict) else {}}
def save_state(path,state):path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name("."+path.name+".tmp");tmp.write_text(json.dumps(state,indent=2,sort_keys=True));tmp.replace(path)
def seed_slice(refs,state,count):
    if not refs:return [],0
    x=sorted(refs,key=lambda r:r.identity.key);c=int(state.get("cursor",0))%len(x);n=min(max(0,count),len(x));return [x[(c+i)%len(x)] for i in range(n)],(c+n)%len(x)
def fingerprint(op):return hashlib.sha256(f"{op.provider}|{op.url}|{op.price_jpy}".encode()).hexdigest()
def notify(op,server,topic):
    landed=f"{op.landed_chf:.0f} CHF" if op.landed_chf is not None else f"€{op.landed_eur:.0f}"
    body=f"{op.identity.name} {op.identity.number} PSA 10\n{op.provider}: ¥{op.price_jpy:,} | rendu estimé {landed}\nFair GCC SOLD: €{op.fair_eur:.0f} | décote ~{op.discount_pct:.0f}%\nPreuve: {op.gcc_sold_count} SOLD exacts ({op.gcc_recent_90} <90j)\nASK, PAS UNE VENTE\n{op.url}"
    requests.post(f"{server.rstrip('/')}/{topic}",data=body.encode(),headers={"Title":"JAPAN EDGE >=30%","Priority":"high"},timeout=8).raise_for_status()

def run(state_path:Path,output_path:Path,max_gcc_pages=20,max_seeds=12,max_items=25,min_discount=30.0,proxy=500,buffer_pct=12.0,notify_enabled=False,server="https://ntfy.sh",topic=""):
    diag=Diagnostics();state=load_state(state_path);refs=references(fetch_gcc(max_gcc_pages,diag));diag.references=len(refs);seeds,cursor=seed_slice(refs,state,max_seeds);diag.seeds=len(seeds)
    snap=ECBCurrencyConverter(timeout_seconds=8).get_snapshot()
    if not snap or not snap.units_per_eur.get("JPY"):raise RuntimeError("ECB JPY rate unavailable; fail-closed")
    jpy=snap.units_per_eur["JPY"];chf=snap.units_per_eur.get("CHF");ops=[];reviews=[]
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True);page=browser.new_page(locale="ja-JP")
        for ref in seeds:
            for provider in PROVIDERS:
                diag.provider_searches+=1
                try:asks=collect(page,provider,ref.identity,max_items)
                except Exception:diag.provider_errors[provider.code]=diag.provider_errors.get(provider.code,0)+1;continue
                diag.search_candidates+=len(asks)
                for ask in asks:
                    rough=landed_eur(ask.price_jpy,jpy,proxy,buffer_pct);gap=(ref.fair_eur-rough)/ref.fair_eur*100 if ref.fair_eur>0 else 0
                    if gap+1e-9<min_discount:continue
                    diag.cheap_candidates+=1
                    try:a=detail(page,ask);diag.detail_pages+=1
                    except Exception:a=ask
                    ok,reason=identity_check(a,ref.identity)
                    if reason=="ongoing_auction":diag.auctions_skipped+=1;continue
                    if not ok:diag.identity_rejected+=1;reviews.append({"provider":ask.provider,"url":ask.url,"price_jpy":ask.price_jpy,"possible_discount_pct":round(gap,1),"identity_status":"UNPROVEN_LOG_ONLY","reason":reason,"target":asdict(ref.identity)});continue
                    diag.exact_candidates+=1;op=evaluate(a,ref,jpy,chf,min_discount,proxy,buffer_pct)
                    if op:ops.append(op)
        browser.close()
    unique={}
    for op in ops:
        k=(op.provider,op.url)
        if k not in unique or op.discount_pct>unique[k].discount_pct:unique[k]=op
    ops=sorted(unique.values(),key=lambda x:x.discount_pct,reverse=True);diag.opportunities=len(ops)
    n=now_utc();cut=n-timedelta(days=14);notified={k:v for k,v in state["notified"].items() if (parse_time(v) or datetime.min.replace(tzinfo=timezone.utc))>=cut}
    if notify_enabled and topic:
        for op in ops:
            fp=fingerprint(op)
            if fp not in notified:notify(op,server,topic);notified[fp]=n.isoformat().replace("+00:00","Z")
    save_state(state_path,{"cursor":cursor,"notified":notified,"updated_at":n.isoformat().replace("+00:00","Z")})
    payload={"generated_at":n.isoformat().replace("+00:00","Z"),"mode":"READ_ONLY_SHADOW","marketplace_observations_are":"ASK_NOT_SOLD","threshold":{"min_discount_pct_after_buffer":min_discount,"proxy_fixed_jpy":proxy,"logistics_buffer_pct":buffer_pct},"diagnostics":asdict(diag),"opportunities":[asdict(x) for x in ops],"manual_reviews_log_only":reviews[:100],"safety":{"purchase":False,"bid":False,"checkout":False,"payment":False}}
    output_path.parent.mkdir(parents=True,exist_ok=True);output_path.write_text(json.dumps(payload,ensure_ascii=False,indent=2));return payload

def env_i(n,d):
    try:return int(os.getenv(n,str(d)))
    except ValueError:return d
def env_f(n,d):
    try:return float(os.getenv(n,str(d)))
    except ValueError:return d
def main():
    p=argparse.ArgumentParser();p.add_argument("--state",default=".japan-edge-state/state.json");p.add_argument("--output",default="japan_edge_report.json");a=p.parse_args()
    x=run(Path(a.state),Path(a.output),max(1,env_i("JAPAN_EDGE_GCC_PAGES",20)),max(1,env_i("JAPAN_EDGE_MAX_SEEDS_PER_RUN",12)),max(1,env_i("JAPAN_EDGE_MAX_ITEMS_PER_SEARCH",25)),max(0,env_f("JAPAN_EDGE_MIN_DISCOUNT_PCT",30)),max(0,env_i("JAPAN_EDGE_PROXY_FIXED_JPY",500)),max(0,env_f("JAPAN_EDGE_LOGISTICS_BUFFER_PCT",12)),os.getenv("JAPAN_EDGE_NOTIFY_ENABLED","false").lower()=="true",os.getenv("NTFY_SERVER","https://ntfy.sh"),os.getenv("NTFY_TOPIC","").strip())
    print(json.dumps({"opportunities":len(x["opportunities"]),"manual_reviews":len(x["manual_reviews_log_only"]),"diagnostics":x["diagnostics"]},ensure_ascii=False))
if __name__=="__main__":main()
