#!/usr/bin/env python3
"""Wax Mage vinyl tracker.

Scans the sources in sources.json for Wax Mage pressings, works out whether each
one is in stock / pre-order / sold out / just announced, remembers what it has
seen, and writes data.json + data.js for index.html to display.

    pip install requests beautifulsoup4
    python tracker.py

Run it on a schedule (cron, Task Scheduler, or the included GitHub Action).
"""
import datetime as dt
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
CFG_PATH = ROOT / "sources.json"
DATA_PATH = ROOT / "data.json"
JS_PATH = ROOT / "data.js"

UA = "Mozilla/5.0 (compatible; WaxMageTracker/1.0; personal hobby tracker)"
DELAY = 1.0          # seconds between requests, to be polite
TIMEOUT = 25
REMOVE_AFTER = 3     # runs an item can be missing from a healthy source before it is marked removed
ANNOUNCE_WINDOW_DAYS = 120

KEY_RE = re.compile(r"wax\s*mage", re.I)
SOLD_RE = re.compile(r"sold[\s-]*out|out of stock|unavailable|currently unavailable", re.I)
PRE_RE = re.compile(r"pre[\s-]*order|pre[\s-]*sale|presale", re.I)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept-Language": "en"})


# --------------------------------------------------------------------------- helpers
def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def get(url, **kw):
    time.sleep(DELAY)
    r = session.get(url, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def item_id(url, title):
    base = (url or "").split("#")[0].rstrip("/").lower() or title.lower()
    return hashlib.sha1(base.encode()).hexdigest()[:12]


def edition_size(text):
    for pat in (r"(?:limited\s+(?:edition\s+)?(?:to|of)|edition of|ltd\.?\s+edition of|only)\s*(\d{1,4})\b",
                r"(?<![\d.])/\s?(\d{2,4})\b"):
        m = re.search(pat, text, re.I)
        if m:
            n = int(m.group(1))
            if 1 < n <= 2000:
                return n
    return None


def classify_kind(text):
    t = text.lower()
    if "collab" in t:
        return "Collab"
    if "exclusive" in t:
        return "Exclusive"
    if "edition" in t or re.search(r"/\s?25\b", t) or "wax mage variant" in t:
        return "Edition"
    return "Variant"


def parse_release_date(text):
    m = re.search(r"releas\w*\s*(?:date)?\s*(?:is|:|on)?\s*([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d{2})",
                  text, re.I)
    if not m:
        return None
    mon = MONTHS.get(m.group(1)[:3].lower())
    if not mon:
        return None
    try:
        return dt.date(int(m.group(3)), mon, int(m.group(2))).isoformat()
    except ValueError:
        return None


def stock_status(text):
    if SOLD_RE.search(text):
        return "sold_out"
    if PRE_RE.search(text):
        return "preorder"
    return "in_stock"


def make_item(*, title, url, seller, source, status, price="", image="", note="",
              release_date=None, size=None, kind=None, posted=None):
    blob = f"{title} {note}"
    return {
        "id": item_id(url, title),
        "title": clean(title),
        "url": url,
        "seller": seller,
        "source": source,
        "status": status,
        "price": clean(price),
        "image": image or "",
        "note": clean(note)[:400],
        "release_date": release_date,
        "edition_size": size if size is not None else edition_size(blob),
        "kind": kind or classify_kind(blob),
        "posted": posted,
    }


# --------------------------------------------------------------------------- parsers
def parse_feed(xml_text, name):
    """RSS feed of announcements -> items with status 'announced' (or 'archive' if old)."""
    items = []
    root = ET.fromstring(xml_text)
    ns = {"c": "http://purl.org/rss/1.0/modules/content/"}
    today = dt.date.today()
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = clean(it.findtext("link"))
        body_html = it.findtext("c:encoded", namespaces=ns) or it.findtext("description") or ""
        body = clean(BeautifulSoup(body_html, "html.parser").get_text(" "))
        if not (KEY_RE.search(title) or KEY_RE.search(body)):
            continue
        posted = None
        pub = it.findtext("pubDate")
        if pub:
            try:
                posted = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").date()
            except ValueError:
                pass
        rel = parse_release_date(body)
        recent = posted is not None and (today - posted).days <= ANNOUNCE_WINDOW_DAYS
        upcoming = rel is not None and dt.date.fromisoformat(rel) >= today
        status = "announced" if (recent or upcoming) else "archive"
        note = "Announcement post. Check the post for the purchase link and live stock."
        if PRE_RE.search(title + " " + body[:600]):
            note = "Pre-sale announcement. Check the post for the purchase link and live stock."
        items.append(make_item(title=title, url=link, seller=name, source="feed", status=status,
                               note=note, release_date=rel,
                               size=edition_size(title + " " + body[:800]),
                               kind=classify_kind(title + " " + body[:400]),
                               posted=posted.isoformat() if posted else None))
    return items


def parse_woocommerce(html, base, name):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    cards = soup.select("li.product, article.product, div.product")
    for c in cards:
        a = c.select_one("a[href]")
        t = c.select_one(".woocommerce-loop-product__title, h2, h3")
        title = clean(t.get_text(" ")) if t else ""
        if not title or not KEY_RE.search(title + " " + (a.get("href", "") if a else "")):
            continue
        classes = " ".join(c.get("class", []))
        text = clean(c.get_text(" "))
        status = "sold_out" if ("outofstock" in classes or SOLD_RE.search(text) or SOLD_RE.search(title)) \
            else stock_status(text)
        price = c.select_one(".price")
        img = c.select_one("img")
        out.append(make_item(title=title, url=urljoin(base, a["href"]) if a else base, seller=name,
                             source="woocommerce", status=status,
                             price=price.get_text(" ") if price else "",
                             image=urljoin(base, img.get("src", "")) if img else ""))
    return out


def parse_bandcamp_merch(html, sub, name):
    soup = BeautifulSoup(html, "html.parser")
    base = f"https://{sub}.bandcamp.com"
    out = []
    for li in soup.select("li.merch-grid-item, li[data-item-id]"):
        a = li.select_one("a[href]")
        t = li.select_one("p.title") or li.select_one(".title")
        raw = t.get_text("\n") if t else ""
        title = clean(raw.split("\n")[0]) or clean(li.get_text(" "))[:120]
        text = clean(li.get_text(" "))
        if not KEY_RE.search(title):
            continue
        classes = " ".join(li.get("class", []))
        status = "sold_out" if ("sold" in classes.lower() or SOLD_RE.search(text)) else stock_status(text)
        price = li.select_one(".price")
        img = li.select_one("img")
        src = (img.get("src") or img.get("data-original") or "") if img else ""
        out.append(make_item(title=title, url=urljoin(base, a["href"]).split("?")[0] if a else base + "/merch",
                             seller=name, source="bandcamp", status=status,
                             price=price.get_text(" ") if price else "", image=src))
    if out:
        return out
    # Fallback: JSON embedded in the page
    holder = soup.select_one("[data-client-items]")
    if holder:
        try:
            for j in json.loads(holder["data-client-items"]):
                title = clean(j.get("title", ""))
                if not KEY_RE.search(title):
                    continue
                url = urljoin(base, j.get("page_url") or j.get("url") or "/merch")
                sold = j.get("sold_out") or j.get("is_sold_out")
                price = ""
                if j.get("price") is not None:
                    price = f"{j.get('currency', '')} {j['price']}".strip()
                out.append(make_item(title=title, url=url.split("?")[0], seller=name, source="bandcamp",
                                     status="sold_out" if sold else stock_status(json.dumps(j)),
                                     price=price))
        except (ValueError, TypeError):
            pass
    return out


def parse_shopify_suggest(payload, domain, name):
    out = []
    products = (((payload or {}).get("resources") or {}).get("results") or {}).get("products") or []
    for p in products:
        title = clean(p.get("title", ""))
        tags = " ".join(p.get("tags") or []) if isinstance(p.get("tags"), list) else str(p.get("tags") or "")
        if not KEY_RE.search(title + " " + tags):
            continue
        status = "in_stock" if p.get("available") else "sold_out"
        if status == "in_stock" and PRE_RE.search(title + " " + tags):
            status = "preorder"
        out.append(make_item(title=title, url=urljoin(f"https://{domain}", p.get("url", "")).split("?")[0],
                             seller=name, source="shopify", status=status,
                             price=str(p.get("price") or ""), image=p.get("image") or ""))
    return out


def parse_bandcamp_search(html):
    soup = BeautifulSoup(html, "html.parser")
    subs = []
    for li in soup.select("li.searchresult"):
        a = li.select_one(".itemurl") or li.select_one("a[href]")
        href = (a.get_text() if a and a.name != "a" else (a.get("href") if a else "")) or ""
        host = urlparse(href.strip()).netloc
        if host.endswith(".bandcamp.com"):
            subs.append(host.split(".")[0])
    return subs


# --------------------------------------------------------------------------- fetchers
def fetch_source(src, kw):
    t = src["type"]
    if t == "feed":
        return parse_feed(get(src["url"]).text, src["name"])
    if t == "woocommerce":
        url = f"{src['base']}/?s={quote_plus(kw)}&post_type=product"
        return parse_woocommerce(get(url).text, src["base"], src["name"])
    if t == "bandcamp":
        url = f"https://{src['sub']}.bandcamp.com/merch"
        return parse_bandcamp_merch(get(url).text, src["sub"], src["name"])
    if t == "shopify":
        url = (f"https://{src['domain']}/search/suggest.json?q={quote_plus(kw)}"
               "&resources[type]=product&resources[limit]=20")
        return parse_shopify_suggest(get(url).json(), src["domain"], src["name"])
    raise ValueError(f"unknown source type {t}")


def discover_bandcamp(kw, known, limit):
    found = []
    for itype in ("a", "t"):
        try:
            html = get(f"https://bandcamp.com/search?q={quote_plus(kw)}&item_type={itype}").text
        except Exception as e:  # noqa: BLE001
            print(f"  discovery ({itype}) failed: {e}")
            continue
        for sub in parse_bandcamp_search(html):
            if sub not in known and sub not in found:
                found.append(sub)
    return found[:limit]


# --------------------------------------------------------------------------- merge
def merge(old_items, found_by_source, ok_sources, ts):
    """Update the item store; returns (items, events)."""
    items = {i["id"]: i for i in old_items}
    events = []
    seen_ids = set()
    for src_name, found in found_by_source.items():
        for it in found:
            seen_ids.add(it["id"])
            old = items.get(it["id"])
            if old is None:
                it.update(first_seen=ts, last_seen=ts, last_changed=ts, missing=0)
                items[it["id"]] = it
                events.append({"ts": ts, "type": "new", "id": it["id"], "title": it["title"],
                               "seller": it["seller"], "status": it["status"], "url": it["url"]})
            else:
                changed = old["status"] != it["status"]
                if changed:
                    events.append({"ts": ts, "type": "status", "id": old["id"], "title": it["title"],
                                   "seller": it["seller"], "from": old["status"], "to": it["status"],
                                   "url": it["url"]})
                first = old.get("first_seen", ts)
                old.update({k: v for k, v in it.items() if v not in (None, "")})
                old.update(first_seen=first, last_seen=ts, missing=0,
                           last_changed=ts if changed else old.get("last_changed", first))
    # items from healthy sources that vanished
    for it in items.values():
        if it["id"] in seen_ids or it["source"] not in ok_sources.get(it["seller"], set()):
            continue
        if it["source"] == "seed":
            continue
        it["missing"] = it.get("missing", 0) + 1
        if it["missing"] >= REMOVE_AFTER and it["status"] != "removed":
            events.append({"ts": ts, "type": "status", "id": it["id"], "title": it["title"],
                           "seller": it["seller"], "from": it["status"], "to": "removed", "url": it["url"]})
            it["status"] = "removed"
            it["last_changed"] = ts
    return list(items.values()), events


# --------------------------------------------------------------------------- main
def main():
    cfg = json.loads(CFG_PATH.read_text())
    kw = cfg.get("keyword", "wax mage")
    store = json.loads(DATA_PATH.read_text()) if DATA_PATH.exists() else {}
    ts = now_iso()

    sources = list(cfg["sources"])
    known_subs = {s["sub"] for s in sources if s["type"] == "bandcamp"}
    discovered = list(store.get("discovered_bandcamp", []))
    for sub in discovered:
        if sub not in known_subs:
            sources.append({"type": "bandcamp", "name": f"{sub} (auto-discovered)", "sub": sub})
            known_subs.add(sub)

    disc = cfg.get("bandcamp_discovery", {})
    if disc.get("enabled"):
        print("Discovering Bandcamp labels...")
        for sub in discover_bandcamp(kw, known_subs, disc.get("max_new_per_run", 15)):
            print("  +", sub)
            discovered.append(sub)
            sources.append({"type": "bandcamp", "name": f"{sub} (auto-discovered)", "sub": sub})

    found_by_source, status_rows, ok = {}, [], {}
    for src in sources:
        name = src["name"]
        print(f"Scanning {name} ...")
        try:
            found = fetch_source(src, kw)
            found_by_source[name] = found
            ok.setdefault(name, set()).add(src["type"])
            status_rows.append({"name": name, "type": src["type"], "ok": True, "count": len(found), "error": ""})
            print(f"  {len(found)} Wax Mage item(s)")
        except Exception as e:  # noqa: BLE001
            status_rows.append({"name": name, "type": src["type"], "ok": False, "count": 0, "error": str(e)[:200]})
            print(f"  FAILED: {e}")

    items, events = merge(store.get("items", []), found_by_source, ok, ts)
    all_events = (events + store.get("events", []))[:500]

    out = {
        "generated": ts,
        "keyword": kw,
        "sources": status_rows,
        "search_links": cfg.get("search_links", []),
        "discovered_bandcamp": discovered,
        "items": sorted(items, key=lambda i: i.get("first_seen", ""), reverse=True),
        "events": all_events,
    }
    healthy = sum(1 for r in status_rows if r["ok"])
    if healthy == 0:
        # Don't overwrite good data (or claim a fresh scan) when we are simply offline.
        print("No source could be reached, so nothing was saved. Check your internet connection.", file=sys.stderr)
        return 1
    # Lines for a phone notification: new listings and restocks (skipped on the very first scan).
    lines = []
    if store.get("generated"):
        for e in events:
            if e["type"] == "new" and e["status"] in ("in_stock", "preorder", "announced"):
                lines.append(f"NEW ({e['status'].replace('_', ' ')}): {e['title']} - {e['seller']}")
            elif e["type"] == "status" and e["to"] in ("in_stock", "preorder"):
                lines.append(f"{e['to'].replace('_', ' ').upper()}: {e['title']} - {e['seller']}")
    (ROOT / "notify.txt").write_text("\n".join(lines[:15]) + ("\n" if lines else ""))

    DATA_PATH.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    JS_PATH.write_text("window.WAXMAGE_DATA = " + json.dumps(out, ensure_ascii=False) + ";\n")
    print(f"\nDone: {len(items)} items tracked, {len(events)} change(s) this run, "
          f"{healthy}/{len(status_rows)} sources reachable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
