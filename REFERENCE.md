# TH Investment — Private Client Dashboard · Reference

A durable reference for the project: what it is, how it's wired, how to operate it,
and the decisions/gotchas worth remembering. (For the quick-start, see `README.md`.)

---

## 1. What this is

An Excel workbook of a private client's holdings (Thai mutual funds, Thai + US
equities, crypto, cash, SGD unit trusts) is converted into a **branded, self-updating,
institutional-grade web dashboard** that refreshes **daily at 08:30 Bangkok time** and
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

**Automation (outside `pipeline/`):** `scripts/daily_update.sh` is the local 08:30-BKT
driver (pull → `run_weekly.py --no-publish` → commit → push), run by the macOS LaunchAgent
`~/Library/LaunchAgents/com.jack.dashboard-daily.plist`. See §7.

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

1. **Overview** — a **"Today's Movement"** card (day-over-day Δ value + %, dated, with a
   Funds/Equities/Crypto/**Other** bucket breakdown), KPIs with **1D** deltas + sparklines,
   allocation ribbon, top movers, value-vs-invested trend, largest holdings. The daily card
   attributes real **contributions/dividends from the `Cash Flows` sheet** (date-matched) and
   splits them out from market & FX — it does **not** infer flows from Δ cost basis, which
   drifts daily with FX (see §8).
2. **Allocation** — asset class / geography / tax wrapper / theme.
3. **Holdings** — searchable / sortable / filterable; on mobile, tappable cards. A **Priced**
   column shows the date each position's price/NAV was last fetched (bold = today, muted =
   carried forward, amber = >1 week stale) — sourced from Prices col G via `price_asof`.
4. **Performance** — period table vs **MSCI ACWI (THB)** benchmark, TWR/IRR, growth-of-฿100, drawdown, calendar-year, risk stats.
5. **Risk** — concentration (top-5/10, effective holdings), currency exposure (THB/USD/SGD), risk-posture band.
6. **Tax & Lots** — wrapper breakdown, **lock-up & maturity schedule**, lot table with Locked/Available status (and the same **Priced** column as Holdings).

---

## 6. Configuration & secrets

- **`pipeline/config.json`** — `firm_name`, `logo_text`, `client_name`, accent colors,
  `benchmark`, `annual_fee_pct`, `risk_free_pct`, `tax_inception_date` (2026-05-01),
  `tax_advantaged_wrappers`, `schedule_text`, `disclaimer`.
- **Secret:** `SEC_OPENAPI_KEY` — the SEC "fund_api" (product `sec-openapi-normal`) key from
  https://secopendata.sec.or.th/. Set it in **both** places: the local launchd job reads
  `.env.local` (gitignored) at the repo root (`export SEC_OPENAPI_KEY=…`); the GitHub Actions
  backstop reads the repo secret (Settings → Secrets → Actions). Without it, Thai NAVs carry
  forward. **Never commit keys.** `.gitignore` blocks `*.png` (except app icons), `*token*`,
  `*secret*`, `*.rtf`, `.env.local`, `logs/`, screenshots.
- **GitHub token (local push):** the launchd driver reads a fine-grained PAT from
  `Github token.rtf` (gitignored) to push. That PAT has **Contents:write** but **not
  Actions:write**, so it can't trigger `workflow_dispatch` via the API (returns 403) — use
  the Actions tab UI or `bash scripts/daily_update.sh` to run on demand.

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

# run the full daily job exactly as automation does (build + commit + push)
bash scripts/daily_update.sh                # DRY_RUN=1 to build without committing

# publish a manual change (from your machine — sandbox is read-only)
git push origin main
```

- **Daily job (PRIMARY) — local launchd:** `scripts/daily_update.sh`, driven by
  `~/Library/LaunchAgents/com.jack.dashboard-daily.plist` at **08:30 BKT** (Mac on Bangkok
  time; runs on next wake if asleep). Manage it with
  `launchctl bootout|bootstrap gui/$(id -u) <plist>`; logs in `logs/launchd.{out,err}.log`.
- **Daily job (BACKSTOP) — GitHub Actions:** `.github/workflows/weekly.yml`, cron `30 1`
  + `30 2 * * *` UTC. ⚠️ **GitHub's scheduled cron is unreliable** — it dropped both morning
  ticks and ran ~12 h late (2026-06-04), which is why launchd is primary. Kept on for
  Mac-off days; runnable on demand from the Actions tab. Editing the workflow file needs a
  token with `workflow` scope.
- **Recovering a missed day:** just run `bash scripts/daily_update.sh` (idempotent — commits
  only on a real diff).
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
- **Cost basis is FX-translated at spot**, so `total_invested` (THB) drifts day-to-day on
  FX moves alone — e.g. USD/THB 32.59→32.65 raised it ~฿6,254 with zero purchases. So **Δ
  cost basis is NOT a contribution signal**: the Overview "Today's Movement" card reads real
  flows from the `Cash Flows` sheet (date-matched, with Type → "dividend"/"contribution"/
  "withdrawal") and reports the rest as market & FX. `build_site.read_flows()` does the parse.
- **Mobile:** font-boosting fixed (`text-size-adjust:100%`); long names wrap at a fixed
  34ch column; grid overflow fixed with `min-width:0` (uniform 347px cards).

---

## 9. Roadmap status

**Done:** template + auto-update · SEC v2 NAVs · v2 tabbed redesign · mobile-friendly ·
SGD unit trusts · **Performance overhaul** (#1) · **Tax & Lots** (#2) · daily history
backfill · mobile UX trio (bottom nav, card tables, PWA) · **price-freshness "Priced"
column** (Holdings + Tax) · **reliable scheduling via local launchd** (GitHub cron demoted
to backstop) · **Overview "Today's Movement" card** (1D Δ + bucket breakdown, flow-aware
attribution from `Cash Flows`).

**Not done / next:**
- **Authentication** (deferred) — the live URL is currently open; gate before sharing widely.
- Allocation: **target vs actual + drift / rebalance flags**.
- **Income & cash-flow** view (yield, projected income, distribution calendar).
- Risk deepening (VaR, liquidity profile).
- Actionability (contact RM, PDF statement, alerts); native shell.

---

## 10. Change history (commits, newest first)

**local launchd daily driver (08:30 BKT; GitHub cron → backstop)** · Holdings/Tax **"Priced"
column** + desktop column-width fit · daily cadence → **08:30 BKT, off-the-hour cron** ·
Touch-ups (timestamp, daily footer) · uniform mobile width · mobile UX trio (bottom nav /
cards / PWA) · long-name wrapping · tax maturity labels · **Tax & Lots page** · overview
backfill · **daily history backfill** · **Performance overhaul + benchmark + daily** · mobile
font fix · unit-trust classification fix · unit-trust NAVs Prices-driven · SGD unit-trust
auto-fetch · 5 SGD unit trusts · **SGD unit-trust support** · formula-cell fix · cost-basis
correction · new investments · **add-holding helper + dynamic ranges** · **fund share-class
fix** · **v2 redesign** · mobile-friendly · SEC live · **SEC v2 migration** · SEC NAVs · initial.
