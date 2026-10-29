#!/usr/bin/env python3
"""
collect.py — gather what the Morning Brief needs before Claude writes it.

Reads the latest portfolio (docs/data.json), looks through funds to the markets
they hold (exposures.json) and pulls:
  * overnight market closes and futures (Yahoo Finance chart API),
  * press releases and headlines from the allowlisted feeds in sources.json,
  * recent SEC filings for the US stocks held,
  * NAV-lag facts (fund priced days ago while its market has since moved),
  * the event calendar and research-radar topics.

Writes news_work/<edition>/context.json (gitignored: it holds third-party feed
text). No AI and no publishing happen here. Only domains on the allowlist are
contacted; blocked outlets are never fetched.

    python3 pipeline/news/collect.py                 # today's edition (Bangkok date)
    python3 pipeline/news/collect.py --date 2026-10-29 --since-hours 30
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DOCS = ROOT / "docs"
WORK = ROOT / "news_work"
try:
    BKK = ZoneInfo("Asia/Bangkok")
except Exception:  # slim cloud images may lack tzdata; Thailand has no DST
    BKK = dt.timezone(dt.timedelta(hours=7), "ICT")

SOURCES = json.loads((HERE / "sources.json").read_text())
EXPO = json.loads((HERE / "exposures.json").read_text())
CIK_CACHE = HERE / "cik_cache.json"

NS = {"rss1": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/",
      "atom": "http://www.w3.org/2005/Atom"}
MATERIAL = re.compile(r"\b(earnings|results|quarter|profit|revenue|guidance|forecast|outlook|dividend|"
                      r"buyback|merger|acquisition|acquire|takeover|offering|IPO|lawsuit|probe|"
                      r"investigation|fine|approval|approves|FDA|recall|downgrade|upgrade|rate|"
                      r"hike|cut|holds|raises|lowers|plunge|plunges|slump|surge|surges|soar|record|"
                      r"default|bankruptcy|tariff|sanction)\w*", re.I)
SEC_FORMS = ("8-K", "10-Q", "10-K", "6-K", "S-3", "S-3ASR", "SC 13D", "SC 13D/A")
ITEMS_8K = {"1.01": "material agreement", "1.05": "cybersecurity incident", "2.01": "acquisition or disposal",
            "2.02": "results of operations", "2.05": "restructuring costs", "3.01": "listing notice",
            "5.02": "director or officer change", "5.07": "shareholder vote", "7.01": "Reg FD disclosure",
            "8.01": "other events"}


# --------------------------------------------------------------------------- http
def get(url: str, ua: str | None = None, timeout: int = 20, accept: str = "*/*", news: bool = True) -> bytes:
    """news=True enforces the source policy; market-data calls (Yahoo prices) pass news=False."""
    if news and is_blocked(url):
        raise PermissionError(f"blocked outlet, not fetched: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": ua or SOURCES["user_agent"], "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(5_000_000)


def host_of(url: str) -> str:
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _in(host: str, domains) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def is_blocked(url: str) -> bool:
    return _in(host_of(url), SOURCES["blocked"]) or _in(host_of(url), SOURCES["never"])


def allowed_domains() -> list[str]:
    out = []
    for tier in SOURCES["tiers"].values():
        out += [d for d in tier["domains"] if d not in out]
    return out


def tier_of(url: str) -> str | None:
    h = host_of(url)
    for name, tier in SOURCES["tiers"].items():
        if _in(h, tier["domains"]):
            return name
    return None


# ---------------------------------------------------------------------- portfolio
def load_portfolio():
    data = json.loads((DOCS / "data.json").read_text())
    P = data["portfolio"]
    tot = P["total_value"] or 1
    pool = {}
    for h in P["holdings"]:
        k = (h["asset_type"], h["name"])
        g = pool.setdefault(k, {"name": h["name"], "type": h["asset_type"], "value": 0.0,
                                "theme": h.get("theme"), "geography": h.get("geography"),
                                "currency": h.get("currency") or "THB", "price_asof": "",
                                "day_px_pct": None})
        g["value"] += h.get("value_thb") or 0
        if (h.get("price_asof") or "") > g["price_asof"]:
            g["price_asof"] = h.get("price_asof") or ""
        if h.get("has_day"):
            g["day_px_pct"] = h.get("day_px_pct")
    holdings = []
    for g in pool.values():
        g["weight"] = round(g["value"] / tot, 6)
        g["group"] = group_of(g)
        ov = EXPO["holdings"].get(g["name"], {})
        if ov.get("set") or (g["type"] == "Equity" and g["geography"] == "Thailand" and g["theme"] != "Brokerage Cash"):
            g["set_symbol"] = ov.get("set") or g["name"]
        if ov.get("sec"):
            g["sec_ticker"] = g["name"]
        if ov.get("label"):
            g["label"] = ov["label"]
        del g["value"]
        holdings.append(g)
    holdings.sort(key=lambda x: -x["weight"])
    themes = {r["name"]: r["pct"] for r in P.get("by_theme", [])}
    ccy = {}  # per lot: one coin or fund can be held in THB at one custodian and USD at another
    for h in P["holdings"]:
        c = h.get("currency") or "THB"
        ccy[c] = ccy.get(c, 0) + (h.get("value_thb") or 0) / tot
    return data, P, holdings, themes, ccy


def group_of(h: dict) -> str | None:
    ov = EXPO["holdings"].get(h["name"], {})
    if ov.get("group"):
        return ov["group"]
    if h.get("theme") in EXPO["theme_to_group"]:
        return EXPO["theme_to_group"][h["theme"]]
    return EXPO["geography_to_group"].get(h.get("geography"))


def build_groups(holdings):
    groups = {}
    for h in holdings:
        if not h["group"]:
            continue
        g = groups.setdefault(h["group"], {"group": h["group"], "weight": 0.0, "holdings": []})
        g["weight"] += h["weight"]
        g["holdings"].append({"name": h["name"], "weight": round(h["weight"], 4), "type": h["type"]})
    for name, g in groups.items():
        g["weight"] = round(g["weight"], 4)
        g["keywords"] = EXPO["groups"].get(name, {}).get("keywords", [])
    return sorted(groups.values(), key=lambda g: -g["weight"])


# ------------------------------------------------------------------------ markets
def yahoo(symbol: str, rng: str = "1d", interval: str = "5m") -> dict:
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}"
           f"?range={rng}&interval={interval}")
    return json.loads(get(url, ua="Mozilla/5.0", news=False))["chart"]["result"][0]


def fmt_value(v: float, kind: str) -> str:
    if kind == "fx":
        return f"{v:,.2f}"
    if kind == "usd0":
        return f"${v:,.0f}"
    if kind == "yield":
        return f"{v:.2f}%"
    return f"{v:,.2f}"


def quote(spec: dict) -> dict:
    out = {"label": spec["label"], "symbol": spec["symbol"]}
    try:
        meta = yahoo(spec["symbol"])["meta"]
        last, prev = meta.get("regularMarketPrice"), meta.get("chartPreviousClose") or meta.get("previousClose")
        tz = dt.timezone(dt.timedelta(seconds=meta.get("gmtoffset") or 0))  # exchange time, no tzdata needed
        when = dt.datetime.fromtimestamp(meta.get("regularMarketTime") or 0, tz)
        out.update(value=last, value_text=fmt_value(last, spec.get("fmt", "index")), asof=when.isoformat(),
                   asof_date=when.date().isoformat())
        if prev and last is not None and prev != last:
            if spec.get("fmt") == "yield":
                bp = (last - prev) * 100
                out.update(change=bp, change_text=f"{'▲' if bp >= 0 else '▼'} {abs(bp):.0f} bp")
            else:
                ch = last / prev - 1
                out.update(change=ch, change_text=f"{'▲' if ch >= 0 else '▼'} {abs(ch) * 100:.2f}%")
            out["dir"] = "neutral" if spec.get("neutral") else ("pos" if out["change"] >= 0 else "neg")
        else:
            out.update(change=None, change_text="—", dir="neutral")
    except Exception as e:  # a failed quote must never stop the brief
        out.update(value=None, value_text="—", change=None, change_text="—", dir="neutral", error=str(e)[:120])
    return out


def exposure_for(spec: dict, groups: dict, themes: dict, ccy_weight: dict) -> float | None:
    e = spec.get("expo") or {}
    if "group" in e:
        return groups.get(e["group"], {}).get("weight")
    if "theme" in e:
        return themes.get(e["theme"])
    if "currency" in e:
        return ccy_weight.get(e["currency"])
    return None


def markets(groups_list, themes, ccy, now_bkk):
    groups = {g["group"]: g for g in groups_list}
    with ThreadPoolExecutor(8) as ex:
        tiles = list(ex.map(quote, EXPO["markets"]))
        early = list(ex.map(quote, EXPO["early"]))
    for spec, t in zip(EXPO["markets"], tiles):
        w = exposure_for(spec, groups, themes, ccy)
        t["exposure"] = round(w, 4) if w is not None else None
        t["exposure_label"] = spec.get("expo_label", "")
        t["window"] = spec.get("window", "close")
    order = sorted(tiles, key=lambda t: -(t["exposure"] or -1))
    # Asian cash indices only count as "early trade" once their session has opened today
    keep = []
    for spec, q in zip(EXPO["early"], early):
        if q.get("change") is None:
            continue
        if spec.get("asia") and q.get("asof_date") != now_bkk.date().isoformat():
            continue
        keep.append(q)
    return {"tiles": order, "early": keep, "fetched_at": now_bkk.isoformat(timespec="minutes")}


def nav_lags(holdings, now_bkk):
    """Funds whose dashboard NAV is older than their market's latest close."""
    proxies = {}
    for h in holdings:
        p = EXPO["holdings"].get(h["name"], {}).get("proxy")
        if p and h["type"] in ("MF", "Unit Trust") and h["weight"] >= 0.01 and h["price_asof"]:
            proxies.setdefault(p, []).append(h)
    out = []
    for sym, funds in proxies.items():
        try:
            r = yahoo(sym, "3mo", "1d")
            tz = dt.timezone(dt.timedelta(seconds=r["meta"].get("gmtoffset") or 0))
            closes = [(dt.datetime.fromtimestamp(t, tz).date().isoformat(), c)
                      for t, c in zip(r["timestamp"], r["indicators"]["quote"][0]["close"]) if c]
        except Exception:
            continue
        if len(closes) < 2:
            continue
        last_date, last = closes[-1]
        for h in funds:
            base = [c for d, c in closes if d <= h["price_asof"]]
            if not base or last_date <= h["price_asof"]:
                continue
            move = last / base[-1] - 1
            if abs(move) >= 0.01:
                out.append({"fund": h["name"], "weight": round(h["weight"], 4), "nav_date": h["price_asof"],
                            "proxy_symbol": sym, "proxy_last_date": last_date, "proxy_move_since_nav": round(move, 4)})
    return sorted(out, key=lambda x: -x["weight"])


# -------------------------------------------------------------------------- feeds
def _text(el, *paths):
    for p in paths:
        x = el.find(p, NS)
        if x is not None:
            if x.text and x.text.strip():
                return x.text.strip()
            if x.get("href"):
                return x.get("href")
    return ""


def _when(s: str):
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def _clean(s: str, n: int = 360) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


def parse_feed(body: bytes):
    root = ET.fromstring(body)
    items = root.findall(".//item") or root.findall(".//rss1:item", NS) or root.findall(".//atom:entry", NS)
    out = []
    for it in items:
        title = _text(it, "title", "rss1:title", "atom:title")
        link = _text(it, "link", "rss1:link", "atom:link")
        when = _when(_text(it, "pubDate", "dc:date", "rss1:date", "atom:published", "atom:updated"))
        summary = _text(it, "description", "rss1:description", "atom:summary", "atom:content")
        if title and link:
            out.append({"title": _clean(title, 200), "link": link.strip(), "published": when,
                        "summary": _clean(summary)})
    return out


def fetch_feed(feed):
    try:
        if is_blocked(feed["url"]) or not tier_of(feed["url"]):
            return feed, [], "not on the allowlist"
        return feed, parse_feed(get(feed["url"], accept="application/rss+xml, application/xml, text/xml, */*")), None
    except Exception as e:
        return feed, [], f"{type(e).__name__}: {str(e)[:80]}"


def _kw(kw: str):
    flags = 0 if any(c.isupper() for c in kw) else re.I
    return re.compile(r"(?<![\w-])" + re.escape(kw) + r"(?![\w-])", flags)


def build_matchers(holdings, groups_list):
    gm = {g["group"]: [_kw(k) for k in g["keywords"]] for g in groups_list}
    hm = []
    for h in holdings:
        kws = list(EXPO["holdings"].get(h["name"], {}).get("keywords", []))
        if h.get("set_symbol") and len(h["name"]) >= 4 and h["name"] not in ("WORK", "HUMAN"):
            kws.append(h["name"])
        if kws:
            hm.append((h, [_kw(k) for k in kws]))
    return gm, hm


def score_items(items, holdings, groups_list, now_utc):
    gw = {g["group"]: g["weight"] for g in groups_list}
    gm, hm = build_matchers(holdings, groups_list)
    for it in items:
        text = f"{it['title']} {it['summary']}"
        groups = [g for g, pats in gm.items() if any(p.search(text) for p in pats)]
        hits = [h for h, pats in hm if any(p.search(text) for p in pats)]
        if not groups and it.get("feed_group"):  # a regional feed's own market, only when nothing else matched
            groups.append(it["feed_group"])
        base = 0.6 * sum(gw.get(g, 0) for g in groups) + sum(max(h["weight"], 0.003) for h in hits)
        mult = 1.5 if MATERIAL.search(it["title"]) else 1.0
        mult *= {"primary": 1.3, "major": 1.0, "regional": 0.9}.get(it["tier"], 0.8)
        if it["published"]:
            age = (now_utc - it["published"]).total_seconds() / 3600
            mult *= 1.0 if age <= 12 else 0.85 if age <= 24 else 0.7
        it["groups"] = groups
        it["holdings"] = [h["name"] for h in hits]
        it["score"] = round(base * mult, 4)
    return items


def collect_feeds(holdings, groups_list, since_utc, now_utc):
    status, items, seen = [], [], set()
    with ThreadPoolExecutor(12) as ex:
        results = list(ex.map(fetch_feed, SOURCES["feeds"]))
    for feed, rows, err in results:
        status.append({"name": feed["name"], "ok": err is None, "items": len(rows), "error": err})
        undated = 0
        for r in rows:
            if r["link"] in seen or is_blocked(r["link"]):
                continue
            if r["published"] and r["published"] > now_utc + dt.timedelta(minutes=15):
                r["published"] = None  # some feeds label local time as UTC; a future stamp is unknowable
            if r["published"] is None:
                undated += 1
                if undated > 12:
                    continue
            elif r["published"] < since_utc:
                continue
            seen.add(r["link"])
            r.update(outlet=SOURCES["outlet_names"].get(host_of(r["link"]), feed["name"]), feed=feed["name"],
                     tier=tier_of(r["link"]) or tier_of(feed["url"]), feed_group=feed.get("group"))
            items.append(r)
    score_items(items, holdings, groups_list, now_utc)
    relevant = [i for i in items if i["score"] > 0 or i["tier"] == "primary"]
    relevant.sort(key=lambda i: -i["score"])
    keep = relevant[:90]
    for i in keep:
        i["published"] = i["published"].astimezone(BKK).isoformat(timespec="minutes") if i["published"] else None
        i.pop("feed_group", None)
    return keep, status, len(items)


# ---------------------------------------------------------------------------- SEC
def cik_for(ticker: str, cache: dict):
    if ticker in cache:
        return cache[ticker]
    url = "https://efts.sec.gov/LATEST/search-index?keysTyped=" + urllib.parse.quote(ticker)
    cik = None
    try:
        hits = json.loads(get(url, ua=SOURCES["sec_user_agent"]))["hits"]["hits"]
        for hit in hits:
            m = re.search(r"\(([^)]*)\)\s*$", hit["_source"].get("entity", ""))
            if m and ticker in [t.strip() for t in m.group(1).split(",")]:
                cik = int(hit["_id"])
                break
    except Exception:
        return None
    if cik:  # cache hits only, so a ticker the search missed is retried next run
        cache[ticker] = cik
    return cik


def sec_filings(holdings, since_date: dt.date):
    cache = json.loads(CIK_CACHE.read_text()) if CIK_CACHE.exists() else {}
    tickers = [h for h in holdings if h.get("sec_ticker")]
    out = []
    for h in tickers:
        cik = cik_for(h["sec_ticker"], cache)
        if not cik:
            continue
        try:
            sub = json.loads(get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", ua=SOURCES["sec_user_agent"]))
        except Exception:
            continue
        r = sub["filings"]["recent"]
        for i, form in enumerate(r["form"]):
            if r["filingDate"][i] < since_date.isoformat():
                break
            if form not in SEC_FORMS and not form.startswith("424B"):
                continue
            acc = r["accessionNumber"][i]
            items = [ITEMS_8K.get(x.strip(), x.strip()) for x in (r.get("items", [""] * (i + 1))[i] or "").split(",") if x.strip() and x.strip() != "9.01"]
            out.append({"ticker": h["sec_ticker"], "weight": round(h["weight"], 4), "form": form,
                        "filed": r["filingDate"][i], "description": r["primaryDocDescription"][i] or form,
                        "items": items,
                        "url": f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{r['primaryDocument'][i]}"})
    CIK_CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=1) + "\n")
    return out


# ------------------------------------------------------------------ calendar/radar
def calendar(edition: dt.date, horizon_days: int = 45):
    events = json.loads((HERE / "calendar.json").read_text())["events"]
    end = edition + dt.timedelta(days=horizon_days)
    keep = [e for e in events if edition.isoformat() <= e["date"] <= end.isoformat()]
    if edition.month in (10, 11, 12):
        keep.append({"date": f"{edition.year}-12-31", "date_label": "Late Dec", "time_bkt": "",
                     "title": f"Last chance for {edition.year} RMF and Thai ESG purchases",
                     "detail": "Cut-off dates vary by fund house", "kind": "tax", "tab": "Tax & Lots", "source": None})
    return sorted(keep, key=lambda e: (e["date"], e.get("time_bkt") or "99"))


def radar(items):
    topics = json.loads((HERE / "radar.json").read_text())["topics"]
    out = []
    for t in topics:
        pats = [_kw(k) for k in t["keywords"]]
        hits = [{"title": i["title"], "link": i["link"], "outlet": i["outlet"], "published": i["published"]}
                for i in items if any(p.search(i["title"] + " " + i["summary"]) for p in pats)]
        out.append({**t, "feed_hits": hits[:8]})
    return out


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="edition date YYYY-MM-DD (default: today in Bangkok)")
    ap.add_argument("--since-hours", type=float, help="news window length (default: since 06:00 the previous day; Monday covers the weekend)")
    args = ap.parse_args()

    now_bkk = dt.datetime.now(BKK)
    edition = dt.date.fromisoformat(args.date) if args.date else now_bkk.date()
    if args.since_hours:
        since = now_bkk - dt.timedelta(hours=args.since_hours)
    else:
        back = 3 if edition.weekday() == 0 else 1
        since = dt.datetime.combine(edition - dt.timedelta(days=back), dt.time(6, 0), BKK)
    now_utc, since_utc = now_bkk.astimezone(dt.timezone.utc), since.astimezone(dt.timezone.utc)

    data, P, holdings, themes, ccy = load_portfolio()
    groups_list = build_groups(holdings)
    feed_items, feed_status, scanned = collect_feeds(holdings, groups_list, since_utc, now_utc)
    ctx = {
        "edition_date": edition.isoformat(),
        "collected_at": now_bkk.isoformat(timespec="minutes"),
        "window": {"from": since.isoformat(timespec="minutes"), "to": now_bkk.isoformat(timespec="minutes")},
        "portfolio": {"as_of": P["as_of"], "generated_at": data.get("generated_at"), "positions": len(holdings),
                      "total_value_thb": round(P["total_value"])},
        "groups": groups_list,
        "holdings": [h for h in holdings if h["weight"] > 0],
        "markets": markets(groups_list, themes, ccy, now_bkk),
        "nav_lags": nav_lags(holdings, now_bkk),
        "feed_items": feed_items,
        "feed_status": feed_status,
        "filings": sec_filings(holdings, since.date() - dt.timedelta(days=1)),
        "calendar": calendar(edition),
        "radar": radar(feed_items),
        "allowed_domains": allowed_domains(),
        "blocked_domains": SOURCES["blocked"] + SOURCES["never"],
    }
    out_dir = WORK / edition.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "context.json"
    path.write_text(json.dumps(ctx, indent=1, ensure_ascii=False))

    bad = [f["name"] for f in feed_status if not f["ok"]]
    print(f"context: {path}")
    print(f"  edition {edition} · window {since:%a %d %b %H:%M} → now · portfolio as of {P['as_of']}")
    print("  top groups: " + ", ".join(f"{g['group']} {g['weight'] * 100:.1f}%" for g in groups_list[:6]))
    print(f"  feeds: {len(feed_status) - len(bad)}/{len(feed_status)} ok, {scanned} items in window, "
          f"{len(feed_items)} kept" + (f" · failed: {', '.join(bad)}" if bad else ""))
    print(f"  markets: " + ", ".join(f"{t['label']} {t['change_text']}" for t in ctx["markets"]["tiles"]))
    print(f"  SEC filings: {len(ctx['filings'])} · NAV lags: {len(ctx['nav_lags'])} · events: {len(ctx['calendar'])}")


if __name__ == "__main__":
    sys.exit(main())
