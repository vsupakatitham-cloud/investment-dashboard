"""
build_site.py — Render the live portfolio into the static GitHub Pages site.

Outputs (into docs/, which GitHub Pages serves):
  * docs/data.json     : full portfolio snapshot (machine-readable)
  * docs/history.json  : appended weekly time-series for the trend chart
  * docs/index.html    : branded, self-contained client dashboard

The HTML embeds the snapshot inline so it renders even when opened as a local
file, and also re-fetches data.json so a hosted copy always shows the latest.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from portfolio import load_portfolio, WORKBOOK_DEFAULT

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
CONFIG = Path(__file__).resolve().parent / "config.json"


def update_history(snapshot: dict, asof: str) -> list:
    hist_path = DOCS / "history.json"
    history = []
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text())
        except json.JSONDecodeError:
            history = []
    row = {
        "date": asof,
        "total_value": round(snapshot["total_value"]),
        "total_invested": round(snapshot["total_invested"]),
        "total_pnl": round(snapshot["total_pnl"]),
        "pnl_pct": round(snapshot["total_pnl_pct"], 4),
        "mf_value": round(snapshot["mf_value"]),
        "eq_value": round(snapshot["eq_value"]),
        "crypto_value": round(snapshot["crypto_value"]),
        "fx_rate": snapshot["fx_rate"],
    }
    history = [h for h in history if h.get("date") != asof]  # replace same-day
    history.append(row)
    history.sort(key=lambda h: h["date"])
    hist_path.write_text(json.dumps(history, indent=2))
    return history


def build(workbook=WORKBOOK_DEFAULT, generated_at=None):
    DOCS.mkdir(exist_ok=True)
    cfg = json.loads(CONFIG.read_text())
    p = load_portfolio(workbook).to_dict()
    history = update_history(p, p["as_of"])

    generated_at = generated_at or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    payload = {"config": cfg, "portfolio": p, "history": history, "generated_at": generated_at}
    (DOCS / "data.json").write_text(json.dumps(payload, indent=2, default=str))

    html = HTML_TEMPLATE.replace("/*__DATA__*/null", json.dumps(payload, default=str))
    (DOCS / "index.html").write_text(html)
    return payload


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Private Banking Summary</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
  :root{
    --accent:#0b3d2e; --accent-soft:#15634a; --gold:#b9975b;
    --ink:#1d2421; --muted:#6b7772; --line:#e7e9e7; --bg:#f4f5f3; --card:#ffffff;
    --pos:#1a7f4b; --neg:#b3322c;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased}
  .wrap{max-width:1180px;margin:0 auto;padding:0 20px 64px}
  header.top{background:linear-gradient(135deg,var(--accent),var(--accent-soft));color:#fff;
       padding:30px 0 26px;border-bottom:3px solid var(--gold)}
  .head-inner{max-width:1180px;margin:0 auto;padding:0 20px;display:flex;justify-content:space-between;
       align-items:flex-end;gap:20px;flex-wrap:wrap}
  .brand{font-size:13px;letter-spacing:.22em;text-transform:uppercase;color:var(--gold);font-weight:600}
  h1{margin:6px 0 2px;font-size:26px;font-weight:600;letter-spacing:.01em}
  .client{font-size:14px;color:#dfe7e2}
  .asof{text-align:right;font-size:13px;color:#dfe7e2;line-height:1.7}
  .asof b{color:#fff;font-size:15px}
  .pill{display:inline-block;margin-top:6px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.25);
       padding:4px 10px;border-radius:20px;font-size:11px;color:#fff}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}
  .kpi{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 18px 16px;
       box-shadow:0 1px 2px rgba(0,0,0,.03)}
  .kpi .label{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--muted)}
  .kpi .value{font-size:26px;font-weight:600;margin-top:8px;letter-spacing:-.01em}
  .kpi .sub{font-size:12px;color:var(--muted);margin-top:4px}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
  .grid3{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:16px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-top:16px;
       box-shadow:0 1px 2px rgba(0,0,0,.03)}
  .card h2{margin:0 0 14px;font-size:14px;letter-spacing:.04em;text-transform:uppercase;color:var(--accent)}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:right;padding:8px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  th{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600}
  tbody tr:hover{background:#fafbfa}
  .tag{font-size:11px;color:var(--muted)}
  .bar{height:8px;border-radius:6px;background:#eef0ee;overflow:hidden}
  .bar>span{display:block;height:100%;background:var(--accent-soft)}
  .chartbox{position:relative;height:240px}
  .legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:12px;font-size:12px}
  .legend div{display:flex;align-items:center;gap:6px;color:var(--muted)}
  .dot{width:10px;height:10px;border-radius:3px;display:inline-block}
  .note{background:#fff8e8;border:1px solid #ecdcb0;color:#7a5d18;font-size:12px;border-radius:10px;
       padding:10px 12px;margin-top:16px}
  .controls{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}
  .controls button{font:inherit;font-size:12px;border:1px solid var(--line);background:#fff;color:var(--muted);
       padding:6px 12px;border-radius:20px;cursor:pointer}
  .controls button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  footer{margin-top:28px;font-size:11px;color:var(--muted);line-height:1.6;border-top:1px solid var(--line);padding-top:16px}
  @media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}.grid2,.grid3{grid-template-columns:1fr}}
</style>
</head>
<body>
<header class="top">
  <div class="head-inner">
    <div>
      <div class="brand" id="brand">TH INVESTMENT</div>
      <h1 id="title">Private Banking Summary</h1>
      <div class="client" id="client">Private Client Portfolio</div>
    </div>
    <div class="asof">
      <div>Valuation as of</div>
      <b id="asof">—</b>
      <div id="fxline"></div>
      <div class="pill" id="sched"></div>
    </div>
  </div>
</header>

<div class="wrap">
  <div class="kpis" id="kpis"></div>

  <div class="grid3">
    <div class="card">
      <h2>Asset Class Allocation</h2>
      <div class="chartbox"><canvas id="acChart"></canvas></div>
      <div class="legend" id="acLegend"></div>
    </div>
    <div class="card">
      <h2>Geography</h2>
      <div class="chartbox"><canvas id="geoChart"></canvas></div>
    </div>
    <div class="card">
      <h2>Tax Status</h2>
      <div class="chartbox"><canvas id="taxChart"></canvas></div>
    </div>
  </div>

  <div class="card">
    <h2>Portfolio Value — Weekly Trend</h2>
    <div class="chartbox" style="height:260px"><canvas id="trendChart"></canvas></div>
  </div>

  <div class="grid2">
    <div class="card">
      <h2>Top 10 Holdings</h2>
      <table id="topTable"><thead><tr><th>Holding</th><th>Custodian</th><th>Value</th><th>%</th><th>P&amp;L</th></tr></thead><tbody></tbody></table>
    </div>
    <div class="card">
      <h2>Theme / Sector Exposure</h2>
      <table id="themeTable"><thead><tr><th>Theme</th><th>Value</th><th>%</th><th></th></tr></thead><tbody></tbody></table>
    </div>
  </div>

  <div class="card">
    <h2>Holdings Detail</h2>
    <div class="controls" id="filters"></div>
    <table id="holdTable">
      <thead><tr><th>Name</th><th>Type</th><th>Class</th><th>Geo</th><th>Qty</th><th>Price</th><th>Invested</th><th>Value</th><th>P&amp;L</th><th>P&amp;L %</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div class="note" id="staleNote" style="display:none"></div>

  <footer>
    <div id="disclaimer"></div>
    <div style="margin-top:8px" id="genline"></div>
  </footer>
</div>

<script>
const DATA = /*__DATA__*/null;

const PALETTE = ["#0b3d2e","#15634a","#b9975b","#3f7d6a","#8aa399","#c9b27a","#5b8c7b","#d8c79b","#2c5446","#a9bdb4","#e0d3ad","#6f9a89"];
const fmt0 = n => (n<0?"-":"") + "฿" + Math.abs(Math.round(n)).toLocaleString("en-US");
const fmtPct = n => (n*100).toFixed(1) + "%";
const sign = n => (n>=0?"+":"") ;

function boot(payload){
  const cfg = payload.config, p = payload.portfolio, hist = payload.history || [];
  document.documentElement.style.setProperty('--accent', cfg.accent);
  document.documentElement.style.setProperty('--accent-soft', cfg.accent_soft);
  document.documentElement.style.setProperty('--gold', cfg.gold);
  document.getElementById('brand').textContent = (cfg.firm_name||"").toUpperCase();
  document.getElementById('title').textContent = cfg.report_title || "Private Banking Summary";
  document.getElementById('client').textContent = cfg.client_name + (cfg.client_ref? "  ·  "+cfg.client_ref : "");
  document.getElementById('asof').textContent = p.as_of;
  document.getElementById('fxline').textContent = "USD/THB  " + p.fx_rate;
  document.getElementById('sched').textContent = cfg.schedule_text || "";
  document.getElementById('disclaimer').textContent = cfg.disclaimer || "";
  document.getElementById('genline').textContent = "Generated " + payload.generated_at +
        "  ·  " + p.lot_counts.MF + " funds · " + p.lot_counts.Equity + " equity · " + p.lot_counts.Crypto + " crypto lots";

  // KPIs
  const pnlCls = p.total_pnl>=0?"pos":"neg";
  document.getElementById('kpis').innerHTML = `
    <div class="kpi"><div class="label">Total Portfolio Value</div><div class="value">${fmt0(p.total_value)}</div><div class="sub">Reporting currency: THB</div></div>
    <div class="kpi"><div class="label">Total Invested</div><div class="value">${fmt0(p.total_invested)}</div><div class="sub">Cost basis</div></div>
    <div class="kpi"><div class="label">Unrealized P&amp;L</div><div class="value ${pnlCls}">${sign(p.total_pnl)}${fmt0(p.total_pnl)}</div><div class="sub ${pnlCls}">${sign(p.total_pnl)}${fmtPct(p.total_pnl_pct)} cumulative</div></div>
    <div class="kpi"><div class="label">MF · Equities · Crypto</div><div class="value" style="font-size:18px">${fmt0(p.mf_value)}<br>${fmt0(p.eq_value)} · ${fmt0(p.crypto_value)}</div><div class="sub">By sleeve</div></div>`;

  // Donut helper
  function donut(id, rows, legendId){
    const top = rows.filter(r=>r.value>0);
    new Chart(document.getElementById(id),{type:'doughnut',
      data:{labels:top.map(r=>r.name),datasets:[{data:top.map(r=>r.value),
        backgroundColor:top.map((_,i)=>PALETTE[i%PALETTE.length]),borderWidth:2,borderColor:'#fff'}]},
      options:{cutout:'62%',plugins:{legend:{display:false},
        tooltip:{callbacks:{label:c=>` ${c.label}: ${fmt0(c.parsed)} (${(c.parsed/p.total_value*100).toFixed(1)}%)`}}}}});
    if(legendId){
      document.getElementById(legendId).innerHTML = top.slice(0,8).map((r,i)=>
        `<div><span class="dot" style="background:${PALETTE[i%PALETTE.length]}"></span>${r.name} · ${fmtPct(r.pct)}</div>`).join('');
    }
  }
  donut('acChart', p.by_asset_class, 'acLegend');
  donut('geoChart', p.by_geography, null);
  donut('taxChart', p.by_tax_status, null);

  // Trend
  const labels = hist.map(h=>h.date);
  new Chart(document.getElementById('trendChart'),{type:'line',
    data:{labels,datasets:[
      {label:'Total Value',data:hist.map(h=>h.total_value),borderColor:cfg.accent,backgroundColor:'rgba(11,61,46,.08)',fill:true,tension:.25,pointRadius:3},
      {label:'Invested',data:hist.map(h=>h.total_invested),borderColor:cfg.gold,borderDash:[5,4],fill:false,tension:.25,pointRadius:0}
    ]},
    options:{plugins:{legend:{position:'bottom',labels:{boxWidth:12,font:{size:11}}}},
      scales:{y:{ticks:{callback:v=>'฿'+(v/1e6).toFixed(1)+'M'}}}}});
  if(hist.length<2){
    document.getElementById('trendChart').parentElement.insertAdjacentHTML('beforeend',
      '<div class="tag" style="position:absolute;top:8px;right:8px">History builds each Saturday — one point so far</div>');
  }

  // Top 10
  document.querySelector('#topTable tbody').innerHTML = p.top_holdings.map(h=>{
    const c = h.pnl>=0?'pos':'neg';
    return `<tr><td>${h.name}</td><td class="tag">${h.custodian||''}</td><td>${fmt0(h.value)}</td><td>${fmtPct(h.pct)}</td><td class="${c}">${sign(h.pnl)}${fmtPct(h.pnl_pct)}</td></tr>`;
  }).join('');

  // Theme table
  const themeMax = Math.max(...p.by_theme.map(t=>t.value),1);
  document.querySelector('#themeTable tbody').innerHTML = p.by_theme.filter(t=>t.value>0).slice(0,14).map(t=>
    `<tr><td>${t.name}</td><td>${fmt0(t.value)}</td><td>${fmtPct(t.pct)}</td>
      <td style="width:120px"><div class="bar"><span style="width:${(t.value/themeMax*100).toFixed(0)}%"></span></div></td></tr>`).join('');

  // Holdings detail with filter (pooled by name)
  const pool = {};
  p.holdings.forEach(h=>{
    const k=h.asset_type+'|'+h.name+'|'+h.custodian;
    const g = pool[k]||(pool[k]={name:h.name,asset_type:h.asset_type,asset_class:h.asset_class,geography:h.geography,
      quantity:0,price:h.price,invested_thb:0,value_thb:0,pnl_thb:0});
    g.quantity+=h.quantity; g.invested_thb+=h.invested_thb; g.value_thb+=h.value_thb; g.pnl_thb+=h.pnl_thb;
  });
  const rows = Object.values(pool).sort((a,b)=>b.value_thb-a.value_thb);
  const types = ['All','MF','Equity','Crypto'];
  document.getElementById('filters').innerHTML = types.map((t,i)=>
    `<button class="${i===0?'active':''}" data-t="${t}">${t==='MF'?'Mutual Funds':t==='Equity'?'Equities':t}</button>`).join('');
  function renderHold(filter){
    const tb = document.querySelector('#holdTable tbody');
    tb.innerHTML = rows.filter(r=>filter==='All'||r.asset_type===filter).map(r=>{
      const pct = r.invested_thb? r.pnl_thb/r.invested_thb : 0;
      const c = r.pnl_thb>=0?'pos':'neg';
      return `<tr><td>${r.name}</td><td class="tag">${r.asset_type}</td><td class="tag">${r.asset_class||''}</td>
        <td class="tag">${r.geography||''}</td><td>${r.quantity.toLocaleString('en-US',{maximumFractionDigits:4})}</td>
        <td>${r.price.toLocaleString('en-US',{maximumFractionDigits:4})}</td>
        <td>${fmt0(r.invested_thb)}</td><td>${fmt0(r.value_thb)}</td>
        <td class="${c}">${sign(r.pnl_thb)}${fmt0(r.pnl_thb)}</td><td class="${c}">${sign(r.pnl_thb)}${fmtPct(pct)}</td></tr>`;
    }).join('');
  }
  renderHold('All');
  document.getElementById('filters').addEventListener('click',e=>{
    if(e.target.tagName!=='BUTTON')return;
    document.querySelectorAll('#filters button').forEach(b=>b.classList.remove('active'));
    e.target.classList.add('active'); renderHold(e.target.dataset.t);
  });

  // Stale prices note
  if(p.stale_prices && p.stale_prices.length){
    const n=document.getElementById('staleNote'); n.style.display='block';
    n.textContent = "Note: "+p.stale_prices.length+" holding(s) use a carried-forward price pending a manual NAV update: "+p.stale_prices.join(", ");
  }
}

// Prefer fresh data.json when hosted; fall back to embedded snapshot.
fetch('data.json',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject()).then(boot).catch(()=>{ if(DATA) boot(DATA); });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", default=str(WORKBOOK_DEFAULT))
    args = ap.parse_args()
    out = build(args.workbook)
    pf = out["portfolio"]
    print(f"Built docs/index.html + data.json — total ฿{pf['total_value']:,.0f}, "
          f"{len(out['history'])} history point(s).")
