"""Public browser/source boundaries feeding the real Global candidate pipeline."""
import copy
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

URL = 'https://jp.mercari.com/item/m12345678901'
ITEM = {'title':'Pikachu 025/165 PSA 10', 'product_count':1,
        'product':{'name':'Pikachu 025/165 PSA 10', 'category':'Pokemon',
                   'offers':{'price':'1000','priceCurrency':'JPY','availability':'https://schema.org/InStock'}},
        'fields':{'Language':'Japanese','Card Name':'Pikachu','Set':'151','Card Number':'025/165',
                  'Grading Company':'PSA','Grade':'10','Quantity':'1'}}


class Page:
    def __init__(self, item=None, status=200, structured=True):
        self.item, self.status, self.calls = copy.deepcopy(ITEM if item is None else item), status, []
        if structured:
            self.item['product']['additionalProperty'] = [{'name':k,'value':v} for k,v in self.item['fields'].items()]
    def on(self, *a): pass
    def remove_listener(self, *a): pass
    def goto(self, url, **kwargs):
        self.url = url; self.calls.append(url)
        return SimpleNamespace(status=self.status)
    def wait_for_timeout(self, ms): pass
    def evaluate(self, script):
        return {'links':[URL], 'container':True} if '/search' in self.url else self.item


class JapanPublicInventoryTests(unittest.TestCase):
    def test_native_mercari_labels_and_number_explicitly_in_title(self):
        item = copy.deepcopy(ITEM)
        item['fields'] = {'言語':'日本語版','種別':'シングルカード 1枚', 'カード名':'Pikachu',
                          'セット':'151', 'グレード':'PSA10'}
        rows, _, _ = self.scan(item)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identity.number, '025/165')
        for key, value in [('種別','シングルカード 2枚'),('グレード','PSA9'),('言語','英語版'),('ミラー加工','Master Ball Poke Ball'),('特徴','unknown stamp')]:
            bad = copy.deepcopy(item); bad['fields'][key] = value
            if key == '言語':
                bad['title'] += ' Japanese'; bad['product']['name'] = bad['title']
            self.assertEqual(self.scan(bad)[0], [], (key,value))

    def scan(self, item=None, status=200, structured=True):
        from v4_global_marketplace_japan_public import scan_public_inventory
        page = Page(item, status, structured)
        with patch('requests.sessions.Session.request', side_effect=AssertionError('unexpected HTTP')):
            rows, state = scan_public_inventory(page, 'mercari', observed_at=datetime.now(timezone.utc), max_detail_pages=3)
        return rows, state, page

    def test_public_exact_metadata_enters_shared_pipeline_without_cost_invention(self):
        rows, state, page = self.scan()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].identity.name, 'Pikachu')
        self.assertEqual(rows[0].identity.language, 'ja')
        self.assertEqual(rows[0].evidence_type, 'FIXED_ASK')
        self.assertIsNone(rows[0].all_in_eur({'JPY':160}))
        self.assertEqual(len(page.calls), 2)
        self.assertFalse(state.complete)

    def test_unscoped_diagnostic_fields_cannot_prove_item_identity(self):
        rows, state, _ = self.scan(structured=False)
        self.assertEqual(rows, [])
        self.assertIn('LANGUAGE_UNPROVEN', state.detail)

    def test_japanese_title_is_not_language_proof(self):
        item=copy.deepcopy(ITEM); item['fields'].pop('Language'); item['title']=item['product']['name']='ピカチュウ PSA10'
        rows,state,_=self.scan(item)
        self.assertEqual(rows, [])
        self.assertIn('LANGUAGE_UNPROVEN', state.detail)

    def test_missing_axes_and_explicit_contradictions_reject(self):
        changes=[('Quantity','2'),('Grade','9'),('Card Number','026/165'),('Card Name','Charizard'),('Language','Korean')]
        for key,value in changes:
            item=copy.deepcopy(ITEM); item['fields'][key]=value
            self.assertEqual(self.scan(item)[0], [], (key,value))
        for key in ('Set','Quantity','Grading Company','Card Name'):
            item=copy.deepcopy(ITEM); item['fields'].pop(key)
            self.assertEqual(self.scan(item)[0], [], key)

    def test_ended_out_of_stock_or_malformed_price_never_sold(self):
        for availability in ('https://schema.org/OutOfStock','ENDED','WAITING_FOR_PAYMENT',''):
            item=copy.deepcopy(ITEM); item['product']['offers']['availability']=availability
            self.assertEqual(self.scan(item)[0], [])
        for price in ('NaN','inf','0','-1'):
            item=copy.deepcopy(ITEM); item['product']['offers']['price']=price
            self.assertEqual(self.scan(item)[0], [])

    def test_http_block_stops_before_item_inspection(self):
        rows,state,page=self.scan(status=403)
        self.assertEqual(rows, [])
        self.assertEqual(len(page.calls), 1)
        self.assertIn('HTTP_BLOCKED', state.detail)

    def test_conflicting_special_finishes_and_title_language_are_blocked(self):
        for extra in (' Master Ball Poke Ball', ' English', ' Lot of 2'):
            item=copy.deepcopy(ITEM); item['title'] += extra
            self.assertEqual(self.scan(item)[0], [])

    def test_unknown_title_claims_cannot_be_hidden_by_structured_fields(self):
        for extra in (' ex', ' Base Set', ' Charizard'):
            item=copy.deepcopy(ITEM); item['title'] += extra
            item['product']['name'] = item['title']
            self.assertEqual(self.scan(item)[0], [], extra)


if __name__ == '__main__': unittest.main()
