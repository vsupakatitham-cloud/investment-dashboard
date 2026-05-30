"""
fetch_thai_nav.py — Thai mutual-fund NAVs from the SEC Thailand Open API.

Portal:  https://api-portal.sec.or.th/   (subscribe to the two products below)

Two products / two subscription keys are required:
  * Fund Factsheet   -> maps a fund abbreviation to its proj_id
        GET https://api.sec.or.th/FundFactsheet/fund/amc
        GET https://api.sec.or.th/FundFactsheet/fund/amc/{unique_id}
  * Fund Daily Info  -> the daily NAV for a proj_id
        GET https://api.sec.or.th/FundDailyInfo/{proj_id}/dailynav/{yyyy-mm-dd}
            -> JSON, NAV in field `last_val`

Auth header on every call:  Ocp-Apim-Subscription-Key: <key>

Keys are read from the environment (never hard-coded / committed):
    SEC_FUND_FACTSHEET_KEY   (one key, or several comma-separated to spread load)
    SEC_FUND_DAILY_INFO_KEY

Everything degrades gracefully: if a key is missing, the host is down, or a fund
can't be matched, the caller simply carries the previous NAV forward and flags it.

CLI:
    python3 pipeline/fetch_thai_nav.py --selftest          # check connectivity/keys
    python3 pipeline/fetch_thai_nav.py --refresh-map       # rebuild proj_id cache
    python3 pipeline/fetch_thai_nav.py --nav ASP-AIEQ      # one fund, latest NAV
"""
from __future__ import annotations

import argparse
import datetime as _dt
import itertools
import json
import os
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

SEC_HOST = "https://api.sec.or.th"
MAP_CACHE = Path(__file__).resolve().parent / "sec_fund_map.json"
MAP_TTL_DAYS = 14
UA = "Mozilla/5.0 (private-banking-dashboard)"


# --------------------------------------------------------------------------- #
# low-level request helpers
# --------------------------------------------------------------------------- #
def _keys(env_name: str) -> list[str]:
    raw = os.environ.get(env_name, "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def _sec_get(path: str, key: str, timeout: int = 20):
    """GET a SEC endpoint. Returns (status_code, parsed_json_or_None)."""
    url = path if path.startswith("http") else f"{SEC_HOST}{path}"
    req = urllib.request.Request(url, headers={
        "Ocp-Apim-Subscription-Key": key,
        "Accept": "application/json",
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


# --------------------------------------------------------------------------- #
# name normalisation / matching
# --------------------------------------------------------------------------- #
def _norm(name: str) -> str:
    return re.sub(r"\s+", "", (name or "")).upper()


def _loose(name: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(name))


# --------------------------------------------------------------------------- #
# fund map (abbreviation -> proj_id), cached to disk
# --------------------------------------------------------------------------- #
def build_fund_map(refresh: bool = False) -> dict:
    """Return {'built': iso, 'exact': {NORM: proj_id}, 'loose': {LOOSE: proj_id}}.

    Loads from cache if fresh; otherwise walks every AMC's fund list. Requires
    SEC_FUND_FACTSHEET_KEY. On failure returns whatever cache exists (or empty).
    """
    if not refresh and MAP_CACHE.exists():
        try:
            cached = json.loads(MAP_CACHE.read_text())
            built = _dt.date.fromisoformat(cached.get("built", "1900-01-01"))
            if (_dt.date.today() - built).days <= MAP_TTL_DAYS:
                return cached
        except Exception:
            pass

    keys = _keys("SEC_FUND_FACTSHEET_KEY")
    if not keys:
        if MAP_CACHE.exists():
            return json.loads(MAP_CACHE.read_text())
        return {"built": "", "exact": {}, "loose": {}}

    key_cycle = itertools.cycle(keys)
    status, amcs = _sec_get("/FundFactsheet/fund/amc", next(key_cycle))
    if status != 200 or not isinstance(amcs, list):
        if MAP_CACHE.exists():
            return json.loads(MAP_CACHE.read_text())
        return {"built": "", "exact": {}, "loose": {}}

    exact, loose, ambiguous = {}, {}, set()
    for amc in amcs:
        uid = amc.get("unique_id") or amc.get("uniqueId")
        if not uid:
            continue
        st, funds = _sec_get(f"/FundFactsheet/fund/amc/{uid}", next(key_cycle))
        if st != 200 or not isinstance(funds, list):
            continue
        for f in funds:
            proj_id = f.get("proj_id")
            abbr = f.get("proj_abbr_name")
            status_rg = (f.get("fund_status") or "").upper()
            if not proj_id or not abbr:
                continue
            if status_rg and status_rg != "RG":   # keep registered funds only
                continue
            exact[_norm(abbr)] = proj_id
            lk = _loose(abbr)
            if lk in loose and loose[lk] != proj_id:
                ambiguous.add(lk)
            else:
                loose[lk] = proj_id
        time.sleep(0.05)
    for lk in ambiguous:                          # drop ambiguous loose keys
        loose.pop(lk, None)

    result = {"built": _dt.date.today().isoformat(), "exact": exact, "loose": loose}
    if exact:
        MAP_CACHE.write_text(json.dumps(result, indent=0))
    return result


def resolve_proj_id(abbr: str, fund_map: dict) -> str | None:
    n = _norm(abbr)
    if n in fund_map.get("exact", {}):
        return fund_map["exact"][n]
    return fund_map.get("loose", {}).get(_loose(abbr))


# --------------------------------------------------------------------------- #
# NAV lookup
# --------------------------------------------------------------------------- #
def latest_nav(proj_id: str, asof: _dt.date | None = None, lookback: int = 8):
    """Most recent NAV at/just before `asof`. Returns (nav: float, date: iso) or None."""
    keys = _keys("SEC_FUND_DAILY_INFO_KEY")
    if not keys:
        return None
    key_cycle = itertools.cycle(keys)
    asof = asof or _dt.date.today()
    for back in range(lookback):
        d = asof - _dt.timedelta(days=back)
        status, data = _sec_get(f"/FundDailyInfo/{proj_id}/dailynav/{d.isoformat()}", next(key_cycle))
        if status == 200 and isinstance(data, dict):
            val = data.get("last_val", data.get("net_asset"))
            try:
                if val is not None and float(val) > 0:
                    return float(val), d.isoformat()
            except (TypeError, ValueError):
                pass
        time.sleep(0.05)
    return None


def resolve_navs(abbrs, asof: _dt.date | None = None, refresh_map: bool = False):
    """Batch: {abbr: {'nav': float, 'date': iso}} for funds we could price.

    Returns ({}, reason) when SEC keys are not configured so the caller can fall
    back to carry-forward without treating it as an error.
    """
    if not _keys("SEC_FUND_DAILY_INFO_KEY") or not (_keys("SEC_FUND_FACTSHEET_KEY") or MAP_CACHE.exists()):
        return {}, "SEC keys not configured"

    fund_map = build_fund_map(refresh=refresh_map)
    out, unmatched, nodata = {}, [], []
    for abbr in abbrs:
        pid = resolve_proj_id(abbr, fund_map)
        if not pid:
            unmatched.append(abbr)
            continue
        res = latest_nav(pid, asof)
        if res:
            out[abbr] = {"nav": res[0], "date": res[1]}
        else:
            nodata.append(abbr)
    reason = f"matched {len(out)}/{len(list(abbrs))}"
    if unmatched:
        reason += f"; unmatched: {', '.join(unmatched)}"
    if nodata:
        reason += f"; no NAV: {', '.join(nodata)}"
    return out, reason


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--refresh-map", action="store_true")
    ap.add_argument("--nav", metavar="ABBR")
    ap.add_argument("--asof", default=_dt.date.today().isoformat())
    args = ap.parse_args()

    if args.selftest:
        ff = _keys("SEC_FUND_FACTSHEET_KEY")
        fd = _keys("SEC_FUND_DAILY_INFO_KEY")
        print(f"SEC_FUND_FACTSHEET_KEY : {'set ('+str(len(ff))+')' if ff else 'NOT SET'}")
        print(f"SEC_FUND_DAILY_INFO_KEY: {'set ('+str(len(fd))+')' if fd else 'NOT SET'}")
        st, _ = _sec_get("/FundFactsheet/fund/amc", ff[0] if ff else "none")
        print(f"Factsheet /amc status  : {st}  ({'OK' if st==200 else 'auth/again' if st==401 else st})")
        return

    if args.refresh_map:
        m = build_fund_map(refresh=True)
        print(f"Fund map built {m.get('built')}: {len(m.get('exact',{}))} funds.")
        return

    if args.nav:
        m = build_fund_map()
        pid = resolve_proj_id(args.nav, m)
        print(f"{args.nav} -> proj_id {pid}")
        if pid:
            res = latest_nav(pid, _dt.date.fromisoformat(args.asof))
            print(f"   NAV: {res}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
