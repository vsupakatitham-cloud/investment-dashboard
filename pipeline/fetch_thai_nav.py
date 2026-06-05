"""
fetch_thai_nav.py — Thai mutual-fund NAVs from the SEC "Open Data" Fund API (v2).

Portal:  https://secopendata.sec.or.th/   (the successor to api-portal.sec.or.th)
Gateway: https://api.sec.or.th

This uses the NEW consolidated **Fund API** (product name "sec-openapi-normal").
ONE subscription key drives the whole flow:

  * Fund profiles  GET /v2/fund/general-info/profiles?page_size=100[&next_cursor=]
        -> proj_id, proj_abbr_name, fund_class_name, fund_status  (cursor-paged)
  * Daily NAV      GET /v2/fund/daily-info/nav?proj_id=..&start_nav_date=..&end_nav_date=..
        -> items[].last_val  (NAV/unit, THB),  items[].nav_date,  items[].fund_class_name

Auth header on every call:  Ocp-Apim-Subscription-Key: <key>

Key (read from the environment, never committed):
    SEC_OPENAPI_KEY            # the "fund_api" / sec-openapi-normal subscription key
                               # (legacy SEC_FUND_DAILY_INFO_KEY is accepted as a fallback)

A fund abbreviation can have several share classes, each with its own NAV, so a
verified abbreviation -> (proj_id, fund_class_name) map is shipped in
`pipeline/sec_fund_map.json` (every entry NAV-checked against the workbook).
Runtime therefore only makes one NAV call per held fund — no page-walking.

Everything degrades gracefully: missing key, host down, or an unmapped fund all
fall back to carrying the previous NAV forward and flagging it.

CLI:
    python3 pipeline/fetch_thai_nav.py --selftest          # key + connectivity
    python3 pipeline/fetch_thai_nav.py --nav K-VIETNAMRMF  # latest NAV for one fund
    python3 pipeline/fetch_thai_nav.py --refresh-map       # add NEW funds to the pin map
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import time
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

SEC_HOST = "https://api.sec.or.th"
MAP_FILE = Path(__file__).resolve().parent / "sec_fund_map.json"
UA = "private-banking-dashboard"


# --------------------------------------------------------------------------- #
# auth / request helpers
# --------------------------------------------------------------------------- #
def _key() -> str | None:
    for name in ("SEC_OPENAPI_KEY", "SEC_FUND_DAILY_INFO_KEY", "SEC_FUND_FACTSHEET_KEY"):
        v = os.environ.get(name, "").strip()
        if v:
            return v.split(",")[0].strip()   # first key if several are given
    return None


def _get(path: str, key: str, timeout: int = 30):
    """GET a SEC v2 endpoint. Returns (status_code, parsed_json_or_None)."""
    url = path if path.startswith("http") else f"{SEC_HOST}{path}"
    req = urllib.request.Request(url, headers={
        "Ocp-Apim-Subscription-Key": key,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": UA,
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace").strip()
            if r.status == 204 or not body:
                return r.status, None
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, None
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception:
        return None, None


def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).upper()


# --------------------------------------------------------------------------- #
# pin map (abbreviation -> proj_id + fund_class_name)
# --------------------------------------------------------------------------- #
def load_pin_map() -> dict:
    if MAP_FILE.exists():
        try:
            return json.loads(MAP_FILE.read_text()).get("funds", {})
        except Exception:
            return {}
    return {}


# --------------------------------------------------------------------------- #
# NAV lookup
# --------------------------------------------------------------------------- #
def latest_nav(proj_id: str, fund_class_name: str | None, key: str,
               asof: _dt.date | None = None, lookback: int = 12):
    """Most recent NAV at/just before `asof` for a fund (and share class).

    Returns (nav: float, date: iso) or None.
    """
    asof = asof or _dt.date.today()
    start = (asof - _dt.timedelta(days=lookback)).isoformat()
    q = urllib.parse.urlencode({
        "proj_id": proj_id,
        "start_nav_date": start,
        "end_nav_date": asof.isoformat(),
        "page_size": 100,
    })
    status, data = _get(f"/v2/fund/daily-info/nav?{q}", key)
    if status != 200 or not isinstance(data, dict):
        return None
    items = data.get("items", []) or []
    if fund_class_name:
        cls = [it for it in items if it.get("fund_class_name") == fund_class_name]
        items = cls or items
    items = [it for it in items if it.get("last_val") not in (None, "", 0)]
    if not items:
        return None
    items.sort(key=lambda it: it.get("nav_date", ""))
    last = items[-1]
    # previous NAV (the trading day before `last`) — for daily-move calc; the
    # response already carries the series so this is free. None if only one point.
    prev_val, prev_date = None, ""
    if len(items) >= 2:
        try:
            prev_val = float(items[-2]["last_val"])
            prev_date = items[-2].get("nav_date", "")
        except (TypeError, ValueError, KeyError):
            prev_val, prev_date = None, ""
    try:
        return float(last["last_val"]), last.get("nav_date", ""), prev_val, prev_date
    except (TypeError, ValueError, KeyError):
        return None


def resolve_navs(abbrs, asof: _dt.date | None = None, **_):
    """Batch NAV lookup. Returns ({abbr: {'nav': float, 'date': iso}}, reason).

    Returns ({}, reason) when the key isn't configured so the caller falls back
    to carry-forward without treating it as an error.
    """
    key = _key()
    if not key:
        return {}, "SEC key not configured (set SEC_OPENAPI_KEY)"

    pins = load_pin_map()
    out, unmapped, nodata = {}, [], []
    for abbr in abbrs:
        pin = pins.get(abbr) or pins.get(_norm(abbr))
        if not pin:
            unmapped.append(abbr)
            continue
        res = latest_nav(pin["proj_id"], pin.get("fund_class_name"), key, asof)
        if res:
            out[abbr] = {"nav": res[0], "date": res[1],
                         "prev": res[2], "prev_date": res[3]}
        else:
            nodata.append(abbr)
        time.sleep(0.05)
    reason = f"matched {len(out)}/{len(list(abbrs))} via SEC /v2/fund"
    if unmapped:
        reason += f"; unmapped: {', '.join(unmapped)}"
    if nodata:
        reason += f"; no NAV: {', '.join(nodata)}"
    return out, reason


# --------------------------------------------------------------------------- #
# maintenance: extend the pin map with NEW abbreviations (does not clobber)
# --------------------------------------------------------------------------- #
def _all_profiles(key, max_pages=200):
    rows, cursor, pages = [], None, 0
    while pages < max_pages:
        q = "page_size=100" + (f"&next_cursor={urllib.parse.quote(cursor)}" if cursor else "")
        st, d = _get(f"/v2/fund/general-info/profiles?{q}", key)
        if st != 200 or not isinstance(d, dict):
            break
        rows.extend(d.get("items", []) or [])
        cursor = d.get("next_cursor")
        pages += 1
        if not cursor:
            break
    return rows


def refresh_map(new_abbrs):
    """Add pins for abbreviations not already in the map (exact abbr/class match).

    Ambiguous share classes should be verified and pinned by hand in
    sec_fund_map.json — this only fills clean, unambiguous matches.
    """
    key = _key()
    if not key:
        print("No SEC key set."); return
    existing = json.loads(MAP_FILE.read_text()) if MAP_FILE.exists() else {"funds": {}}
    funds = existing.get("funds", {})
    todo = [a for a in new_abbrs if a not in funds]
    if not todo:
        print("Map already covers all requested funds."); return
    rows = _all_profiles(key)
    by_class, by_abbr = {}, {}
    for it in rows:
        by_class.setdefault(_norm(it.get("fund_class_name")), (it.get("proj_id"), it.get("fund_class_name")))
        by_abbr.setdefault(_norm(it.get("proj_abbr_name")), (it.get("proj_id"), it.get("fund_class_name")))
    added = 0
    for a in todo:
        hit = by_class.get(_norm(a)) or by_abbr.get(_norm(a))
        if hit:
            funds[a] = {"proj_id": hit[0], "fund_class_name": hit[1]}
            added += 1
        else:
            print(f"  unmatched (pin by hand): {a}")
    existing["funds"] = funds
    MAP_FILE.write_text(json.dumps(existing, indent=1, ensure_ascii=False))
    print(f"Added {added} pin(s); map now covers {len(funds)} funds.")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--nav", metavar="ABBR")
    ap.add_argument("--refresh-map", nargs="*", metavar="ABBR")
    ap.add_argument("--asof", default=_dt.date.today().isoformat())
    args = ap.parse_args()
    key = _key()

    if args.selftest:
        print(f"SEC key            : {'set' if key else 'NOT SET (export SEC_OPENAPI_KEY=...)'}")
        if key:
            st, d = _get("/v2/fund/daily-info/nav?page_size=1", key)
            print(f"/v2/fund NAV probe : {st}  ({'OK' if st == 200 else 'check subscription'})")
        print(f"Pin map            : {len(load_pin_map())} funds in {MAP_FILE.name}")
        return

    if args.refresh_map is not None:
        refresh_map(args.refresh_map)
        return

    if args.nav:
        pin = load_pin_map().get(args.nav)
        print(f"{args.nav} -> {pin}")
        if pin and key:
            print("   NAV:", latest_nav(pin["proj_id"], pin.get("fund_class_name"), key,
                                        _dt.date.fromisoformat(args.asof)))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
