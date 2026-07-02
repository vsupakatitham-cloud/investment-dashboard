# TH Investment Dashboard — 10x Roadmap

*Drafted 2026-07-02. The codebase today is a solid single-client reporting engine
(~3,400 lines of Python turning one workbook into a self-updating dashboard with
honest performance math, daily movers, tax-aware lock-ups, reliable scheduling).
What it is not yet: secure, advisory, multi-client, or self-defending against data
errors. Zero tests. Those four gaps are where the 10x lives.*

> **Thesis: from "a dashboard that reports one portfolio" → "a private-banking
> platform that protects, advises, and scales."**

---

## Phase 1 — Trust & Security (unlocks everything else)

### 1.1 Authentication on the live site 🔴 highest priority
**Why:** the client's full holdings are publicly reachable today.
**Build:** GitHub Pages can't gate content → move to Cloudflare Pages + Access
(free, email OTP/SSO, `docs/` deploys as-is). Kill or dark-mirror the Pages URL.
**Acceptance criteria:**
- [ ] Fresh incognito session → login challenge, never data (HTML *and* `data.json` blocked)
- [ ] Authorized email logs in ≤2 steps; session persists ≥7 days on the PWA
- [ ] Old public URL returns 404/redirect; repo history scrubbed or repo private
- [ ] Daily 08:30 job publishes to the new host with zero manual steps (3 consecutive automated deploys)

### 1.2 Test suite + CI gate
**Why:** ~10 features shipped on 0 tests; the FX-contribution bug survived until a
human questioned it.
**Build:** `pytest` on a fixture workbook: valuation totals, FX translation, RMF
sellable-year rule, flows parsing, day-move gating, `_num()` formula-eval. CI runs
before any publish.
**Acceptance criteria:**
- [ ] ≥12 invariants incl.: total = Σ holdings; Δinvested-under-FX ≠ flow; `rmf_sellable_year(1982,2014)==2037`; stale-NAV gate excludes >5-day windows
- [ ] CI fails the build (no publish) on test failure — verified by an intentionally broken PR
- [ ] Reconciliation test: `data.json` totals match recomputed workbook totals to the baht

### 1.3 Data-quality sentinel + alerting
**Why:** failures are silent (NAV carry-forward, bad workbook edits, SEC portal cutoff 2026-06-30).
**Build:** post-build validation in `run_weekly.py` (freshness census, >|8%| day-move
sanity, SEC probe, `tax.warnings`) → LINE Messaging API push or email; dead-man's
switch for missed runs.
**Acceptance criteria:**
- [ ] Daily push ≤09:00 BKT: "✅ Updated ฿X (+Y%) · N fresh / M carried" — 5 consecutive days
- [ ] Killed SEC key in a test run → ⚠️ alert naming the cause within that run
- [ ] Missed 08:30 run → "no update today" alert by 10:00 (healthchecks.io-style ping)

---

## Phase 2 — Advisory intelligence (report → recommend)

### 2.1 Target allocation, drift & rebalance signals
**Build:** `target_allocation` in `config.json`; drift bars on the Allocation tab;
rebalance table (sell/buy ฿ to return to target), **lock-up-aware** (never proposes
selling a Locked RMF lot).
**Acceptance criteria:**
- [ ] Each class shows target %, actual %, drift pp; amber ≥3pp / red ≥5pp (configurable)
- [ ] Rebalance trades sum to ~zero net cash and land every class within tolerance (recompute test)
- [ ] No proposed sell references a lot with `status == "Locked"` (fixture test)
- [ ] Disclaimer: illustrative drift calculations, not advice

### 2.2 Thai tax-allowance optimizer 🇹🇭
**Build:** extend `tax_rules.py`; optional `annual_income` in config; "Tax Planning"
card on Tax & Lots: YTD purchases per wrapper vs cap (RMF 30%/฿500k combined,
Thai ESG 30%/฿300k), remaining room, year-end countdown, RMF continuity check
(no gap >1 year).
**Acceptance criteria:**
- [ ] YTD RMF/ESG purchases match a hand-audit of the workbook for the current year
- [ ] Remaining allowance ฿ shown when income configured; cap math hidden gracefully when unset
- [ ] RMF continuity warning fires iff the purchase-year gap rule is at risk (fixture both ways)
- [ ] Q4 (Oct 1+) surfaces a year-end deadline countdown chip

### 2.3 Income & cash-flow view
**Build:** dividend/interest ledger from the `Cash Flows` sheet Type taxonomy
(`read_flows()` already parses it); trailing-12M income; portfolio income yield;
distribution history. Projected income can follow once external yield data is wired.
**Acceptance criteria:**
- [ ] Income section: T12M income received (real logged flows), income yield %
- [ ] Every logged dividend appears in both the income ledger and Today's Movement attribution (single source — test)
- [ ] Holdings with no distribution data show "—", never fabricated yields

---

## Phase 3 — Scale (1 client → N clients)

### 3.1 Multi-client engine
**Build:** `clients/<ref>/` (workbook + config + docs-out) per client; pipeline takes
`--client`; loop in `daily_update.sh`; per-client access policy; advisor roll-up page
(AUM, 1D move, alerts) behind advisor-only auth.
**Acceptance criteria:**
- [ ] Second demo client (from `make_template.py`) builds + publishes with config only, zero code edits
- [ ] 2-client daily run <10 min; one client's failure doesn't block the other
- [ ] Access test: client-A credentials → 403 on client-B's URL
- [ ] Advisor roll-up lists all clients with AUM, 1D move, outstanding alerts

### 3.2 Transaction ingestion (kill manual entry)
**Build:** `ingest_statement.py` parses the 2–3 real confirmation formats (K Asset,
SCB, Dime) → staged diff → `--apply` writes via existing `add_holding` machinery.
**Acceptance criteria:**
- [ ] Real confirmation → staged diff (fund, units, cost, date) requiring explicit `--apply`
- [ ] Idempotent: re-running the same statement adds nothing (dedupe fund+date+units)
- [ ] Unknown fund → existing SEC share-class pin flow, never a blind insert
- [ ] Round-trip: ingested lot valuation == manual `add_holding.py` entry exactly

---

## Phase 4 — Depth & polish

### 4.1 Risk deepening — VaR, stress, FX sensitivity
Historical 95% 1-month VaR (honest-gated ≥250 daily points), named stress scenarios
(THB +5%, global equity −20%, crypto −50%) via existing FX/classification data.
**Acceptance:** VaR hidden with "accruing history" note until sample sufficient (test
both sides); each stress decomposed by currency book; methodology note.

### 4.2 Monthly PDF statement
`make_statement.py`: month performance vs benchmark, movements, income, tax status —
branded, headless HTML→PDF, auto on the 1st, delivered via 1.3 alert channel.
**Acceptance:** PDF matches on-screen numbers for a frozen fixture month; auto-generated
2 consecutive months; Thai-locale number formatting.

### 4.3 Per-holding drill-down & attribution
Holding modal: lot table, price sparkline (extend Prev-Price into rolling
`holdings_history.json`), contribution-to-return.
**Acceptance:** every holding opens a detail view; Σ contributions reconcile to
portfolio return ±0.1pp; mobile tap-target ≥44px.

---

## Sequencing & effort

| # | Feature | Effort | Value driver |
|---|---|---|---|
| 1 | 1.1 Auth | ~½ day | Unblocks sharing — do first |
| 2 | 1.2 Tests + CI | 1–2 d | Makes everything after safe |
| 3 | 1.3 Alerts | 1 d | Trust: silence = safety |
| 4 | 2.1 Targets & drift | 1–2 d | First advisory feature |
| 5 | 2.2 Thai tax optimizer | 1 d | Unique, seasonal, high-touch |
| 6 | 2.3 Income view | 1–2 d | Client-visible |
| 7 | 3.1 Multi-client | 2–3 d | The business 10x |
| 8 | 3.2 Ingestion | 2–4 d | Labor elimination |
| 9 | 4.x depth | 1–3 d each | Compounding polish |

**Two explicit calls:** auth before any new feature (every addition raises exposure);
tests before Phase 2 features are *relied on* (a wrong rebalance ticket is worse than
none).

**Status log:** Phase 2 started 2026-07-02 (2.1, 2.2, 2.3 scoped flows-first).
