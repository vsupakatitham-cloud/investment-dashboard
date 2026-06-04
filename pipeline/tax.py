"""
tax.py — Tax & Lots metrics for the dashboard.

Builds a `tax` object: lot-level records, unrealized/realized gains, tax-wrapper
aggregates, and a Thai lock-up & maturity calendar (RMF / SSF / Thai ESG / LTF).

Design choices (confirmed):
  * Holding period starts from config `tax_inception_date` (2026-05-01) for every
    lot — globally adjustable; the per-lot value/cost come from the live engine.
  * Lock-up maturity uses the REAL "Sellable Year" on each MF lot, so the Thai
    wrapper calendar stays accurate independent of the inception assumption.
  * Realized gains come from the workbook "Realized" sheet (empty until you sell).
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "config.json"


def _read_realized(wb):
    rows = []
    if "Realized" not in wb.sheetnames:
        return rows
    ws = wb["Realized"]
    for r in range(5, ws.max_row + 1):
        d, holding, wrapper, units, proceeds, cost, gain = (ws.cell(r, c).value for c in range(1, 8))
        if d is None or holding in (None, ""):
            continue
        if isinstance(d, _dt.datetime):
            d = d.date().isoformat()
        try:
            g = float(gain) if gain not in (None, "") else (float(proceeds or 0) - float(cost or 0))
        except (TypeError, ValueError):
            g = 0.0
        rows.append({"date": str(d)[:10], "holding": holding, "wrapper": wrapper or "Taxable",
                     "proceeds": float(proceeds or 0), "cost": float(cost or 0), "gain": g})
    return rows


def compute(portfolio, wb):
    cfg = json.loads(CONFIG.read_text())
    inception = cfg.get("tax_inception_date", "2026-05-01")
    adv = set(cfg.get("tax_advantaged_wrappers", ["RMF", "SSF", "Thai ESG", "LTF"]))
    asof = _dt.date.fromisoformat(portfolio["as_of"])
    cur_year = asof.year
    inc_d = _dt.date.fromisoformat(inception)
    hold_days = (asof - inc_d).days

    lots = []
    for h in portfolio["holdings"]:
        wrapper = h["tax_status"] or "Taxable"
        sy_raw = (h.get("sellable_year") or "").strip()
        try:
            sell_year = int(float(sy_raw))
        except (ValueError, TypeError):
            sell_year = None
        is_adv = wrapper in adv
        locked = bool(is_adv and sell_year and sell_year > cur_year)
        lots.append({
            "name": h["name"], "custodian": h["custodian"], "type": h["asset_type"],
            "wrapper": wrapper, "acq_date": inception, "holding_days": hold_days,
            "units": h["quantity"], "cost": h["invested_thb"], "value": h["value_thb"],
            "unrealized": h["pnl_thb"], "unrealized_pct": h["pnl_pct"],
            "sellable_year": sell_year, "tax_advantaged": is_adv,
            "status": "Locked" if locked else "Available",
            "price_asof": h.get("price_asof", ""), "price_stale": bool(h.get("price_stale", False)),
        })

    tot_val = sum(l["value"] for l in lots)
    tot_cost = sum(l["cost"] for l in lots)
    tot_unreal = tot_val - tot_cost
    adv_val = sum(l["value"] for l in lots if l["tax_advantaged"])
    locked_val = sum(l["value"] for l in lots if l["status"] == "Locked")

    # by wrapper
    wraps = {}
    for l in lots:
        w = wraps.setdefault(l["wrapper"], {"wrapper": l["wrapper"], "count": 0, "invested": 0.0,
                                            "value": 0.0, "unrealized": 0.0, "locked": 0.0,
                                            "advantaged": l["tax_advantaged"], "next_unlock": None})
        w["count"] += 1
        w["invested"] += l["cost"]
        w["value"] += l["value"]
        w["unrealized"] += l["unrealized"]
        if l["status"] == "Locked":
            w["locked"] += l["value"]
            if l["sellable_year"] and (w["next_unlock"] is None or l["sellable_year"] < w["next_unlock"]):
                w["next_unlock"] = l["sellable_year"]
    for w in wraps.values():
        w["pct"] = w["value"] / tot_val if tot_val else 0
    by_wrapper = sorted(wraps.values(), key=lambda x: x["value"], reverse=True)

    # maturity calendar: ฿ unlocking per year for locked advantaged lots
    mat = {}
    available_in_wrapper = 0.0
    for l in lots:
        if not l["tax_advantaged"]:
            continue
        if l["status"] == "Locked" and l["sellable_year"]:
            mat[l["sellable_year"]] = mat.get(l["sellable_year"], 0.0) + l["value"]
        elif l["tax_advantaged"]:
            available_in_wrapper += l["value"]   # wrapper lot already past maturity
    maturity = [{"year": y, "value": round(v)} for y, v in sorted(mat.items())]

    realized = _read_realized(wb)
    realized_ytd = sum(r["gain"] for r in realized if r["date"][:4] == str(cur_year))

    # holding-period buckets (1yr split) — uniform from inception for now
    short = sum(l["value"] for l in lots if l["holding_days"] < 365)
    long = tot_val - short

    return {
        "as_of": portfolio["as_of"], "inception": inception, "holding_days": hold_days,
        "totals": {
            "value": round(tot_val), "cost": round(tot_cost),
            "unrealized": round(tot_unreal), "unrealized_pct": (tot_unreal / tot_cost) if tot_cost else 0,
            "realized_ytd": round(realized_ytd), "realized_count": len(realized),
            "tax_adv_value": round(adv_val), "tax_adv_pct": (adv_val / tot_val) if tot_val else 0,
            "locked_value": round(locked_val), "available_value": round(tot_val - locked_val),
            "available_in_wrapper": round(available_in_wrapper),
        },
        "by_wrapper": [{**w, "invested": round(w["invested"]), "value": round(w["value"]),
                        "unrealized": round(w["unrealized"]), "locked": round(w["locked"])}
                       for w in by_wrapper],
        "maturity": maturity,
        "holding_buckets": {"short": round(short), "long": round(long)},
        "lots": sorted(lots, key=lambda x: x["value"], reverse=True),
        "realized": realized,
    }
