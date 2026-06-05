# TH Investment — Private Client Dashboard

Converts the lot-level **Private Banking Summary** workbook into a branded,
**self-updating online dashboard** that refreshes **daily at 08:30 Bangkok
time**, plus a **blank onboarding template** for new private clients.

The dashboard (v2) is a clean, institutional, tabbed web app:
**Overview** (KPIs with deltas + sparklines, allocation, top movers, value-vs-invested
trend) · **Allocation** (asset class / geography / tax wrapper / theme) ·
**Holdings** (searchable, sortable, filterable; a **Priced** column shows the date each
position's price/NAV was last fetched) · **Performance** (period returns vs MSCI ACWI
benchmark, TWR/IRR, growth-of-฿100, drawdown, risk stats) · **Risk** (single-name
concentration, top-5/10 weight, effective holdings, currency exposure, risk-posture
band) · **Tax & Lots** (wrapper breakdown, lock-up/maturity calendar, lot table — also
with the **Priced** column). Mobile is a bottom-nav, card-based PWA (installable/offline).

```
investment-dashboard/
├─ TH Investment - Private Banking Summary.xlsx   ← working copy (this client)
├─ template/
│   └─ TH Investment - Private Banking TEMPLATE.xlsx   ← blank, drop-in for new clients
├─ pipeline/
│   ├─ config.json        ← firm / client branding, colours, disclaimer
│   ├─ fetch_prices.py    ← live prices: Yahoo (equities, FX) + CoinGecko (crypto)
│   ├─ portfolio.py       ← valuation engine (reproduces every workbook formula)
│   ├─ build_site.py      ← renders docs/index.html + data.json + history.json
│   ├─ run_weekly.py      ← orchestrator (fetch → snapshot → build → publish)
│   └─ make_template.py   ← regenerates the blank template
├─ docs/                  ← the published site (GitHub Pages serves this folder)
│   ├─ index.html  data.json  history.json
├─ scripts/
│   ├─ daily_update.sh    ← local 08:30 BKT driver (run by launchd; the PRIMARY scheduler)
│   └─ setup_github.sh    ← one-time GitHub Pages setup
├─ .env.local             ← (gitignored) local secrets: SEC_OPENAPI_KEY for the launchd job
└─ .github/workflows/weekly.yml   ← cloud scheduler — now a BACKSTOP (see below)
```

## How the daily auto-update works

The refresh runs every day at **08:30 Asia/Bangkok**. Each run:

1. **Fetches live prices** — US & Thai equities and FX from Yahoo Finance, crypto
   from CoinGecko, and **Thai mutual-fund NAVs from the SEC Thailand Open API**
   (see below). Any fund the SEC can't match is carried forward and flagged.
2. **Logs a snapshot** into the workbook's `Weekly Snapshot` sheet (history).
3. **Rebuilds** `docs/` (the dashboard + JSON data + trend history).
4. **Commits & pushes** — GitHub Pages redeploys automatically.

**Two triggers, primary + backstop:**

- **Primary — local launchd (reliable):** `scripts/daily_update.sh`, run by the macOS
  LaunchAgent `~/Library/LaunchAgents/com.jack.dashboard-daily.plist` at 08:30 BKT
  (the Mac is on Bangkok time). It pulls, runs the pipeline, and pushes. If the Mac is
  asleep at 08:30, launchd runs it once on the next wake.
- **Backstop — GitHub Actions:** `.github/workflows/weekly.yml` (`cron: "30 1"` + `"30 2"`
  UTC) still runs in the cloud for days the Mac is off, and is runnable on demand from
  the **Actions** tab. *Note:* GitHub's **scheduled** cron is unreliable — it has dropped
  the morning ticks and run many hours late — which is exactly why the local launchd
  driver is the primary. The pipeline is idempotent (commits only on a real diff), so if
  both fire on the same day the second is a harmless no-op or a small refresh.

## First-time setup (≈5 min)

1. Create an **empty** repo on github.com (no README).
2. From this folder:
   ```bash
   scripts/setup_github.sh https://github.com/<you>/<repo>.git
   ```
3. In the repo: **Settings → Pages → Deploy from a branch → `main` → `/docs`**.
4. Your dashboard is live at `https://<you>.github.io/<repo>/` and refreshes daily.

Trigger an update any time from the repo's **Actions** tab → *Daily Dashboard
Update* → *Run workflow*, or locally with `bash scripts/daily_update.sh`.

## Thai mutual-fund NAVs (SEC Open Data — Fund API v2)

`pipeline/fetch_thai_nav.py` prices the Thai funds from the SEC Thailand
**Open Data** portal — https://secopendata.sec.or.th/ (gateway `https://api.sec.or.th`).
It uses the new consolidated **Fund API** (product **`sec-openapi-normal`**), so a
**single key** drives everything:

| Endpoint | Gives |
|---|---|
| `GET /v2/fund/general-info/profiles` | `proj_id`, `proj_abbr_name`, `fund_class_name` (cursor-paged) |
| `GET /v2/fund/daily-info/nav?proj_id=…&start_nav_date=…&end_nav_date=…` | daily NAV `last_val` (THB/unit), `nav_date` |

Header on every call: `Ocp-Apim-Subscription-Key`.

To enable:

1. Sign in at https://secopendata.sec.or.th/, subscribe to the **Fund API**, and
   copy the key from your **`fund_api` (Product: sec-openapi-normal)** subscription.
   *(The separate legacy "Fund Daily Info" subscription is the old `/FundDailyInfo`
   API and is not needed.)*
2. Provide it in **both** places so primary and backstop can each fetch NAVs:
   - **Local launchd job:** put it in `.env.local` (gitignored) at the repo root —
     `echo 'export SEC_OPENAPI_KEY="your-fund_api-key"' > .env.local` (the driver
     sources this; a plain `export …` in your shell also works for manual runs).
   - **GitHub Actions backstop:** add it as a repo secret
     (`Settings → Secrets and variables → Actions → SEC_OPENAPI_KEY`).
3. Check it:
   ```bash
   python pipeline/fetch_thai_nav.py --selftest          # key + connectivity + pin count
   python pipeline/fetch_thai_nav.py --nav K-VIETNAMRMF  # latest NAV for one fund
   ```

How it behaves:

- A fund's abbreviation can have several share classes, each with its own NAV. A
  **verified** abbreviation → (`proj_id`, `fund_class_name`) map is shipped in
  `pipeline/sec_fund_map.json` — every one of this client's 32 funds was pinned and
  NAV-checked against the workbook (exact match). Runtime makes just one NAV call
  per held fund.
- The NAV lookup walks back ~12 days, so weekend/holiday runs still find the last NAV.
- Adding new funds: `python pipeline/fetch_thai_nav.py --refresh-map ABBR1 ABBR2`
  adds clean matches; ambiguous share classes are listed to pin by hand.
- **No key set → the system still works**: Thai MFs carry forward and are flagged
  on the dashboard. Well under the SEC limit of 3,000 calls / 300 s.

## Run it locally

```bash
pip install -r requirements.txt

python pipeline/run_weekly.py --no-publish   # full refresh, don't push
python pipeline/run_weekly.py --offline --no-publish   # rebuild only, no network
python pipeline/build_site.py                # rebuild dashboard from current workbook
open docs/index.html                         # preview
```

## Onboarding a new client

1. Copy `template/TH Investment - Private Banking TEMPLATE.xlsx` and rename it.
2. Fill the `Reference`, `Prices`, and the three `… - Lots` sheets with the new
   client's positions (all formulas and rollups are already wired up).
3. Set `pipeline/config.json` → `client_name`, `client_ref`, branding.
4. Point `WORKBOOK_DEFAULT` (or the `--workbook` flag) at the new file and publish.

## Notes

- **Reporting currency is THB.** THB holdings use FX = 1; USD/USDT holdings use the
  single `USD/THB` rate from `FX & Assumptions` — the workbook's original convention.
- The workbook stays the system of record. The dashboard never edits formulas; it
  only writes prices, the FX/as-of cells, and appended snapshot rows.
- Branding, disclaimer and colours live in `pipeline/config.json`.
