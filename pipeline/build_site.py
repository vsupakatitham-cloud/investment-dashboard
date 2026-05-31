"""
build_site.py — Render the live portfolio into the static GitHub Pages site (v2).

Outputs (into docs/, which GitHub Pages serves):
  * docs/data.json     : full portfolio snapshot (machine-readable)
  * docs/history.json  : appended weekly time-series for the trend/performance views
  * docs/index.html    : branded, self-contained client dashboard (v2)

v2 design: clean institutional light, tabbed sections (Overview / Allocation /
Holdings / Performance / Risk), with concentration, currency and risk-posture
analytics. The page embeds the snapshot inline so it renders as a local file and
also re-fetches data.json so a hosted copy always shows the latest. Performance
and week-over-week visuals use the REAL accumulating Weekly Snapshot history and
degrade gracefully to a "history is building" state until a second point exists.
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
    --bg:#f6f7f8; --surface:#ffffff; --surface-2:#fbfcfc;
    --border:#e6e8eb; --border-2:#d7dbe0;
    --ink:#14181c; --muted:#69727b; --faint:#98a0a8;
    --accent:#0b3d2e; --accent-2:#15634a; --accent-tint:#eef3f1;
    --pos:#0f7a44; --pos-bg:#e8f4ee; --neg:#c0392b; --neg-bg:#fbecea;
    --gold:#b9975b;
    --r:10px; --shadow:0 1px 2px rgba(16,24,32,.04),0 1px 1px rgba(16,24,32,.03);
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
       background:var(--bg);color:var(--ink);-webkit-font-smoothing:antialiased;font-size:14px;line-height:1.45;overflow-x:hidden}
  .num{font-variant-numeric:tabular-nums;font-feature-settings:"tnum" 1}
  .pos{color:var(--pos)} .neg{color:var(--neg)}
  a{color:inherit}

  .topbar{position:sticky;top:0;z-index:40;background:rgba(255,255,255,.92);backdrop-filter:saturate(1.4) blur(8px);
    border-bottom:1px solid var(--border)}
  .topbar .in{max-width:1240px;margin:0 auto;padding:11px 22px;display:flex;align-items:center;gap:18px}
  .wordmark{display:flex;align-items:center;gap:10px;font-weight:680;letter-spacing:-.01em}
  .logo{width:26px;height:26px;border-radius:7px;background:linear-gradient(135deg,var(--accent),var(--accent-2));
    display:grid;place-items:center;color:#fff;font-size:12px;font-weight:700}
  .who{color:var(--muted);font-size:12.5px;padding-left:14px;border-left:1px solid var(--border);margin-left:2px}
  .who b{color:var(--ink);font-weight:620}
  .spacer{flex:1}
  .meta{display:flex;gap:18px;align-items:center;font-size:12.5px;color:var(--muted)}
  .meta .v{color:var(--ink);font-weight:600}
  .tag{font-size:10.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--gold);
    border:1px solid #e7dcc3;background:#fbf7ee;padding:3px 8px;border-radius:20px}

  .tabs{position:sticky;top:49px;z-index:30;background:var(--bg);border-bottom:1px solid var(--border)}
  .tabs .in{max-width:1240px;margin:0 auto;padding:0 22px;display:flex;gap:4px;overflow-x:auto}
  .tab{appearance:none;border:0;background:none;font:inherit;font-size:13.5px;color:var(--muted);
    padding:13px 14px 11px;cursor:pointer;border-bottom:2px solid transparent;white-space:nowrap;font-weight:550}
  .tab:hover{color:var(--ink)}
  .tab.active{color:var(--accent);border-bottom-color:var(--accent);font-weight:640}

  .wrap{max-width:1240px;margin:0 auto;padding:22px}
  section[hidden]{display:none}
  .row{display:grid;gap:16px}
  .g4{grid-template-columns:repeat(4,1fr)} .g3{grid-template-columns:repeat(3,1fr)}
  .g2{grid-template-columns:repeat(2,1fr)} .g23{grid-template-columns:1.4fr 1fr}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow)}
  .card.pad{padding:18px}
  .card h3{margin:0 0 2px;font-size:13px;font-weight:640;letter-spacing:.01em}
  .card .hint{color:var(--faint);font-size:11.5px;margin-bottom:12px}
  .head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:12px}
  .head h3{margin:0}
  .mini{font-size:11.5px;color:var(--faint)}

  .kpi{padding:16px 16px 12px;position:relative;overflow:hidden}
  .kpi .label{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
  .kpi .val{font-size:25px;font-weight:680;letter-spacing:-.02em;margin-top:7px}
  .delta{display:inline-flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;margin-top:8px;
    padding:2px 7px;border-radius:20px}
  .delta.up{color:var(--pos);background:var(--pos-bg)} .delta.down{color:var(--neg);background:var(--neg-bg)}
  .spark{position:absolute;right:10px;bottom:10px;width:74px;height:30px;opacity:.9}

  .barstack{height:22px;border-radius:6px;overflow:hidden;display:flex;background:var(--border)}
  .barstack i{display:block;height:100%}
  .legend{display:flex;flex-wrap:wrap;gap:8px 16px;margin-top:14px;font-size:12px;color:var(--muted)}
  .legend div{display:flex;align-items:center;gap:7px}
  .dot{width:9px;height:9px;border-radius:3px;display:inline-block}
  table{width:100%;border-collapse:collapse}
  th,td{text-align:right;padding:9px 10px;font-size:12.5px;white-space:nowrap}
  th:first-child,td:first-child{text-align:left}
  thead th{font-size:10.5px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);font-weight:600;
    border-bottom:1px solid var(--border-2);cursor:pointer;user-select:none}
  tbody td{border-bottom:1px solid var(--border)}
  tbody tr:hover{background:var(--surface-2)}
  .name{font-weight:600}
  .sub{color:var(--faint);font-size:11px}
  .chip{display:inline-block;font-size:10.5px;color:var(--muted);background:#f1f3f5;border:1px solid var(--border);
    padding:1px 7px;border-radius:5px}
  .wbar{height:6px;border-radius:4px;background:var(--accent-tint);overflow:hidden;min-width:40px}
  .wbar>i{display:block;height:100%;background:var(--accent-2)}
  .scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
  .chartbox{position:relative;height:260px}

  .toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:14px}
  .search{flex:1;min-width:180px;border:1px solid var(--border-2);border-radius:8px;padding:8px 11px;font:inherit;font-size:13px;background:#fff}
  .seg{display:inline-flex;border:1px solid var(--border-2);border-radius:8px;overflow:hidden}
  .seg button{appearance:none;border:0;background:#fff;font:inherit;font-size:12.5px;color:var(--muted);padding:8px 12px;cursor:pointer;border-left:1px solid var(--border)}
  .seg button:first-child{border-left:0}
  .seg button.active{background:var(--accent);color:#fff}

  .stat{padding:16px}
  .stat .k{font-size:11px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted)}
  .stat .v{font-size:23px;font-weight:680;margin-top:6px;letter-spacing:-.01em}
  .stat .d{font-size:11.5px;color:var(--faint);margin-top:3px}
  .conc ul{margin:0;padding:0}
  .conc li{display:grid;grid-template-columns:130px 1fr 56px;gap:10px;align-items:center;padding:6px 0;list-style:none}
  .conc .nm{font-size:12.5px;font-weight:560}
  .ribbon{display:flex;height:30px;border-radius:7px;overflow:hidden;border:1px solid var(--border)}
  .ribbon i{display:flex;align-items:center;justify-content:center;font-size:10.5px;color:#fff;font-weight:600;min-width:0}

  .note{font-size:11.5px;color:var(--faint);margin-top:10px}
  .empty{padding:26px;text-align:center;color:var(--muted);font-size:13px}
  .empty .pillnote{display:inline-block;background:#fff;border:1px dashed var(--border-2);color:var(--muted);
    font-size:12px;border-radius:20px;padding:6px 14px;margin-top:8px}
  footer{max-width:1240px;margin:8px auto 40px;padding:0 22px;color:var(--faint);font-size:11px;line-height:1.6}

  @media(max-width:980px){.g4{grid-template-columns:repeat(2,1fr)}.g3,.g2,.g23{grid-template-columns:1fr}}
  @media(max-width:560px){
    .topbar{position:static}
    .topbar .in{flex-wrap:wrap;gap:8px 14px;padding:10px 14px}
    .who{padding-left:0;border-left:0;margin-left:0}
    .meta{gap:12px;font-size:12px} .tag{display:none}
    .tabs{top:0;position:sticky}
    .wrap{padding:16px 14px}
    .g4{grid-template-columns:1fr 1fr}
    .kpi .val{font-size:21px} .spark{display:none}
  }
</style>
</head>
<body>
<div class="topbar"><div class="in">
  <div class="wordmark"><span class="logo" id="logo">TH</span> <span id="firm">TH Investment</span></div>
  <div class="who"><b id="client">Private Client Portfolio</b> · <span id="ref"></span></div>
  <div class="spacer"></div>
  <div class="meta">
    <div>As of <span class="v" id="asof">—</span></div>
    <div>USD/THB <span class="v num" id="fx">—</span></div>
    <span class="tag">Confidential</span>
  </div>
</div></div>

<div class="tabs"><div class="in" id="tabnav"></div></div>

<div class="wrap">
  <section data-tab="Overview">
    <div class="row g4" id="kpis" style="margin-bottom:16px"></div>
    <div class="row g23" style="margin-bottom:16px">
      <div class="card pad">
        <div class="head"><h3>Asset Allocation</h3><span class="mini" id="acTotal"></span></div>
        <div class="barstack" id="acBar"></div>
        <div class="legend" id="acLegend"></div>
      </div>
      <div class="card pad">
        <div class="head"><h3>Top Movers</h3><span class="mini">by return</span></div>
        <div id="movers"></div>
      </div>
    </div>
    <div class="row g23">
      <div class="card pad">
        <div class="head"><h3>Performance</h3><span class="mini">value vs invested</span></div>
        <div id="ovPerfWrap" class="chartbox" style="height:230px"><canvas id="ovPerf"></canvas></div>
      </div>
      <div class="card pad">
        <div class="head"><h3>Largest Holdings</h3><span class="mini">top 6</span></div>
        <div class="scroll"><table id="ovHold"></table></div>
      </div>
    </div>
  </section>

  <section data-tab="Allocation" hidden>
    <div class="row g3" style="margin-bottom:16px">
      <div class="card pad"><h3>By Asset Class</h3><div class="hint">share of portfolio</div><div class="chartbox"><canvas id="acDonut"></canvas></div></div>
      <div class="card pad"><h3>By Geography</h3><div class="hint">look-through region</div><div id="geoBars"></div></div>
      <div class="card pad"><h3>By Tax Wrapper</h3><div class="hint">Thai vehicle type</div><div class="chartbox"><canvas id="taxDonut"></canvas></div></div>
    </div>
    <div class="row g2">
      <div class="card pad"><div class="head"><h3>Asset Class Detail</h3></div><div class="scroll"><table id="acTable"></table></div></div>
      <div class="card pad"><div class="head"><h3>Theme / Sector Exposure</h3></div><div id="themeBars"></div></div>
    </div>
  </section>

  <section data-tab="Holdings" hidden>
    <div class="card pad">
      <div class="toolbar">
        <input class="search" id="search" placeholder="Search holdings, class, geography…"/>
        <div class="seg" id="typeSeg"></div>
        <span class="mini" id="holdCount"></span>
      </div>
      <div class="scroll"><table id="holdTable"></table></div>
    </div>
  </section>

  <section data-tab="Performance" hidden>
    <div class="row g4" id="perfStats" style="margin-bottom:16px"></div>
    <div class="card pad" style="margin-bottom:16px">
      <div class="head"><h3>Portfolio Value</h3><span class="mini">value vs cost basis, weekly</span></div>
      <div id="perfLineWrap" class="chartbox" style="height:300px"><canvas id="perfLine"></canvas></div>
    </div>
    <div class="row g2">
      <div class="card pad"><div class="head"><h3>Weekly P&amp;L Change</h3></div><div id="perfBarsWrap" class="chartbox"><canvas id="perfBars"></canvas></div></div>
      <div class="card pad"><div class="head"><h3>Cumulative Return</h3></div><div id="perfCumWrap" class="chartbox"><canvas id="perfCum"></canvas></div></div>
    </div>
  </section>

  <section data-tab="Risk" hidden>
    <div class="row g4" id="riskStats" style="margin-bottom:16px"></div>
    <div class="row g2" style="margin-bottom:16px">
      <div class="card pad">
        <div class="head"><h3>Single-Name Concentration</h3><span class="mini">top 10 weights</span></div>
        <div class="conc"><ul id="concList"></ul></div>
      </div>
      <div class="card pad">
        <div class="head"><h3>Currency Exposure</h3><span class="mini">pre-hedge</span></div>
        <div class="barstack" id="fxBar" style="height:26px"></div>
        <div class="legend" id="fxLegend"></div>
        <div class="note">USD exposure is unhedged and revalues with the USD/THB rate.</div>
      </div>
    </div>
    <div class="card pad">
      <div class="head"><h3>Risk Posture</h3><span class="mini">by asset-class risk band</span></div>
      <div class="ribbon" id="riskRibbon"></div>
      <div class="legend" id="riskLegend"></div>
    </div>
  </section>
</div>

<footer id="foot"></footer>

<script>
const EMBEDDED = /*__DATA__*/null;
const PAL = ["#0b3d2e","#15634a","#3f7d6a","#b9975b","#6f9a89","#8aa399","#c9b27a","#a9bdb4","#d8c79b","#2c5446","#e0d3ad","#5b8c7b"];
const B="฿";
const f0=n=>(n<0?"-":"")+B+Math.abs(Math.round(n)).toLocaleString("en-US");
const fM=n=>B+(n/1e6).toFixed(2)+"M";
const pc=n=>(n*100).toFixed(1)+"%";
const sg=n=>n>=0?"+":"";
const md=iso=>{const p=(iso||"").split("-");return p.length===3?(+p[1])+"/"+(+p[2]):iso;};
const charts={};

function boot(PAYLOAD){
  const P=PAYLOAD.portfolio, CFG=PAYLOAD.config||{};
  const HIST=(PAYLOAD.history||[]).slice().sort((a,b)=>a.date<b.date?-1:1);
  const hasHist=HIST.length>=2;
  const H={labels:HIST.map(h=>md(h.date)),value:HIST.map(h=>h.total_value),invested:HIST.map(h=>h.total_invested)};
  const TABS=["Overview","Allocation","Holdings","Performance","Risk"];

  if(CFG.accent)document.documentElement.style.setProperty("--accent",CFG.accent);
  if(CFG.accent_soft)document.documentElement.style.setProperty("--accent-2",CFG.accent_soft);
  if(CFG.gold)document.documentElement.style.setProperty("--gold",CFG.gold);

  const firm=CFG.firm_name||"TH Investment";
  document.getElementById("firm").textContent=firm;
  document.getElementById("logo").textContent=(CFG.logo_text||firm.split(/\s+/).map(w=>w[0]).join("")).slice(0,2).toUpperCase();
  document.getElementById("client").textContent=CFG.client_name||"Private Client Portfolio";
  document.getElementById("ref").textContent=CFG.client_ref||"";
  document.getElementById("asof").textContent=P.as_of;
  document.getElementById("fx").textContent=P.fx_rate;
  document.title=(CFG.report_title||"Private Banking Summary");
  document.getElementById("foot").innerHTML=
    `<div>${CFG.disclaimer||""}</div>
     <div style="margin-top:8px">${CFG.schedule_text||""} · Generated ${PAYLOAD.generated_at||""} ·
       ${P.lot_counts.MF} funds · ${P.lot_counts.Equity} equity · ${P.lot_counts.Crypto} crypto lots</div>`;

  // pooled holdings
  const pool={};
  P.holdings.forEach(h=>{const k=h.asset_type+"|"+h.name;
    const g=pool[k]||(pool[k]={name:h.name,type:h.asset_type,ac:h.asset_class,geo:h.geography,
      cur:h.currency||"THB",qty:0,price:h.price,inv:0,val:0});
    g.qty+=h.quantity;g.inv+=h.invested_thb;g.val+=h.value_thb;});
  const POOL=Object.values(pool).map(h=>({...h,pnl:h.val-h.inv,pnlpct:h.inv?(h.val-h.inv)/h.inv:0,wt:P.total_value?h.val/P.total_value:0}))
    .sort((a,b)=>b.val-a.val);

  // tabs
  const nav=document.getElementById("tabnav");nav.innerHTML="";
  const drawn={};
  TABS.forEach((t,i)=>{const b=document.createElement("button");b.className="tab"+(i?"":" active");b.textContent=t;
    b.onclick=()=>{document.querySelectorAll(".tab").forEach(x=>x.classList.remove("active"));b.classList.add("active");
      document.querySelectorAll("section[data-tab]").forEach(s=>s.hidden=s.dataset.tab!==t);window.scrollTo(0,0);draw(t);};
    nav.appendChild(b);});

  // KPIs
  const wow=hasHist?(P.total_value-HIST[HIST.length-2].total_value)/HIST[HIST.length-2].total_value:null;
  function spark(series){
    if(!series||series.length<2)return"";
    const w=74,h=30,mn=Math.min(...series),mx=Math.max(...series),r=mx-mn||1;
    const pts=series.map((v,i)=>[i/(series.length-1)*w,h-((v-mn)/r)*(h-4)-2]);
    const up=series[series.length-1]>=series[0];
    const d=pts.map((p,i)=>(i?"L":"M")+p[0].toFixed(1)+" "+p[1].toFixed(1)).join(" ");
    return `<svg class="spark" viewBox="0 0 ${w} ${h}"><path d="${d}" fill="none" stroke="${up?'#0f7a44':'#c0392b'}" stroke-width="1.6"/></svg>`;
  }
  const kpis=[
    {label:"Total Portfolio Value",val:f0(P.total_value),d:wow,spark:H.value},
    {label:"Invested (Cost Basis)",val:f0(P.total_invested),sub:"THB"},
    {label:"Unrealized P&L",val:sg(P.total_pnl)+f0(P.total_pnl),cls:P.total_pnl>=0?"pos":"neg",sub:"since inception"},
    {label:"Total Return",val:sg(P.total_pnl_pct)+pc(P.total_pnl_pct),cls:P.total_pnl_pct>=0?"pos":"neg",d:wow,spark:H.value},
  ];
  document.getElementById("kpis").innerHTML=kpis.map(k=>`
    <div class="card kpi">
      <div class="label">${k.label}</div>
      <div class="val num ${k.cls||''}">${k.val}</div>
      ${k.d!=null?`<div class="delta ${k.d>=0?'up':'down'}">${k.d>=0?'▲':'▼'} ${pc(Math.abs(k.d))} WoW</div>`
                 :`<div class="mini" style="margin-top:8px">${k.sub||''}</div>`}
      ${k.spark?spark(k.spark):''}
    </div>`).join("");

  // allocation bar
  const ac=P.by_asset_class.filter(r=>r.value>0);
  document.getElementById("acTotal").textContent=f0(P.total_value);
  document.getElementById("acBar").innerHTML=ac.map((r,i)=>`<i style="width:${r.pct*100}%;background:${PAL[i%PAL.length]}" title="${r.name} ${pc(r.pct)}"></i>`).join("");
  document.getElementById("acLegend").innerHTML=ac.map((r,i)=>`<div><span class="dot" style="background:${PAL[i%PAL.length]}"></span>${r.name} · <span class="num">${pc(r.pct)}</span></div>`).join("");

  // movers
  const mv=POOL.filter(h=>h.val>50000);
  const up3=[...mv].sort((a,b)=>b.pnlpct-a.pnlpct).slice(0,3);
  const dn3=[...mv].sort((a,b)=>a.pnlpct-b.pnlpct).slice(0,3);
  const mrow=h=>`<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)">
    <div><span class="name">${h.name}</span> <span class="sub">${h.type}</span></div>
    <div class="num ${h.pnl>=0?'pos':'neg'}">${sg(h.pnlpct)}${pc(h.pnlpct)}</div></div>`;
  document.getElementById("movers").innerHTML=
    `<div class="mini" style="margin:2px 0 4px">Gainers</div>${up3.map(mrow).join("")}
     <div class="mini" style="margin:12px 0 4px">Laggards</div>${dn3.map(mrow).join("")}`;

  // largest holdings
  document.getElementById("ovHold").innerHTML=
    `<thead><tr><th>Holding</th><th>Value</th><th>Wt</th><th>Return</th></tr></thead><tbody>`+
    POOL.slice(0,6).map(h=>`<tr><td><span class="name">${h.name}</span> <span class="sub">${h.type}</span></td>
     <td class="num">${f0(h.val)}</td><td class="num">${pc(h.wt)}</td>
     <td class="num ${h.pnl>=0?'pos':'neg'}">${sg(h.pnlpct)}${pc(h.pnlpct)}</td></tr>`).join("")+`</tbody>`;

  // ---- helpers for tab charts ----
  function donut(id,rows){
    if(charts[id])charts[id].destroy();
    const top=rows.filter(r=>r.value>0);
    charts[id]=new Chart(document.getElementById(id),{type:"doughnut",
      data:{labels:top.map(r=>r.name),datasets:[{data:top.map(r=>r.value),backgroundColor:top.map((_,i)=>PAL[i%PAL.length]),borderColor:"#fff",borderWidth:2}]},
      options:{cutout:"64%",plugins:{legend:{position:"bottom",labels:{boxWidth:9,font:{size:11},padding:9}},
        tooltip:{callbacks:{label:c=>" "+c.label+": "+pc(P.total_value?c.parsed/P.total_value:0)}}}}});
  }
  function bars(elId,rows,max){
    document.getElementById(elId).innerHTML=rows.filter(r=>r.value>0).slice(0,12).map((r,i)=>`
      <div style="display:grid;grid-template-columns:120px 1fr 52px;gap:10px;align-items:center;padding:5px 0">
        <div style="font-size:12.5px">${r.name}</div>
        <div class="wbar"><i style="width:${max?(r.value/max*100).toFixed(0):0}%;background:${PAL[i%PAL.length]}"></i></div>
        <div class="num" style="text-align:right;font-size:12px">${pc(r.pct)}</div></div>`).join("");
  }
  const buildingMsg=`<div class="empty">Performance history is building.<br>
    <span class="pillnote">One weekly snapshot so far — charts populate each Saturday.</span></div>`;

  // holdings table
  let hsort={k:"val",dir:-1},hfilter="All",hq="";
  const seg=document.getElementById("typeSeg");seg.innerHTML="";
  ["All","MF","Equity","Crypto"].forEach((t,i)=>{const b=document.createElement("button");
    b.className=i?"":"active";b.textContent=t==="MF"?"Funds":t;b.onclick=()=>{hfilter=t;
     [...seg.children].forEach(x=>x.classList.remove("active"));b.classList.add("active");renderHold();};seg.appendChild(b);});
  document.getElementById("search").addEventListener("input",e=>{hq=e.target.value.toLowerCase();renderHold();});
  const HCOLS=[["name","Holding"],["type","Type"],["ac","Class"],["geo","Geo"],["qty","Units"],["price","Price"],
    ["inv","Invested"],["val","Value"],["wt","Wt"],["pnl","P&L"],["pnlpct","P&L %"]];
  function renderHold(){
    let rows=POOL.filter(h=>(hfilter==="All"||h.type===hfilter)&&
      (!hq||(h.name+" "+h.ac+" "+h.geo).toLowerCase().includes(hq)));
    rows.sort((a,b)=>(a[hsort.k]>b[hsort.k]?1:-1)*hsort.dir);
    document.getElementById("holdCount").textContent=rows.length+" of "+POOL.length+" positions";
    const th=HCOLS.map(c=>`<th data-k="${c[0]}">${c[1]}${hsort.k===c[0]?(hsort.dir<0?" ↓":" ↑"):""}</th>`).join("");
    document.getElementById("holdTable").innerHTML=`<thead><tr>${th}</tr></thead><tbody>`+
      rows.map(h=>`<tr>
        <td><span class="name">${h.name}</span></td><td><span class="chip">${h.type}</span></td>
        <td class="sub">${h.ac||""}</td><td class="sub">${h.geo||""}</td>
        <td class="num">${h.qty.toLocaleString("en-US",{maximumFractionDigits:3})}</td>
        <td class="num">${h.price.toLocaleString("en-US",{maximumFractionDigits:2})}</td>
        <td class="num">${f0(h.inv)}</td><td class="num">${f0(h.val)}</td>
        <td class="num">${pc(h.wt)}</td>
        <td class="num ${h.pnl>=0?'pos':'neg'}">${sg(h.pnl)}${f0(h.pnl)}</td>
        <td class="num ${h.pnl>=0?'pos':'neg'}">${sg(h.pnlpct)}${pc(h.pnlpct)}</td></tr>`).join("")+`</tbody>`;
    document.querySelectorAll("#holdTable th").forEach(t=>t.onclick=()=>{const k=t.dataset.k;
      if(hsort.k===k)hsort.dir*=-1;else{hsort.k=k;hsort.dir=-1;}renderHold();});
  }

  // performance
  function perfCharts(){
    if(!hasHist){document.getElementById("perfLineWrap").innerHTML=buildingMsg;
      document.getElementById("perfBarsWrap").innerHTML="";document.getElementById("perfCumWrap").innerHTML="";
      document.getElementById("perfStats").innerHTML=
        [["Weeks Tracked",HIST.length||1,"snapshot"],["Return Since Inception",sg(P.total_pnl_pct)+pc(P.total_pnl_pct),"cumulative"],
         ["Total P&L",sg(P.total_pnl)+f0(P.total_pnl),"unrealized"],["Largest Holding",pc(POOL[0]?POOL[0].wt:0),POOL[0]?POOL[0].name:""]]
        .map(s=>`<div class="card stat"><div class="k">${s[0]}</div><div class="v num">${s[1]}</div><div class="d">${s[2]}</div></div>`).join("");
      return;}
    const grid={color:"#eef0f2"},tick={font:{size:11},color:"#69727b"};
    const mk=(id,cfg)=>{if(charts[id])charts[id].destroy();charts[id]=new Chart(document.getElementById(id),cfg);};
    mk("perfLine",{type:"line",data:{labels:H.labels,datasets:[
      {label:"Value",data:H.value,borderColor:"#0b3d2e",backgroundColor:"rgba(11,61,46,.07)",fill:true,tension:.3,pointRadius:2,borderWidth:2},
      {label:"Invested",data:H.invested,borderColor:"#b9975b",borderDash:[5,4],fill:false,tension:.3,pointRadius:0,borderWidth:1.5}]},
      options:{plugins:{legend:{position:"bottom",labels:{boxWidth:10,font:{size:11}}}},
        scales:{y:{grid,ticks:{...tick,callback:v=>fM(v)}},x:{grid:{display:false},ticks:tick}}}});
    const chg=H.value.map((v,i)=>i?v-H.value[i-1]:0);
    mk("perfBars",{type:"bar",data:{labels:H.labels,datasets:[{data:chg,backgroundColor:chg.map(v=>v>=0?"#0f7a44":"#c0392b")}]},
      options:{plugins:{legend:{display:false}},scales:{y:{grid,ticks:{...tick,callback:v=>(v/1e3).toFixed(0)+"k"}},x:{grid:{display:false},ticks:tick}}}});
    const base=H.invested[0]||H.value[0]||1;
    const cum=H.value.map(v=>(v-base)/base);
    mk("perfCum",{type:"line",data:{labels:H.labels,datasets:[{data:cum,borderColor:"#15634a",backgroundColor:"rgba(21,99,74,.08)",fill:true,tension:.3,pointRadius:2,borderWidth:2}]},
      options:{plugins:{legend:{display:false}},scales:{y:{grid,ticks:{...tick,callback:v=>pc(v)}},x:{grid:{display:false},ticks:tick}}}});
    const chgArr=chg.slice(1);
    document.getElementById("perfStats").innerHTML=[
      ["Weeks Tracked",H.labels.length,"snapshots"],
      ["Best Week",sg(Math.max(...chgArr))+f0(Math.max(...chgArr)),"value change"],
      ["Worst Week",f0(Math.min(...chgArr)),"value change"],
      ["Return Since Start",sg((P.total_value-H.value[0])/H.value[0])+pc((P.total_value-H.value[0])/H.value[0]),H.labels.length+" weeks"],
    ].map(s=>`<div class="card stat"><div class="k">${s[0]}</div><div class="v num">${s[1]}</div><div class="d">${s[2]}</div></div>`).join("");
  }

  // overview mini perf
  function perfMini(){
    if(!hasHist){document.getElementById("ovPerfWrap").innerHTML=buildingMsg;return;}
    if(charts.ovPerf)charts.ovPerf.destroy();
    charts.ovPerf=new Chart(document.getElementById("ovPerf"),{type:"line",
     data:{labels:H.labels,datasets:[
       {label:"Value",data:H.value,borderColor:"#0b3d2e",backgroundColor:"rgba(11,61,46,.07)",fill:true,tension:.3,pointRadius:0,borderWidth:2},
       {label:"Invested",data:H.invested,borderColor:"#b9975b",borderDash:[5,4],fill:false,tension:.3,pointRadius:0,borderWidth:1.5}]},
     options:{plugins:{legend:{position:"bottom",labels:{boxWidth:10,font:{size:11}}}},
       scales:{y:{grid:{color:"#eef0f2"},ticks:{font:{size:11},color:"#69727b",callback:v=>fM(v)}},x:{grid:{display:false},ticks:{font:{size:11},color:"#69727b"}}}}});
  }

  // risk
  function riskViews(){
    const hhi=POOL.reduce((a,h)=>a+h.wt*h.wt,0);
    const effN=hhi?1/hhi:0;
    const top10=POOL.slice(0,10).reduce((a,h)=>a+h.wt,0);
    const top5=POOL.slice(0,5).reduce((a,h)=>a+h.wt,0);
    document.getElementById("riskStats").innerHTML=[
      ["Largest Position",pc(POOL[0]?POOL[0].wt:0),POOL[0]?POOL[0].name:""],
      ["Top 5 Weight",pc(top5),"of portfolio"],
      ["Top 10 Weight",pc(top10),"of portfolio"],
      ["Effective Holdings",effN.toFixed(1),POOL.length+" positions held"],
    ].map(s=>`<div class="card stat"><div class="k">${s[0]}</div><div class="v num">${s[1]}</div><div class="d">${s[2]}</div></div>`).join("");
    document.getElementById("concList").innerHTML=`<ul>`+POOL.slice(0,10).map((h,i)=>`<li>
      <span class="nm">${h.name}</span>
      <span class="wbar"><i style="width:${POOL[0].wt?(h.wt/POOL[0].wt*100).toFixed(0):0}%;background:${PAL[i%PAL.length]}"></i></span>
      <span class="num" style="text-align:right">${pc(h.wt)}</span></li>`).join("")+`</ul>`;
    const fx={};POOL.forEach(h=>{const c=(h.cur==="THB")?"THB":"USD / USDT";fx[c]=(fx[c]||0)+h.val;});
    const fxRows=Object.entries(fx).sort((a,b)=>b[1]-a[1]);
    const fxcol={"THB":"#0b3d2e","USD / USDT":"#b9975b"};
    document.getElementById("fxBar").innerHTML=fxRows.map(([k,v])=>`<i style="width:${P.total_value?v/P.total_value*100:0}%;background:${fxcol[k]||'#6f9a89'}"></i>`).join("");
    document.getElementById("fxLegend").innerHTML=fxRows.map(([k,v])=>`<div><span class="dot" style="background:${fxcol[k]||'#6f9a89'}"></span>${k} · <span class="num">${pc(P.total_value?v/P.total_value:0)}</span> · ${f0(v)}</div>`).join("");
    const band={"Equity":"Growth","Digital Assets":"Growth","Multi-Asset":"Balanced","Alternatives":"Balanced","Fixed Income":"Defensive","Cash & Equivalents":"Cash"};
    const bcol={Growth:"#0b3d2e",Balanced:"#3f7d6a",Defensive:"#b9975b",Cash:"#aeb6bd"};
    const agg={};P.by_asset_class.forEach(r=>{const b=band[r.name]||"Balanced";agg[b]=(agg[b]||0)+r.value;});
    const order=["Growth","Balanced","Defensive","Cash"].filter(b=>agg[b]);
    document.getElementById("riskRibbon").innerHTML=order.map(b=>`<i style="width:${P.total_value?agg[b]/P.total_value*100:0}%;background:${bcol[b]}">${(P.total_value?agg[b]/P.total_value*100:0).toFixed(0)}%</i>`).join("");
    document.getElementById("riskLegend").innerHTML=order.map(b=>`<div><span class="dot" style="background:${bcol[b]}"></span>${b} · <span class="num">${pc(P.total_value?agg[b]/P.total_value:0)}</span></div>`).join("");
  }

  function draw(tab){
    if(tab==="Overview"&&!drawn.ov){perfMini();drawn.ov=1;}
    if(tab==="Allocation"&&!drawn.al){donut("acDonut",P.by_asset_class);donut("taxDonut",P.by_tax_status);
      bars("geoBars",P.by_geography,Math.max(...P.by_geography.map(r=>r.value),1));
      bars("themeBars",P.by_theme,Math.max(...P.by_theme.map(r=>r.value),1));
      document.getElementById("acTable").innerHTML=`<thead><tr><th>Asset Class</th><th>Invested</th><th>Value</th><th>Wt</th><th>P&L</th></tr></thead><tbody>`+
        P.by_asset_class.filter(r=>r.value>0).map(r=>`<tr><td class="name">${r.name}</td><td class="num">${f0(r.invested)}</td>
        <td class="num">${f0(r.value)}</td><td class="num">${pc(r.pct)}</td>
        <td class="num ${r.pnl>=0?'pos':'neg'}">${sg(r.pnl)}${f0(r.pnl)}</td></tr>`).join("")+`</tbody>`;drawn.al=1;}
    if(tab==="Holdings"&&!drawn.ho){renderHold();drawn.ho=1;}
    if(tab==="Performance"&&!drawn.pe){perfCharts();drawn.pe=1;}
    if(tab==="Risk"&&!drawn.ri){riskViews();drawn.ri=1;}
  }
  draw("Overview");
}

fetch('data.json',{cache:'no-store'}).then(r=>r.ok?r.json():Promise.reject()).then(boot).catch(()=>{ if(EMBEDDED) boot(EMBEDDED); });
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
    print(f"Built docs/index.html + data.json (v2) — total ฿{pf['total_value']:,.0f}, "
          f"{len(out['history'])} history point(s).")
