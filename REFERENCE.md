# TH Investment — Private Client Dashboard · Reference

A durable reference for the project: what it is, how it's wired, how to operate it,
and the decisions/gotchas worth remembering. (For the quick-start, see `README.md`.)

---

## 1. What this is

An Excel workbook of a private client's holdings (Thai mutual funds, Thai + US
equities, crypto, cash, SGD unit trusts) is converted into a **branded, self-updating,
institutional-grade web dashboard** that refreshes **daily at 09:00 Bangkok time** and
is published to **GitHub Pages**. Reporting currency is **THB**.

- **Live site:** `https://vsupakatitham-cloud.github.io/investment-dashboard/`
- **Workbook (system of record):** `TH Investment - Private Banking Summary.xlsx`
- **Published site folder:** `docs/` (GitHub Pages serves this)
- **Pipeline (Python):** `pipeline/`

---

## 2. Data flow

```
Workbook (.xlsx)  ──read──►  portfolio.py (recomputes every formula in Python)
      ▲                              │
      │ fetch_prices.py writes       ├─► performance.py  (TWR/IRR, benchmark, risk)
      │ prices/NAVs/FX               ├─► tax.py          (wrappers, lock-ups, lots)
      │                              │
  live sources:                      ▼
  • Yahoo (equities, crypto,    build_site.py  ──►  docs/index.html + docs/data.json
    FX, unit trusts, benchmark)                      (+ history.json, benchmark.json)
  • CoinGecko (crypto)                                      │
  • SEC Open API /v2/fund (Thai NAVs)                       ▼
                                               GitHub Pages (daily via Actions)
```

The **web dashboard never trusts the Excel cached values** (openpyxl strips them on
save). `portfolio.py` re-derives every value from the raw inputs + Reference + Prices.

---

## 3. Pipeline files (`pipeline/`)

| File | Role |
|---|---|
| `portfolio.py` | Core valuation engine. Reads all Lots sheets dynamically (to the TOTAL row), applies Reference classification + Prices, multi-currency FX (THB=1, USD=FXRate, SGD=SGDTHB), returns the portfolio dict. |
| `fetch_prices.py` | Live prices into the workbook: Yahoo (equities `.BK`/US, FX), CoinGecko (crypto), SEC (Thai NAVs via `fetch_thai_nav`), SGD/THB, and unit-trust NAVs (Yahoo, incl. ISIN→symbol resolution). Skips `Cash`. |
| `fetch_thai_nav.py` | Thai MF NAVs from **SEC Open Data Fund API v2** (`/v2/fund/daily-info/nav`). Uses pinned proj_id + share class from `sec_fund_map.json`. |
| `fetch_benchmark.py` | Benchmark history → `docs/benchmark.json`. MSCI ACWI (ETF `ACWI`) × USD/THB, ~6yr daily, indexed to 100. |
| `performance.py` | Institutional performance metrics → `tax`-like `performance` object: period returns (portfolio/benchmark/relative), TWR, IRR, vol/Sharpe/Sortino/maxDD, calendar years, drawdown. Honest gating (no annualized metrics <1yr; periods clamped to inception). |
| `tax.py` | Tax & Lots: unrealized/realized, tax-wrapper aggregates, **lock-up maturity calendar** (real Sellable Years), lot records. |
| `build_site.py` | Renders `docs/index.html` (the whole SPA: HTML+CSS+JS template) + `docs/data.json`. Computes performance + tax, updates `history.json`. **This file holds the entire front-end.** |
| `run_weekly.py` | Orchestrator (despite the name, runs **daily**): fetch prices → benchmark → snapshot → build → publish. |
| `backfill_history.py` | One-time: reconstructs daily portfolio history assuming current holdings **held since 2026-05-01**, priced with real historical prices×FX. Wrote 34 daily points. |
| `add_holding.py` | CLI to add an equity/crypto/fund: inserts the lot, Reference + Prices rows, pricing hookup; lists fund share classes to pick. |
| `make_template.py` | Generates the blank onboarding template (`template/…TEMPLATE.xlsx`). |
| `config.json` | Branding, FX/fee/benchmark/tax settings, disclaimer, schedule text. |
| `sec_fund_map.json` | abbreviation → SEC proj_id + share class (NAV-verified). **Public ids only, no secrets.** |

---

## 4. Workbook sheets

- **Input sheets (you edit these):** `FX & Assumptions` (As-of date, USD/THB, SGD/THB),
  `Prices`, `Reference` (classification), `MF - Lots`, `Equities - Lots`, `Crypto - Lots`,
  `Unit Trust (SGD)`, `Cash Flows` (for IRR), `Realized` (disposals → realized gains).
- **Output/derived (Excel-internal):** `Dashboard`, `Weekly Snapshot`, the `by-Fund/Ticker/Coin` rollups.
- **Yellow cells = inputs; black/green text = formulas — don't overwrite formulas.**
- Lock-up/tax data lives on **MF - Lots** (`Purchase Date`, `Sellable Year`).

---

## 5. The dashboard (6 tabs)

Clean institutional-light design, tabbed; **mobile = bottom nav + card-based tables + PWA**.

1. **Overview** — KPIs with week-over-week deltas + sparklines, allocation ribbon, top movers, value-vs-invested trend, largest holdings.
2. **Allocation** — asset class / geography / tax wrapper / theme.
3. **Holdings** — searchable / sortable / filterable; on mobile, tappable cards.
4. **Performance** — period table vs **MSCI ACWI (THB)** benchmark, TWR/IRR, growth-of-฿100, drawdown, calendar-year, risk stats.
5. **Risk** — concentration (top-5/10, effective holdings), currency exposure (THB/USD/SGD), risk-posture band.
6. **Tax & Lots** — wrapper breakdown, **lock-up & maturity schedule**, lot table with Locked/Available status.

---

## 6. Configuration & secrets

- **`pipeline/config.json`** — `firm_name`, `logo_text`, `client_name`, accent colors,
  `benchmark`, `annual_fee_pct`, `risk_free_pct`, `tax_inception_date` (2026-05-01),
  `tax_advantaged_wrappers`, `schedule_text`, `disclaimer`.
- **Secret:** `SEC_OPENAPI_KEY` — the SEC "fund_api" (product `sec-openapi-normal`) key from
  https://secopendata.sec.or.th/. Local: `export SEC_OPENAPI_KEY=…`. Cloud: repo →
  Settings → Secrets → Actions. **Never commit keys.** `.gitignore` blocks `*.png` (except
  app icons), `*token*`, `*secret*`, `*.rtf`, screenshots.

---

## 7. Operations

```bash
# one-time per session (for Thai NAVs)
export SEC_OPENAPI_KEY="<fund_api key>"

# full daily refresh (prices + benchmark + snapshot + build), no push
python3 pipeline/run_weekly.py --no-publish

# rebuild dashboard only (from current workbook)
python3 pipeline/build_site.py

# add a holding (lists share classes for funds)
python3 pipeline/add_holding.py equity --ticker GOOGL --broker Dime --ccy USD --shares 10 --avg-cost 150 \
   --asset-class Equity --geography "United States" --theme "US Large Cap" --tax Taxable

# publish (from your machine — sandbox is read-only)
git push origin main
```

- **Daily job:** `.github/workflows/weekly.yml`, cron `0 2 * * *` (= 09:00 BKT). Needs the
  `SEC_OPENAPI_KEY` secret + token `workflow` scope to edit the workflow file.
- **PWA install:** open the live URL on a phone → "Add to Home Screen".

---

## 8. Decisions & gotchas (the hard-won lessons)

- **SEC share classes matter.** A fund's NAV is class-specific. The workbook's labels
  (e.g. `SCBKEQTG`) sometimes mapped to the wrong class by NAV; always pin to the class
  whose **name matches the label** (`SCBKEQTG`→`SCBKEQTG`, not `SCBKEQTGE`). Verified
  vs the SCBAM website. See `sec_fund_map.json`.
- **openpyxl strips cached formula values** on save → the dashboard recomputes everything
  in Python. Don't rely on `data_only=True`.
- **Formula-valued input cells**: a user typed `=254.87+2584.77` in a Shares cell;
  `_num()` now safely evaluates simple arithmetic (Dime cash was undercounted by ฿92k).
- **Cash** is stored as Shares=balance, AvgCost=1 (no market price) — valued at balance.
- **Unit trusts (SGD)** are a 3rd currency; classification + NAV are Reference/Prices-driven
  (the sheet's D/E/F/G/J columns became INDEX/MATCH formulas — the engine reads from
  Reference/Prices, not the formula text).
- **Performance honesty:** annualized return/Sharpe suppressed <1yr; benchmark measured
  over the **same window** as the portfolio (clamped to inception) for a fair relative.
- **History is reconstructed** from 2026-05-01 ("held-since") and **live daily** from
  2026-06-03 onward.
- **Mobile:** font-boosting fixed (`text-size-adjust:100%`); long names wrap at a fixed
  34ch column; grid overflow fixed with `min-width:0` (uniform 347px cards).

---

## 9. Roadmap status

**Done:** template + auto-update · SEC v2 NAVs · v2 tabbed redesign · mobile-friendly ·
SGD unit trusts · **Performance overhaul** (#1) · **Tax & Lots** (#2) · daily history
backfill · mobile UX trio (bottom nav, card tables, PWA).

**Not done / next:**
- **Authentication** (deferred) — the live URL is currently open; gate before sharing widely.
- Allocation: **target vs actual + drift / rebalance flags**.
- **Income & cash-flow** view (yield, projected income, distribution calendar).
- Risk deepening (VaR, liquidity profile).
- Actionability (contact RM, PDF statement, alerts); native shell.

---

## 10. Change history (commits, newest first)

Touch-ups (timestamp, daily footer) · uniform mobile width · mobile UX trio (bottom nav /
cards / PWA) · long-name wrapping · tax maturity labels · **Tax & Lots page** · overview
backfill · **daily history backfill** · **Performance overhaul + benchmark + daily** · mobile
font fix · unit-trust classification fix · unit-trust NAVs Prices-driven · SGD unit-trust
auto-fetch · 5 SGD unit trusts · **SGD unit-trust support** · formula-cell fix · cost-basis
correction · new investments · **add-holding helper + dynamic ranges** · **fund share-class
fix** · **v2 redesign** · mobile-friendly · SEC live · **SEC v2 migration** · SEC NAVs · initial.
