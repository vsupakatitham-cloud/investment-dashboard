"""
fetch_benchmark.py — Build the benchmark price history (THB-denominated) used by
the Performance page. Default benchmark: MSCI ACWI via the iShares ACWI ETF,
converted to THB (ACWI_usd x USD/THB), indexed to 100 at the series start.

Writes docs/benchmark.json:
  {"name","symbol","as_of","series":[{"date":"YYYY-MM-DD","level":<float>}, ...]}

A THB investor's MSCI ACWI return includes the USD/THB move, so the level is the
USD ETF close multiplied by the spot on the same day. ~6 years of daily history
are kept (enough for 5Y metrics with a buffer), so the benchmark line is fully
populated immediately while the portfolio's own history accumulates.
"""
from __future__ import annotations

import datetime as _dt
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONFIG = Path(__file__).resolve().parent / "config.json"
UA = {"User-Agent": "Mozilla/5.0 (private-banking-dashboard)"}
KEEP_YEARS = 6


def _yahoo_daily(symbol, rng="10y", timeout=30):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={rng}&interval=1d"
    req = urllib.request.Request(url, headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode())
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    close = res["indicators"]["quote"][0]["close"]
    out = {}
    for t, c in zip(ts, close):
        if c is not None:
            out[_dt.datetime.utcfromtimestamp(t).date().isoformat()] = float(c)
    return out


def build(asof=None):
    cfg = json.loads(CONFIG.read_text())
    bm = cfg.get("benchmark", {"name": "MSCI ACWI (THB)", "symbol": "ACWI", "fx_symbol": "THB=X"})
    px = _yahoo_daily(bm["symbol"])
    fx = _yahoo_daily(bm.get("fx_symbol", "THB=X"))
    # align on common dates, level in THB = price(USD) * USDTHB
    dates = sorted(set(px) & set(fx))
    if not dates:
        return None
    cutoff = (_dt.date.today() - _dt.timedelta(days=int(KEEP_YEARS * 365.25))).isoformat()
    dates = [d for d in dates if d >= cutoff]
    base = px[dates[0]] * fx[dates[0]]
    series = [{"date": d, "level": round(px[d] * fx[d] / base * 100.0, 4)} for d in dates]
    payload = {
        "name": bm["name"], "symbol": bm["symbol"],
        "as_of": asof or dates[-1],
        "series": series,
    }
    DOCS.mkdir(exist_ok=True)
    (DOCS / "benchmark.json").write_text(json.dumps(payload))
    return payload


if __name__ == "__main__":
    p = build()
    if p:
        print(f"Benchmark {p['name']}: {len(p['series'])} daily points, "
              f"{p['series'][0]['date']} -> {p['series'][-1]['date']}")
    else:
        print("Benchmark fetch failed.")
