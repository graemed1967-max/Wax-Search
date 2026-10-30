"""Offline tests: parsers run on small sample pages; no network needed.  python -m unittest discover tests"""
import json, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import tracker as t

BANDCAMP = """<ol><li class="merch-grid-item" data-item-id="p-1"><a href="/merch/antropocene-wax-mage-12?foo=1">
<p class="title">ANTROPOCENE – Wax Mage 12"<br><span>x</span></p></a><span class="price">$25 USD</span></li>
<li class="merch-grid-item sold-out" data-item-id="p-2"><a href="/merch/b"><p class="title">Band – Wax Mage Handpours (ltd. edition of 25)</p></a><span class="price">$25</span></li>
<li class="merch-grid-item" data-item-id="p-3"><a href="/merch/c"><p class="title">Band – Black 12" Vinyl</p></a></li>
<li class="merch-grid-item" data-item-id="p-4"><a href="/merch/d"><p class="title">Band – Wax Mage Variant /25 Pre-order</p></a></li></ol>"""

WOO = """<ul><li class="product instock"><a href="/p/1"><h2 class="woocommerce-loop-product__title">Foo – WAX MAGE COLOR</h2></a><span class="price">$99</span></li>
<li class="product outofstock"><a href="/p/2"><h2 class="woocommerce-loop-product__title">Bar – Wax Mage Edition</h2></a></li>
<li class="product"><a href="/p/3"><h2 class="woocommerce-loop-product__title">Baz – Black LP</h2></a></li></ul>"""

FEED = """<?xml version="1.0"?><rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Willie Nelson – Country Music – Wax Mage Collabs Edition Pre-Sale</title><link>https://x/a</link>
<pubDate>Mon, 02 Feb 2026 10:00:00 +0000</pubDate><content:encoded><![CDATA[<p>/100 copies. THIS IS A PRE-SALE: Release date is Februrary 27, 2026.</p>]]></content:encoded></item>
<item><title>Orquesta – AMÉRICA! (Wax Mage Collab)</title><link>https://x/b</link><pubDate>Mon, 20 Oct 2026 10:00:00 +0000</pubDate>
<description>Limited to 200 copies</description></item>
<item><title>Unrelated pressing</title><link>https://x/c</link><description>nothing</description></item></channel></rss>"""

SHOP = {"resources": {"results": {"products": [
  {"title": "Foo – Wax Mage Variant", "url": "/products/foo?x=1", "available": True, "price": "30.00", "image": "https://i/1.jpg"},
  {"title": "Foo – Wax Mage Edition", "url": "/products/foo2", "available": False, "price": "70.00"},
  {"title": "Plain LP", "url": "/products/plain", "available": True}]}}}

class T(unittest.TestCase):
    def test_bandcamp(self):
        items = t.parse_bandcamp_merch(BANDCAMP, "x", "Lbl")
        self.assertEqual(len(items), 3)
        by = {i["title"].split(" – ")[0] + ("/pre" if "Pre-order" in i["title"] else ""): i for i in items}
        a = by["ANTROPOCENE"]
        self.assertEqual(a["status"], "in_stock")
        self.assertEqual(a["url"], "https://x.bandcamp.com/merch/antropocene-wax-mage-12")
        self.assertEqual(a["price"], "$25 USD")
        sold = by["Band"]
        self.assertEqual(sold["status"], "sold_out"); self.assertEqual(sold["edition_size"], 25)
        self.assertEqual(by["Band/pre"]["status"], "preorder")
    def test_woo(self):
        r = t.parse_woocommerce(WOO, "https://s.com", "Store")
        self.assertEqual([i["status"] for i in r], ["in_stock", "sold_out"])
        self.assertEqual(r[0]["url"], "https://s.com/p/1")
    def test_feed(self):
        r = t.parse_feed(FEED, "GG")
        self.assertEqual(len(r), 2)
        self.assertEqual(r[0]["release_date"], "2026-02-27"); self.assertEqual(r[0]["status"], "archive")
        self.assertEqual(r[0]["edition_size"], 100); self.assertEqual(r[0]["kind"], "Collab")
        self.assertEqual(r[1]["status"], "announced"); self.assertEqual(r[1]["edition_size"], 200)
    def test_shopify(self):
        r = t.parse_shopify_suggest(SHOP, "d.com", "Shop")
        self.assertEqual([i["status"] for i in r], ["in_stock", "sold_out"])
    def test_merge_events(self):
        a = t.make_item(title="A Wax Mage", url="https://u/1", seller="S", source="bandcamp", status="in_stock")
        items, ev = t.merge([], {"S": [dict(a)]}, {"S": {"bandcamp"}}, "T1")
        self.assertEqual([e["type"] for e in ev], ["new"])
        b = dict(a, status="sold_out")
        items, ev = t.merge(items, {"S": [b]}, {"S": {"bandcamp"}}, "T2")
        self.assertEqual((ev[0]["from"], ev[0]["to"]), ("in_stock", "sold_out"))
        self.assertEqual(items[0]["first_seen"], "T1")
        for n in range(3):  # vanishes from a healthy source
            items, ev = t.merge(items, {"S": []}, {"S": {"bandcamp"}}, f"T{3+n}")
        self.assertEqual(items[0]["status"], "removed")
    def test_no_removal_if_source_down(self):
        a = t.make_item(title="A Wax Mage", url="https://u/1", seller="S", source="bandcamp", status="in_stock")
        items, _ = t.merge([], {"S": [a]}, {"S": {"bandcamp"}}, "T1")
        for n in range(5):
            items, _ = t.merge(items, {}, {}, f"T{n}")
        self.assertEqual(items[0]["status"], "in_stock")
if __name__ == "__main__":
    unittest.main()
