#!/usr/bin/env python3
"""
check_brief.py — validate a Morning Brief draft before it is published.

    python3 pipeline/news/check_brief.py news_work/<date>/draft.json [--no-links]

Checks the draft against the source policy (sources.json) and that day's
context.json: every source is https and on the allowlist (never a blocked or
'never' domain), 'primary' is only claimed for primary domains, trust labels
match the sources given, holdings exist, lengths fit the design, the text
contains no trade advice, long quotations, links or markup, nothing is copied
from example_draft.json on another day, and no link is dead (404/410 or an
unknown host; skip that network check with --no-links).
Exit 0 = publishable (warnings may print). Exit 1 = fix the listed errors.
"""
from __future__ import annotations

import json
import re
import socket
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCES = json.loads((HERE / "sources.json").read_text())
EXAMPLE = HERE / "example_draft.json"

DIRS = {"pos", "neg", "watch", "neutral"}
VERIFY = {"primary", "multi", "single", "differ"}
LIMITS = {"lead": 95, "text": 280, "headline": 115, "what": 620, "why": 460, "when": 40, "also": 90,
          "verify_note": 70, "related_text": 360, "briefly_text": 320, "radar_text": 380, "search": 60,
          "title": 90, "detail": 80}
ADVICE = re.compile(
    r"\b(you should|we (?:recommend|suggest|advise)|(?:i|we) would (?:buy|sell)|consider (?:buying|selling|adding|trimming|reducing|taking)|"
    r"time to (?:buy|sell)|(?:buy|sell|trim|add to|exit) (?:your|the position|more|some)|take profits?|lock in (?:gains|profits)|"
    r"price target|strong buy|overweight|underweight|accumulate)\b", re.I)


def host_of(url: str) -> str:
    h = (urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _in(host, domains):
    return any(host == d or host.endswith("." + d) for d in domains)


def tier_of(url: str):
    h = host_of(url)
    for name, tier in SOURCES["tiers"].items():
        if _in(h, tier["domains"]):
            return name
    return None


class Checker:
    def __init__(self, draft: dict, ctx: dict):
        self.d, self.ctx = draft, ctx
        self.errors, self.warnings = [], []
        self.names = {h["name"] for h in ctx["holdings"]}
        self.groups = {g["group"] for g in ctx["groups"]}
        self.topics = {t["topic"] for t in ctx.get("radar", [])}

    def err(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")

    # -- field helpers
    def text(self, where, obj, key, limit_key=None, required=True):
        v = obj.get(key)
        if v in (None, ""):
            if required:
                self.err(where, f"missing '{key}'")
            return ""
        if not isinstance(v, str):
            self.err(where, f"'{key}' must be text")
            return ""
        lim = LIMITS.get(limit_key or key)
        if lim and len(v) > lim:
            self.err(where, f"'{key}' is {len(v)} characters; keep it under {lim}")
        if re.search(r"https?://|www\.", v):
            self.err(where, f"'{key}' contains a link; links belong in sources")
        if re.search(r"<[a-zA-Z/][^>]*>", v):
            self.err(where, f"'{key}' contains markup")
        if ADVICE.search(v):
            self.err(where, f"'{key}' reads as trade advice ('{ADVICE.search(v).group(0)}'); explain, don't recommend")
        for q in re.findall(r"[\"“]([^\"”]+)[\"”]", v):
            if len(q.split()) > 12:
                self.err(where, f"'{key}' quotes {len(q.split())} words; paraphrase instead (max 12)")
        return v

    def sources(self, where, srcs, min_n=1):
        if not isinstance(srcs, list) or len(srcs) < min_n:
            self.err(where, f"needs at least {min_n} source(s)")
            return []
        hosts, urls = [], set()
        for i, s in enumerate(srcs):
            w = f"{where}.sources[{i}]"
            url, name = (s or {}).get("url", ""), (s or {}).get("name", "")
            if not name:
                self.err(w, "missing name")
            if not url.startswith("https://"):
                self.err(w, f"url must start with https:// ({url[:60]})")
                continue
            h = host_of(url)
            if _in(h, SOURCES["blocked"]):
                self.err(w, f"{h} blocks AI tools and must not be cited")
            elif _in(h, SOURCES["never"]):
                self.err(w, f"{h} is on the never-use list")
            elif not tier_of(url):
                self.err(w, f"{h} is not on the source allowlist")
            if s.get("primary") and tier_of(url) != "primary":
                self.err(w, f"{h} is not a primary source; drop 'primary'")
            if url in urls:
                self.err(w, "duplicate url")
            urls.add(url)
            hosts.append(h)
        return hosts

    def verify(self, where, item, hosts, srcs):
        v = item.get("verify")
        if v not in VERIFY:
            self.err(where, f"verify must be one of {sorted(VERIFY)}")
            return
        distinct = len(set(hosts))
        if v == "primary" and not any(s.get("primary") for s in srcs):
            self.err(where, "verify 'primary' needs a source marked primary")
        if v in ("multi", "differ") and distinct < 2:
            self.err(where, f"verify '{v}' needs 2+ different outlets (has {distinct})")
        if v == "single" and distinct > 1:
            self.warn(where, "verify 'single' but more than one outlet is cited; use 'multi'")
        self.text(where, item, "verify_note", required=False)

    def exposure(self, where, item):
        hs = item.get("holdings") or []
        if not isinstance(hs, list):
            self.err(where, "holdings must be a list")
            hs = []
        for n in hs:
            if n not in self.names:
                self.err(where, f"unknown holding '{n}' (use names exactly as in context.holdings)")
        g = item.get("group")
        if g and g not in self.groups:
            self.err(where, f"unknown group '{g}' (one of {sorted(self.groups)})")
        if not hs and not g:
            self.err(where, "give holdings or a group so exposure can be computed")

    # -- sections
    def run(self):
        d = self.d
        if d.get("edition_date") != self.ctx["edition_date"]:
            self.err("draft", f"edition_date {d.get('edition_date')} != context {self.ctx['edition_date']}")
        top = d.get("top3") or []
        if not 1 <= len(top) <= 3:
            self.err("top3", "needs 1 to 3 items")
        for i, t in enumerate(top):
            w = f"top3[{i}]"
            self.text(w, t, "lead")
            self.text(w, t, "text")
            self.exposure(w, t)
            if t.get("dir") not in DIRS:
                self.err(w, f"dir must be one of {sorted(DIRS)}")
        for i, a in enumerate(d.get("also") or []):
            if not isinstance(a, str) or len(a) > LIMITS["also"]:
                self.err(f"also[{i}]", f"short text under {LIMITS['also']} characters")
        stories = d.get("stories") or []
        if len(stories) > 7:
            self.err("stories", "at most 7 stories")
        ids = set()
        for i, s in enumerate(stories):
            w = f"stories[{i}]"
            sid = s.get("id") or ""
            if not re.fullmatch(r"[a-z0-9-]{2,40}", sid):
                self.err(w, "id must be 2-40 chars of a-z, 0-9, -")
            if sid in ids:
                self.err(w, f"duplicate id {sid}")
            ids.add(sid)
            for k in ("headline", "what", "why"):
                self.text(w, s, k)
            self.text(w, s, "when", required=False)
            self.text(w, s, "search", required=False)
            if s.get("dir") not in DIRS:
                self.err(w, f"dir must be one of {sorted(DIRS)}")
            if s.get("impact") not in (1, 2, 3):
                self.err(w, "impact must be 1, 2 or 3")
            self.exposure(w, s)
            srcs = s.get("sources") or []
            self.verify(w, s, self.sources(w, srcs), srcs)
            for j, r in enumerate(s.get("related") or []):
                rw = f"{w}.related[{j}]"
                self.text(rw, r, "label", "title")
                self.text(rw, r, "headline")
                self.text(rw, r, "text", "related_text")
                self.sources(rw, r.get("sources"))
        for i, b in enumerate(d.get("briefly") or []):
            w = f"briefly[{i}]"
            self.text(w, b, "headline")
            self.text(w, b, "text", "briefly_text")
            self.exposure(w, b)
            srcs = b.get("sources") or []
            self.verify(w, b, self.sources(w, srcs), srcs)
        if len(d.get("briefly") or []) > 6:
            self.err("briefly", "at most 6 items")
        for i, r in enumerate(d.get("radar") or []):
            w = f"radar[{i}]"
            if r.get("topic") not in self.topics:
                self.err(w, f"topic must be one of {sorted(self.topics)} (add new topics to radar.json)")
            self.text(w, r, "text", "radar_text")
            self.sources(w, r.get("sources"))
        for i, e in enumerate(d.get("new_events") or []):
            w = f"new_events[{i}]"
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.get("date", "")) or e["date"] < self.ctx["edition_date"]:
                self.err(w, "date must be YYYY-MM-DD, today or later")
            if e.get("time_bkt") and not re.fullmatch(r"\d{2}:\d{2}", e["time_bkt"]):
                self.err(w, "time_bkt must be HH:MM (Bangkok)")
            self.text(w, e, "title")
            self.text(w, e, "detail", required=False)
            self.exposure(w, e)
            if e.get("kind") != "fixed":
                self.sources(w, [e.get("source")] if e.get("source") else [])
        if not stories and not d.get("briefly"):
            self.warn("draft", "no stories or short items; fine on a quiet day, but double-check the searches ran")
        self.not_the_example()
        return self

    def not_the_example(self):
        """example_draft.json shows the format only; on any other day its links and headlines are stale."""
        try:
            ex = json.loads(EXAMPLE.read_text())
        except (OSError, ValueError):
            return
        if ex.get("edition_date") == self.d.get("edition_date"):
            return
        urls, heads = set(), set()
        for item in ex.get("stories", []) + ex.get("briefly", []):
            heads.add(item.get("headline"))
            urls.update(s.get("url") for s in item.get("sources", []))
            for r in item.get("related") or []:
                urls.update(s.get("url") for s in r.get("sources", []))
        for sec in ("stories", "briefly"):
            for i, item in enumerate(self.d.get(sec) or []):
                w = f"{sec}[{i}]"
                if item.get("headline") in heads:
                    self.err(w, "headline copied from example_draft.json; write today's own")
                srcs = list(item.get("sources") or []) + [s for r in item.get("related") or [] for s in r.get("sources", [])]
                for s in srcs:
                    if (s or {}).get("url") in urls:
                        self.err(w, f"link reused from example_draft.json ({ex.get('edition_date')} news): {s['url'][:80]}")


def all_links(draft: dict) -> list[str]:
    urls = []
    for sec in ("stories", "briefly", "radar"):
        for item in draft.get(sec) or []:
            urls += [s.get("url") for s in item.get("sources") or []]
            for r in item.get("related") or []:
                urls += [s.get("url") for s in r.get("sources") or []]
    urls += [e["source"].get("url") for e in draft.get("new_events") or [] if e.get("source")]
    return [u for u in dict.fromkeys(urls) if u and u.startswith("https://")]


def dead_links(urls: list[str], timeout: int = 15) -> list[tuple[str, str]]:
    """Links that are definitely gone: 404/410 or a host that doesn't resolve.
    Bot blocks (401/403/429), paid gateways and timeouts are inconclusive and pass."""
    def probe(u):
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0 (compatible; THInvestmentBrief/1.0; link check)"})
            with urllib.request.urlopen(req, timeout=timeout):
                return None
        except urllib.error.HTTPError as e:
            return (u, f"HTTP {e.code}") if e.code in (404, 410) else None
        except urllib.error.URLError as e:
            return (u, "host not found") if isinstance(e.reason, socket.gaierror) else None
        except Exception:
            return None
    with ThreadPoolExecutor(8) as ex:
        return [x for x in ex.map(probe, urls) if x]


def check(draft: dict, ctx: dict) -> Checker:
    return Checker(draft, ctx).run()


def main():
    args = [a for a in sys.argv[1:] if a != "--no-links"]
    if len(args) != 1:
        print(__doc__)
        return 2
    path = Path(args[0])
    draft = json.loads(path.read_text())
    ctx_path = ROOT / "news_work" / draft.get("edition_date", "") / "context.json"
    if not ctx_path.exists():
        ctx_path = path.parent / "context.json"
    c = check(draft, json.loads(ctx_path.read_text()))
    if "--no-links" not in sys.argv:
        for url, why in dead_links(all_links(draft)):
            c.err("link", f"{why}: {url[:90]} (fix or drop this source)")
    for w in c.warnings:
        print("warning:", w)
    for e in c.errors:
        print("ERROR:", e)
    print("OK — ready to publish" if not c.errors else f"{len(c.errors)} error(s) — fix and re-run")
    return 1 if c.errors else 0


if __name__ == "__main__":
    sys.exit(main())
