# TH Investment — Private Client Dashboard

Converts the lot-level **Private Banking Summary** workbook into a branded,
**self-updating online dashboard** that refreshes **every Saturday at 09:00
Bangkok time**, plus a **blank onboarding template** for new private clients.

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
├─ .github/workflows/weekly.yml   ← the Saturday 09:00 BKT scheduler (cloud)
└─ scripts/setup_github.sh        ← one-time GitHub Pages setup
```

## How the weekly auto-update works

`.github/workflows/weekly.yml` runs in GitHub's cloud on `cron: "0 2 * * 6"`
(02:00 UTC Saturday = **09:00 Asia/Bangkok**). Each run:

1. **Fetches live prices** — US & Thai equities and FX from Yahoo Finance, crypto
   from CoinGecko, and **Thai mutual-fund NAVs from the SEC Thailand Open API**
   (see below). Any fund the SEC can't match is carried forward and flagged.
2. **Logs a weekly snapshot** into the workbook's `Weekly Snapshot` sheet (history).
3. **Rebuilds** `docs/` (the dashboard + JSON data + trend history).
4. **Commits & pushes** — GitHub Pages redeploys automatically.

Because it runs in the cloud, the dashboard updates **whether or not your Mac is on**.

## First-time setup (≈5 min)

1. Create an **empty** repo on github.com (no README).
2. From this folder:
   ```bash
   scripts/setup_github.sh https://github.com/<you>/<repo>.git
   ```
3. In the repo: **Settings → Pages → Deploy from a branch → `main` → `/docs`**.
4. Your dashboard is live at `https://<you>.github.io/<repo>/` and refreshes every Saturday.

Trigger an update any time from the repo's **Actions** tab → *Weekly Dashboard
Update* → *Run workflow*.

## Thai mutual-fund NAVs (SEC Open API)

`pipeline/fetch_thai_nav.py` prices the Thai funds from the SEC Thailand
developer portal — https://api-portal.sec.or.th/. Two products are used:

| Product | Endpoint | Gives |
|---|---|---|
| **Fund Factsheet** | `GET /FundFactsheet/fund/amc`, `…/amc/{unique_id}` | maps a fund abbreviation → `proj_id` |
| **Fund Daily Info** | `GET /FundDailyInfo/{proj_id}/dailynav/{yyyy-mm-dd}` | the daily NAV (`last_val`) |

Each product issues its own subscription key (header
`Ocp-Apim-Subscription-Key`). To enable:

1. Sign in at https://api-portal.sec.or.th/, **subscribe** to *Fund Factsheet*
   and *Fund Daily Info*, and copy the two keys.
2. Provide them as environment variables (local) **or** GitHub Actions secrets
   (`Settings → Secrets and variables → Actions`):
   ```bash
   export SEC_FUND_FACTSHEET_KEY="xxxxxxxx"      # comma-separate several keys to spread the rate limit
   export SEC_FUND_DAILY_INFO_KEY="yyyyyyyy"
   ```
3. Check it:
   ```bash
   python pipeline/fetch_thai_nav.py --selftest          # confirms keys + connectivity
   python pipeline/fetch_thai_nav.py --refresh-map       # build the abbr→proj_id cache
   python pipeline/fetch_thai_nav.py --nav K-VIETNAMRMF  # latest NAV for one fund
   ```

How it behaves:

- Fund abbreviations are matched to `proj_abbr_name` (exact, then punctuation-insensitive).
  Funds that don't match are **carried forward** and listed on the dashboard — no wrong NAVs.
- The abbreviation→`proj_id` map is cached in `pipeline/sec_fund_map.json` (14-day TTL)
  to stay well under the SEC limit of 3,000 calls / 300 s.
- The NAV lookup walks back up to 8 days, so weekend/holiday runs still find the last NAV.
- **No keys set → the system still works**, exactly as before: Thai MFs carry forward.

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
