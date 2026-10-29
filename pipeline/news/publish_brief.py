#!/usr/bin/env python3
"""
publish_brief.py — turn a checked draft into the site's docs/brief.json.

    python3 pipeline/news/publish_brief.py news_work/<date>/draft.json [--status preview]

Runs check_brief first and refuses to publish on errors. Then adds everything
the page needs that the draft shouldn't hand-type: exposure percentages from
the holdings named, outlet tiers and paywall marks, "Find on Reuters / FT"
search links, "Check on SET" links for Thai stocks, market tiles, the calendar,
quiet holdings and run stats. Writes docs/brief.json, an archive copy in
docs/briefs/<date>.json and docs/briefs/index.json. New verified events are
kept in calendar.json for later editions. Committing and pushing is
scripts/morning_brief.sh's job.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DOCS = ROOT / "docs"
try:
    BKK = ZoneInfo("Asia/Bangkok")
except Exception:  # slim cloud images may lack tzdata; Thailand has no DST
    BKK = dt.timezone(dt.timedelta(hours=7), "ICT")
sys.path.insert(0, str(HERE))
import check_brief  # noqa: E402

SOURCES = json.loads((HERE / "sources.json").read_text())
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


class Book:
    """Holding and group weights from the day's context, for exposure maths."""

    def __init__(self, ctx):
        self.h = {h["name"]: h for h in ctx["holdings"]}
        self.g = {g["group"]: g["weight"] for g in ctx["groups"]}
        self.members = {g["group"]: [x["name"] for x in g["holdings"]] for g in ctx["groups"]}

    def covered(self, item):
        """Holdings an item speaks for: the ones it names, or its whole market when it names none."""
        return item.get("holdings") or self.members.get(item.get("group"), [])

    def event_label(self, names, pct, group):
        chips = self.chips(names)
        if len(chips) <= 2:
            return ", ".join(f"{c['name']} {c['weight']}%" for c in chips)
        groups = {self.h[c["name"]].get("group") for c in chips}
        return f"{groups.pop()} {pct}%" if len(groups) == 1 else f"{len(chips)} holdings {pct}%"

    def exposure(self, item):
        names = list(dict.fromkeys(item.get("holdings") or []))
        if names:
            return round(sum(self.h[n]["weight"] for n in names if n in self.h) * 100, 1), names
        return round(self.g.get(item.get("group"), 0) * 100, 1), []

    def chips(self, names):
        return [{"name": n, "weight": round(self.h[n]["weight"] * 100, 1)} for n in
                sorted(names, key=lambda n: -self.h[n]["weight"]) if n in self.h]

    def set_links(self, names):
        return [{"symbol": self.h[n]["set_symbol"], "url": SOURCES["set_news_template"].format(symbol=self.h[n]["set_symbol"])}
                for n in names if n in self.h and self.h[n].get("set_symbol")]


def source_list(srcs):
    out = []
    for s in srcs or []:
        h = check_brief.host_of(s["url"])
        out.append({"name": s.get("name") or SOURCES["outlet_names"].get(h, h), "url": s["url"],
                    "tier": check_brief.tier_of(s["url"]), "primary": bool(s.get("primary")),
                    "paywall": check_brief._in(h, SOURCES["paywalled"])})
    return out


def find_links(query):
    q = quote_plus(query)
    return [{"name": f["name"], "url": f["template"].format(q=q)} for f in SOURCES["find_links"]]


def search_terms(text):
    words = re.findall(r"[A-Z][\w&.-]+(?:\s[A-Z][\w&.-]+)*", text)
    return " ".join(dict.fromkeys(words))[:60] or text[:60]


def date_bits(iso, edition):
    d = dt.date.fromisoformat(iso)
    rel = {0: "Today", 1: "Tomorrow"}.get((d - edition).days)
    return {"dow": rel or DOW[d.weekday()], "day": str(d.day), "mon": MON[d.month - 1]}


def build(draft, ctx, status):
    book = Book(ctx)
    edition = dt.date.fromisoformat(ctx["edition_date"])
    mentioned, outlets = set(), set()

    def item_common(x):
        pct, names = book.exposure(x)
        mentioned.update(book.covered(x))
        srcs = source_list(x.get("sources"))
        outlets.update(check_brief.host_of(s["url"]) for s in srcs)
        return pct, names, srcs

    top3 = []
    for t in draft.get("top3", []):
        pct, names = book.exposure(t)
        mentioned.update(book.covered(t))
        top3.append({"lead": t["lead"], "text": t["text"], "dir": t["dir"], "exposure_pct": pct,
                     "exposure_label": t.get("group") or (names[0] if len(names) == 1 else "Holdings")})

    stories = []
    for s in draft.get("stories", []):
        pct, names, srcs = item_common(s)
        related = []
        for r in s.get("related") or []:
            rs = source_list(r.get("sources"))
            outlets.update(check_brief.host_of(x["url"]) for x in rs)
            related.append({"label": r["label"], "headline": r["headline"], "text": r["text"], "sources": rs})
        stories.append({
            "id": s["id"], "group": s.get("group") or (book.h[names[0]]["group"] if names else ""),
            "headline": s["headline"], "when": s.get("when", ""), "what": s["what"], "why": s["why"],
            "dir": s["dir"], "impact": s["impact"], "exposure_pct": pct, "holdings": book.chips(names),
            "verify": s["verify"], "verify_note": s.get("verify_note", ""), "sources": srcs, "related": related,
            "find": find_links(s.get("search") or search_terms(s["headline"])), "set_links": book.set_links(names)})

    briefly = []
    for b in draft.get("briefly", []):
        pct, names, srcs = item_common(b)
        briefly.append({"headline": b["headline"], "text": b["text"], "exposure_pct": pct,
                        "exposure_label": b.get("group") or ", ".join(names[:2]),
                        "verify": b["verify"], "verify_note": b.get("verify_note", ""), "sources": srcs,
                        "set_links": book.set_links(names)})

    radar_notes = {t["topic"]: t.get("notes", []) for t in ctx.get("radar", [])}
    radar = []
    for r in draft.get("radar", []):
        rs = source_list(r.get("sources"))
        outlets.update(check_brief.host_of(x["url"]) for x in rs)
        radar.append({"topic": r["topic"], "text": r["text"], "notes": radar_notes.get(r["topic"], []), "sources": rs})

    # calendar: verified events from calendar.json plus today's new ones
    events = list(ctx.get("calendar", []))
    for e in draft.get("new_events", []):
        if not any(x["date"] == e["date"] and x["title"] == e["title"] for x in events):
            events.append(e)
    upcoming = []
    for e in sorted(events, key=lambda e: (e["date"], e.get("time_bkt") or "99"))[:8]:
        pct, names = book.exposure(e) if (e.get("holdings") or e.get("group")) else (None, [])
        label = (book.event_label(names, pct, e.get("group")) if names
                 else f"{e['group']} {pct}%" if e.get("group") else (f"See {e['tab']}" if e.get("tab") else ""))
        src = e.get("source")
        upcoming.append({**date_bits(e["date"], edition), "date": e["date"], "date_label": e.get("date_label"),
                         "time_bkt": e.get("time_bkt", ""), "title": e["title"], "detail": e.get("detail", ""),
                         "exposure_label": label, "tab": e.get("tab"),
                         "source": source_list([src])[0] if src else None})

    quiet = [{"name": h["name"], "weight": round(h["weight"] * 100, 1),
              "set_url": SOURCES["set_news_template"].format(symbol=h["set_symbol"]) if h.get("set_symbol") else None}
             for h in ctx["holdings"] if h["weight"] >= 0.005 and h["name"] not in mentioned and h.get("group")]
    small = sum(1 for h in ctx["holdings"] if h["weight"] < 0.005)
    thai = [{"symbol": h["set_symbol"], "weight": round(h["weight"] * 100, 2),
             "url": SOURCES["set_news_template"].format(symbol=h["set_symbol"])}
            for h in ctx["holdings"] if h.get("set_symbol")]

    words = sum(len((x.get("lead", "") + " " + x.get("text", "")).split()) for x in top3) + \
        sum(len((s["what"] + " " + s["why"]).split()) for s in stories) + sum(len(b["text"].split()) for b in briefly)
    primary_checked = sum(1 for x in stories + briefly if x["verify"] == "primary")
    names = {h: SOURCES["outlet_names"].get(h, h) for h in outlets}
    m = ctx["markets"]
    tiles = [{"label": t["label"], "value": t["value_text"], "change": t["change_text"], "dir": t.get("dir", "neutral"),
              "asof_date": t.get("asof_date"), "window": t.get("window"),
              "exposure_label": t["exposure_label"],
              "exposure_pct": round(t["exposure"] * 100, 1) if t.get("exposure") is not None else None}
             for t in m["tiles"] if t.get("value") is not None]
    early = [{"label": e["label"], "change": e["change_text"], "dir": "pos" if (e.get("change") or 0) >= 0 else "neg"}
             for e in m["early"]]
    return {
        "schema": 1, "status": status, "edition_date": ctx["edition_date"],
        "generated_at": dt.datetime.now(BKK).isoformat(timespec="minutes"),
        "window": ctx["window"], "portfolio_as_of": ctx["portfolio"]["as_of"],
        "read_minutes": max(2, round(words / 200)),
        "stats": {"stories": len(stories), "short_items": len(briefly), "outlets": len(outlets),
                  "outlet_names": sorted(set(names.values())), "primary_checked": primary_checked},
        "markets": {"tiles": tiles, "early": early, "fetched_at": m.get("fetched_at")},
        "top3": top3, "also": draft.get("also", []), "stories": stories, "briefly": briefly,
        "upcoming": upcoming, "radar": radar,
        "quiet": quiet, "quiet_small_count": small, "thai_stocks": thai,
        "nav_lags": ctx.get("nav_lags", []),
        "method": {
            "primary": "central banks, regulators and exchanges, company investor pages and fund houses",
            "press": [SOURCES["outlet_names"].get(d, d) for d in SOURCES["tiers"]["major"]["domains"]],
            "regional": [SOURCES["outlet_names"].get(d, d) for d in SOURCES["tiers"]["regional"]["domains"]],
            "blocked": ["Reuters", "AP", "Yonhap", "AFP", "the FT", "WSJ", "Barron's", "MarketWatch",
                        "The Economist", "BBC", "NYT", "The Guardian"],
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("draft")
    ap.add_argument("--status", default="live", choices=["live", "preview"])
    args = ap.parse_args()
    draft_path = Path(args.draft)
    draft = json.loads(draft_path.read_text())
    ctx = json.loads((ROOT / "news_work" / draft["edition_date"] / "context.json").read_text())
    c = check_brief.check(draft, ctx)
    for w in c.warnings:
        print("warning:", w)
    if c.errors:
        for e in c.errors:
            print("ERROR:", e)
        print("not published — fix the draft and run check_brief.py")
        return 1

    brief = build(draft, ctx, args.status)
    (DOCS / "briefs").mkdir(exist_ok=True)
    payload = json.dumps(brief, indent=1, ensure_ascii=False)
    (DOCS / "brief.json").write_text(payload)
    (DOCS / "briefs" / f"{brief['edition_date']}.json").write_text(payload)
    idx_path = DOCS / "briefs" / "index.json"
    idx = json.loads(idx_path.read_text()) if idx_path.exists() else []
    idx = [e for e in idx if e["date"] != brief["edition_date"]]
    idx.insert(0, {"date": brief["edition_date"], "lead": brief["top3"][0]["lead"] if brief["top3"] else ""})
    idx_path.write_text(json.dumps(sorted(idx, key=lambda e: e["date"], reverse=True)[:120], indent=1, ensure_ascii=False))

    # keep newly verified events for later editions
    cal_path = HERE / "calendar.json"
    cal = json.loads(cal_path.read_text())
    added = 0
    for e in draft.get("new_events", []):
        if not any(x["date"] == e["date"] and x["title"] == e["title"] for x in cal["events"]):
            cal["events"].append(e)
            added += 1
    if added:
        cal["events"].sort(key=lambda e: (e["date"], e.get("time_bkt") or "99"))
        cal_path.write_text(json.dumps(cal, indent=1, ensure_ascii=False) + "\n")

    s = brief["stats"]
    print(f"published docs/brief.json — {brief['edition_date']} ({args.status}): {s['stories']} stories, "
          f"{s['short_items']} short items, {s['outlets']} outlets, {s['primary_checked']} checked against primary"
          f" documents, {len(brief['upcoming'])} events ({added} new), {len(brief['quiet'])} quiet holdings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
