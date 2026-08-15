from __future__ import annotations
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import japan_edge_hunter as j
NOW=datetime(2026,8,16,tzinfo=timezone.utc)
def row(i="x",p=100,d=5,language="Japanese",grade="10",variety=""):
    return {"id":i,"status":"SOLD","soldAt":(NOW-timedelta(days=d)).isoformat().replace("+00:00","Z"),"priceInCents":int(p*100),"item":{"gradingCompany":"PSA","grade":grade,"collectible":{"category":"Pokemon","type":"CARDS","language":language,"set":"Mega Dream ex","reference":"#223/193","yearOfDistribution":2025,"edition":"Unlimited","attribute":"","variety":variety,"rarity":"Mega Attack Rare","character":{"englishName":"Mega Charizard X ex"}}}}
def exact_ask(price=9500,text="日本版"):
    return j.Ask("mercari","https://jp.mercari.com/item/m1","Mega Charizard X ex 223/193 PSA10 Japanese Mega Dream ex",price,text)
class Tests(unittest.TestCase):
    def test_seed_requires_proven_sold_japanese_psa10(self):
        self.assertIsNotNone(j.sold_from_gcc(row()));self.assertIsNone(j.sold_from_gcc(row(language="English")));self.assertIsNone(j.sold_from_gcc(row(grade="9")))
        x=row();x["status"]="ON_SALE";self.assertIsNone(j.sold_from_gcc(x))
    def test_identity_separates_microvariant_and_language(self):
        a=j.sold_from_gcc(row()).identity;b=j.sold_from_gcc(row(variety="MA-INCORRECT TEXTURE")).identity
        self.assertNotEqual(a.key,b.key);self.assertNotEqual(a.key,j.Identity(**{**a.__dict__,"language":"English"}).key)
    def test_reference_needs_multiple_exact_sold(self):
        one=j.sold_from_gcc(row("a"));self.assertEqual(j.references([one],NOW),[])
        vals=[j.sold_from_gcc(row("a",90,2)),j.sold_from_gcc(row("b",100,3)),j.sold_from_gcc(row("c",110,4))];r=j.references(vals,NOW)[0]
        self.assertEqual(r.fair_eur,100);self.assertEqual(r.evidence,"GCC_EXACT_SOLD_RECENT")
    def test_listing_identity_fail_closed(self):
        ident=j.sold_from_gcc(row()).identity;self.assertTrue(j.identity_check(exact_ask(),ident)[0])
        self.assertEqual(j.identity_check(j.Ask("m","u","Mega Charizard X ex 222/193 PSA10 Japanese Mega Dream ex",1,"日本版"),ident)[1],"collector_number_unproven")
        self.assertEqual(j.identity_check(j.Ask("m","u","Mega Charizard X ex 223/193 PSA10 Mega Dream ex",1,""),ident)[1],"language_unproven")
    def test_incorrect_texture_cannot_match_standard(self):
        ident=j.sold_from_gcc(row(variety="MA-INCORRECT TEXTURE")).identity;self.assertEqual(j.identity_check(exact_ask(),ident)[1],"microvariant_unproven")
    def test_auction_and_multi_item_are_rejected(self):
        ident=j.sold_from_gcc(row()).identity
        self.assertEqual(j.identity_check(j.Ask("m","u",exact_ask().title,5000,"現在 オークション 日本版"),ident)[1],"ongoing_auction")
        self.assertEqual(j.identity_check(j.Ask("m","u",exact_ask().title+" 2枚セット販売",5000,"日本版"),ident)[1],"multi_item_listing")
    def test_yen_parser_requires_currency(self):
        self.assertEqual(j.parse_yen("PSA10 223/193 ¥14,800"),14800);self.assertEqual(j.parse_yen("14,800円"),14800);self.assertIsNone(j.parse_yen("PSA10 223/193 2025"))
    def test_discount_gate_after_logistics_buffer(self):
        ref=j.references([j.sold_from_gcc(row("a",100,2)),j.sold_from_gcc(row("b",100,3))],NOW)[0]
        op=j.evaluate(exact_ask(9500),ref,Decimal("200"),Decimal("0.95"),30,500,10);self.assertIsNotNone(op);self.assertEqual(op.landed_eur,55);self.assertEqual(op.discount_pct,45)
        self.assertIsNone(j.evaluate(exact_ask(13000),ref,Decimal("200"),None,30,500,10))
    def test_search_parser_drops_auction(self):
        ident=j.sold_from_gcc(row()).identity
        class P:
            def goto(self,*a,**k):pass
            def wait_for_timeout(self,*a,**k):pass
            def evaluate(self,*a,**k):return [{"href":"https://jp.mercari.com/item/mfixed?x=1","anchor":exact_ask().title,"text":exact_ask().title+" ¥12,000"},{"href":"https://jp.mercari.com/item/mauction","anchor":"x","text":"現在 ¥5,000 オークション"}]
        x=j.collect(P(),j.PROVIDERS[0],ident);self.assertEqual(len(x),1);self.assertEqual(x[0].url,"https://jp.mercari.com/item/mfixed")
if __name__=="__main__":unittest.main()
