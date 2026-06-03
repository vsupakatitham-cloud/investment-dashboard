"""
performance.py — institutional performance metrics for the Performance page.

Inputs:
  * portfolio daily history  (docs/history.json: date, total_value, total_invested)
  * cash flows               (workbook "Cash Flows" sheet: date, amount ฿)
  * benchmark series         (docs/benchmark.json: THB-denominated MSCI ACWI, indexed)
  * fee / risk-free          (config.json)

Outputs a `performance` dict consumed by the dashboard: period returns
(portfolio net & gross, benchmark, relative), risk/return stats, the aligned
growth series, calendar-year returns, the drawdown series, and money-weighted
return (IRR). Everything degrades gracefully — metrics that need more history
than exists yet are returned as null with a `history_days` count, so the page
shows a "building" state until enough daily snapshots accrue.

Time-weighted return is flow-adjusted: between snapshots, r = (V_end - net_flow)
/ V_start - 1, then geometrically linked.
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"


def _d(s):
    return _dt.date.fromisoformat(s[:10])


def _read_cash_flows(wb):
    flows = []
    if "Cash Flows" not in wb.sheetnames:
        return flows
    ws = wb["Cash Flows"]
    for r in range(5, ws.max_row + 1):
        dt_, amt = ws.cell(r, 1).value, ws.cell(r, 2).value
        if dt_ is None or amt in (None, ""):
            continue
        if isinstance(dt_, _dt.datetime):
            dt_ = dt_.date()
        elif isinstance(dt_, str):
            try:
                dt_ = _d(dt_)
            except ValueError:
                continue
        try:
            flows.append((dt_, float(amt)))
        except (TypeError, ValueError):
            continue
    return flows


def _twr_daily(history, flows):
    """Geometrically-linkable daily TWR steps from value snapshots + flows.
    Returns list of (date, step_return)."""
    hist = sorted(history, key=lambda h: h["date"])
    steps = []
    for i in range(1, len(hist)):
        v0 = hist[i - 1]["total_value"]
        v1 = hist[i]["total_value"]
        d0, d1 = _d(hist[i - 1]["date"]), _d(hist[i]["date"])
        flow = sum(a for (fd, a) in flows if d0 < fd <= d1)
        if v0:
            steps.append((d1, (v1 - flow) / v0 - 1))
    return steps


def _link(steps):
    v = 1.0
    for _, r in steps:
        v *= (1 + r)
    return v - 1


def _annualize(total, days):
    if days <= 0:
        return None
    return (1 + total) ** (365.25 / days) - 1


def _window(steps, start, end):
    return [(d, r) for (d, r) in steps if start < d <= end]


def _bench_steps(series):
    out = []
    for i in range(1, len(series)):
        l0 = series[i - 1]["level"]
        l1 = series[i]["level"]
        if l0:
            out.append((_d(series[i]["date"]), l1 / l0 - 1))
    return out


def _stdev(xs):
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


# trailing periods need enough history to be meaningful (don't show a "5Y"
# number from one month of data); the to-date / since-inception periods are
# always valid as the investor's actual return for the time they were invested.
_MIN_DAYS = {"1Y": 330, "3Y p.a.": int(365 * 3 * 0.9), "5Y p.a.": int(365 * 5 * 0.9)}


def _period_returns(steps, asof, hist_days, inception, annualized_after_days=370):
    """{label: return or None}. Each period is measured over the window the
    portfolio was actually invested — start is clamped to inception — so the
    portfolio and benchmark are compared over identical windows."""
    if not steps:
        return {k: None for k in PERIODS}
    out = {}
    for label, start in _period_starts(asof).items():
        if label in _MIN_DAYS and hist_days < _MIN_DAYS[label]:
            out[label] = None
            continue
        eff_start = max(start, inception)
        win = _window(steps, eff_start, asof)
        if not win:
            out[label] = None
            continue
        tot = _link(win)
        days = (asof - max(eff_start, win[0][0])).days or 1
        if "p.a." in label and days > annualized_after_days:
            out[label] = _annualize(tot, days)
        else:
            out[label] = tot
    return out


PERIODS = ["MTD", "QTD", "YTD", "1Y", "3Y p.a.", "5Y p.a.", "SI p.a."]


def _period_starts(asof):
    y, m = asof.year, asof.month
    qm = 3 * ((m - 1) // 3) + 1
    return {
        "MTD": asof.replace(day=1) - _dt.timedelta(days=1),
        "QTD": _dt.date(y, qm, 1) - _dt.timedelta(days=1),
        "YTD": _dt.date(y, 1, 1) - _dt.timedelta(days=1),
        "1Y": asof - _dt.timedelta(days=365),
        "3Y p.a.": asof - _dt.timedelta(days=365 * 3),
        "5Y p.a.": asof - _dt.timedelta(days=365 * 5),
        "SI p.a.": _dt.date(1990, 1, 1),
    }


def _xirr(flows, guess=0.1):
    """flows: list of (date, amount). Returns annualized IRR or None."""
    if len(flows) < 2:
        return None
    t0 = min(f[0] for f in flows)

    def npv(rate):
        return sum(a / (1 + rate) ** ((d - t0).days / 365.25) for d, a in flows)

    lo, hi = -0.9999, 10.0
    flo, fhi = npv(lo), npv(hi)
    if flo * fhi > 0:
        return None
    for _ in range(100):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-6:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


def compute(portfolio, wb, generated_at=None):
    """Return the `performance` dict. `portfolio` is the dict from load_portfolio."""
    import json as _json
    cfg = _json.loads((Path(__file__).resolve().parent / "config.json").read_text())
    fee = float(cfg.get("annual_fee_pct", 0.0)) / 100.0
    rf = float(cfg.get("risk_free_pct", 2.0)) / 100.0

    hist_path = DOCS / "history.json"
    history = _json.loads(hist_path.read_text()) if hist_path.exists() else []
    history = [h for h in history if h.get("total_value")]
    bench_path = DOCS / "benchmark.json"
    bench = _json.loads(bench_path.read_text()) if bench_path.exists() else {"series": [], "name": "Benchmark"}

    asof = _d(portfolio["as_of"])
    flows = _read_cash_flows(wb)

    p_steps = _twr_daily(history, flows)
    fee_daily = fee / 365.25
    p_steps_net = [(d, r - fee_daily) for (d, r) in p_steps]   # simple daily fee accrual
    b_steps = _bench_steps(bench.get("series", []))

    inception = _d(history[0]["date"]) if history else asof
    hist_days = (asof - inception).days

    # period returns — portfolio and benchmark over identical windows (clamped to
    # inception) and gated on the same history, for a fair like-for-like compare.
    p_gross = _period_returns(p_steps, asof, hist_days, inception)
    p_net = _period_returns(p_steps_net, asof, hist_days, inception)
    b_per = _period_returns(b_steps, asof, hist_days, inception)
    relative = {k: (None if p_net[k] is None or b_per[k] is None else p_net[k] - b_per[k]) for k in PERIODS}

    # stats from portfolio daily steps. Annualized risk-adjusted figures are only
    # statistically meaningful with >= ~1yr of history, so they are suppressed
    # below that; the cumulative since-inception return is always available.
    rs = [r for (_, r) in p_steps_net]
    si_cum = _link(p_steps_net) if p_steps_net else None
    enough_ann = hist_days >= 365
    si_ann = _annualize(si_cum, hist_days) if (si_cum is not None and enough_ann) else None
    vol = (_stdev(rs) * (252 ** 0.5)) if (_stdev(rs) and len(rs) >= 20) else None
    sharpe = ((si_ann - rf) / vol) if (vol and si_ann is not None and vol > 0) else None
    downs = [r for r in rs if r < 0]
    dvol = (_stdev(downs) * (252 ** 0.5)) if _stdev(downs) else None
    sortino = ((si_ann - rf) / dvol) if (dvol and si_ann is not None and dvol > 0) else None

    # drawdown series (portfolio, net)
    dd_series, idx_series = [], []
    v = 100.0
    peak = 100.0
    idx_series.append({"date": inception.isoformat(), "level": 100.0})
    for (d, r) in p_steps_net:
        v *= (1 + r)
        peak = max(peak, v)
        dd_series.append({"date": d.isoformat(), "dd": round((v / peak - 1) * 100, 3)})
        idx_series.append({"date": d.isoformat(), "level": round(v, 3)})
    max_dd = min((x["dd"] for x in dd_series), default=None)

    # calendar-year returns (portfolio net + benchmark)
    def cal(steps):
        years = {}
        for (d, r) in steps:
            years.setdefault(d.year, 1.0)
            years[d.year] *= (1 + r)
        return {y: round((v - 1) * 100, 2) for y, v in years.items()}
    cal_p, cal_b = cal(p_steps_net), cal(b_steps)
    cal_years = sorted(set(cal_p) | set(cal_b))

    # money-weighted return (IRR): external flows + current value as terminal inflow
    irr_flows = list(flows) + [(asof, portfolio["total_value"])]
    irr = _xirr(irr_flows) if flows else None

    # full benchmark series for the growth chart (already indexed to 100 at its
    # start); the front-end rebases both lines to the selected window.
    bench_aligned = bench.get("series", [])

    best = max(rs) if rs else None
    worst = min(rs) if rs else None

    return {
        "as_of": portfolio["as_of"],
        "inception": inception.isoformat(),
        "history_days": hist_days,
        "history_points": len(history),
        "benchmark_name": bench.get("name", "Benchmark"),
        "fee_pct": fee * 100,
        "periods": PERIODS,
        "period_returns": {"portfolio_net": p_net, "portfolio_gross": p_gross,
                           "benchmark": b_per, "relative": relative},
        "stats": {
            "annualized_return": si_ann, "since_inception_cum": si_cum,
            "volatility": vol, "sharpe": sharpe, "sortino": sortino,
            "max_drawdown": (max_dd / 100 if max_dd is not None else None),
            "best_period": best, "worst_period": worst,
            "pct_positive": (sum(1 for r in rs if r > 0) / len(rs)) if rs else None,
            "irr": irr,
        },
        "growth": {"portfolio": idx_series, "benchmark": bench_aligned},
        "drawdown": dd_series,
        "calendar": {"years": cal_years,
                     "portfolio": [cal_p.get(y) for y in cal_years],
                     "benchmark": [cal_b.get(y) for y in cal_years]},
        "generated_at": generated_at,
    }
