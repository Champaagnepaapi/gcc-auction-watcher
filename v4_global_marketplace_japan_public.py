"""Public item metadata into Global; no inferred language, fees or SOLD state."""
from collections import Counter
import json
import math
import re
import unicodedata
from urllib.parse import urlsplit

from v4_global_marketplace_public_probe import SURFACES, probe, inspect_public_item
from v4_global_marketplace_scan import ScanStatus
from v4_global_marketplace_discovery import listing_from_observation
from v4_global_market_core import CommercialIdentity, PriceObservation, FIXED_ASK
from v4_raw_consensus import MULTILINGUAL_DIMENSION_PATTERNS, parse_multilingual_commercial_dimensions


def _norm(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value or '')).casefold().split())


def _public_identity(item):
    fields = item.get('proven_fields') or {}
    def field(*keys):
        values = {str(fields[k]).strip() for k in keys if fields.get(k)}
        if len({_norm(v) for v in values}) > 1:
            return '__conflict__'
        return next(iter(values), '')
    language_text = field('Language', '言語')
    language = {'japanese':'ja', '日本語':'ja', 'english':'en', '英語':'en'}.get(_norm(language_text))
    if not language:
        return None, 'LANGUAGE_UNPROVEN'
    quantity = field('Quantity', '枚数')
    kind = field('種別')
    if quantity not in {'1', '1枚'} and not (not quantity and kind == 'シングルカード'):
        return None, 'SINGLE_CARD_UNPROVEN'
    if kind and kind != 'シングルカード':
        return None, 'SINGLE_CARD_CONFLICT'
    title = str(item.get('title') or '')
    if re.search(r'\b(?:lot of|set of|bundle|sealed|booster|box)\b|まとめ売り|枚セット', title, re.I):
        return None, 'SINGLE_CARD_CONFLICT'
    name, set_name, number = field('Card Name', 'カード名'), field('Set', 'セット'), field('Card Number', 'カード番号')
    grader, grade = field('Grading Company', '鑑定会社'), field('Grade', 'グレード')
    certification = field('鑑定状況')
    if certification:
        match = re.fullmatch(r'PSA\s*(8(?:\.5)?|9|10)', certification, re.I)
        if not match or (grader and grader.upper() != 'PSA') or (grade and grade != match[1]):
            return None, 'GRADE_CONFLICT'
        grader, grade = 'PSA', match[1]
    if grader.upper() != 'PSA' or grade not in {'8', '8.5', '9', '10'}:
        return None, 'GRADE_UNPROVEN'
    if not name or not set_name or '__conflict__' in (name, set_name, number):
        return None, 'IDENTITY_FIELDS_UNPROVEN'
    if not re.fullmatch(r'#?[A-Za-z]*\d+(?:/[A-Za-z0-9-]+)?', number):
        return None, 'NUMBER_UNPROVEN'
    # Independent title and structured claims must agree. Do not replace the
    # name with a catalog answer or use Japanese script as a language signal.
    name_pattern = re.escape(_norm(name))
    if re.fullmatch(r'[a-z0-9 .\-é]+', _norm(name)):
        name_pattern = r'(?<!\w)' + name_pattern + r'(?!\w)'
    if not re.search(name_pattern, _norm(title)):
        return None, 'TITLE_NAME_CONFLICT'
    for claim in re.findall(r'\bPSA\s*(8(?:\.5)?|9|10)\b', title, re.I):
        if claim != grade:
            return None, 'TITLE_GRADE_CONFLICT'
    for claim in re.findall(r'(?<!\w)(?:#([A-Za-z]*\d+)|([A-Za-z]*\d+/[A-Za-z0-9-]+))(?!\w)', title):
        stated = claim[0] or claim[1]
        normalize_number = lambda n: '/'.join(part.upper().lstrip('0') or '0' for part in n.lstrip('#').split('/'))
        if normalize_number(stated) != normalize_number(number if '/' in stated else number.split('/')[0]):
            return None, 'TITLE_NUMBER_CONFLICT'
    for pattern, code in ((r'\bJapanese\b|日本語', 'ja'), (r'\bEnglish\b|英語', 'en')):
        if re.search(pattern, title, re.I) and code != language:
            return None, 'TITLE_LANGUAGE_CONFLICT'
    dims = parse_multilingual_commercial_dimensions(title)
    if '__conflict__' in dims.values():
        return None, 'MATERIAL_CONFLICT'
    # Account for every title claim using only the independently supplied item
    # fields and known material vocabulary. A different set, card suffix or
    # second card must not vanish when constructing the shared resolver's Lot.
    residual = _norm(title)
    for value in (number, name, set_name):
        residual = residual.replace(_norm(value), ' ')
    residual = re.sub(r'\bpsa\s*' + re.escape(grade) + r'\b', ' ', residual)
    residual = re.sub(r'\b(?:japanese|english|pok[eé]mon|card|gem|mt)\b|日本語|英語|ポケモンカード', ' ', residual)
    for patterns in MULTILINGUAL_DIMENSION_PATTERNS.values():
        for pattern in patterns.values():
            residual = re.sub(pattern, ' ', residual, flags=re.I)
    if re.sub(r'[\W_]+', '', residual):
        return None, 'TITLE_CLAIM_UNPROVEN'
    edition = {'first_edition':'First Edition','unlimited':'Unlimited'}.get(dims.get('edition'), '')
    finish = {'reverse':'Reverse','holo':'Holo','non_holo':'Non Holo'}.get(dims.get('finish'), '')
    # Retain the entire public title for final material gates, including any
    # special foil request. Canonical EXACT remains the shared resolver's job.
    identity = CommercialIdentity(name, set_name, number.lstrip('#'), language, grader.upper(), grade, edition, finish, title)
    return identity, 'PUBLIC_STRUCTURED_IDENTITY'


def _listing(item, market, *, observed_at):
    if item.get('state') != 'PRODUCT_OBSERVED' or item.get('product_count') != 1:
        return None, item.get('state') or 'PRODUCT_UNPROVEN'
    product = item.get('product') or {}
    if product.get('name') and _norm(product['name']) != _norm(item.get('title')):
        return None, 'PRODUCT_TITLE_CONFLICT'
    category = _norm(product.get('category') or (item.get('proven_fields') or {}).get('カテゴリー'))
    if not (re.search(r'\bpok[eé]mon\b', category) or 'ポケモンカードゲーム' in category):
        return None, 'POKEMON_CATEGORY_UNPROVEN'
    offers = product.get('offers') or {}
    if offers.get('availability') not in {'https://schema.org/InStock', 'http://schema.org/InStock'}:
        return None, 'ACTIVE_FIXED_OFFER_UNPROVEN'
    try:
        price = float(offers.get('price'))
    except (ValueError, TypeError):
        return None, 'PRICE_UNPROVEN'
    currency = str(offers.get('priceCurrency') or '').upper()
    if not math.isfinite(price) or price <= 0 or currency not in {'JPY', 'USD'}:
        return None, 'PRICE_UNPROVEN'
    identity, reason = _public_identity(item)
    if identity is None:
        return None, reason
    url = item['url']
    observation = PriceObservation(source=market, identity=identity, evidence_type=FIXED_ASK,
        price=price, currency=currency, observed_at=observed_at, identity_proven=True,
        buyer_fee_rate=None, source_id=urlsplit(url).path,
        note='public item metadata; exact catalog gate required; payment/shipping route unproven')
    return listing_from_observation(observation, source_url=url, title=item['title']), reason


def scan_public_inventory(page, market, *, observed_at, max_detail_pages=20):
    surface = next(entry for entry in SURFACES if entry[0] == market)
    result = probe(page, *surface)
    print('[V4_PUBLIC_SURFACE] ' + json.dumps(result, ensure_ascii=False), flush=True)
    output, rejects = [], Counter()
    urls = result['urls']
    limit = min(20, max(1, int(max_detail_pages)))
    for url in urls[:limit]:
        item = inspect_public_item(page, url)
        listing, reason = _listing(item, market, observed_at=observed_at)
        if listing is not None:
            output.append(listing)
        else:
            rejects[reason] += 1
        item['identity_result'] = reason
        print('[V4_PUBLIC_ITEM] ' + json.dumps(item, ensure_ascii=False), flush=True)
    # Catalogs can locate an offer in future, but are never admitted as one.
    for url in result['catalog_urls'][:3]:
        item = inspect_public_item(page, url)
        item['individual_offer_proven'] = False
        print('[V4_PUBLIC_CATALOG] ' + json.dumps(item, ensure_ascii=False), flush=True)
    detail = (f"public_state={result['state']}; http={result['http']}; inspected={min(limit,len(urls))}; "
              f"catalogs={len(result['catalog_urls'])}; rejects={dict(rejects)}; "
              f"detail_cap_reached={len(urls)>limit}; pagination unproven; costs require buyer route")
    return output, ScanStatus(market, 'OK' if output else 'UNAVAILABLE', result['observations'], len(urls), len(output), detail, False)
