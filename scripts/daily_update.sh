#!/bin/bash
#
# daily_update.sh — local launchd driver for the daily dashboard refresh.
#
# Why this exists: GitHub Actions' *scheduled* cron is unreliable for this repo
# (it has dropped/delayed the 08:30 BKT tick by many hours). This script runs the
# same pipeline locally and pushes, driven by a launchd job at 08:30 Asia/Bangkok
# (see ~/Library/LaunchAgents/com.jack.dashboard-daily.plist). The GitHub workflow
# stays enabled as a best-effort backstop for days the Mac is off.
#
# Secrets (never committed):
#   * GitHub token  : read from "Github token.rtf" (gitignored) in the repo root.
#   * SEC_OPENAPI_KEY (optional, for Thai MF NAVs): put `export SEC_OPENAPI_KEY=...`
#     in <repo>/.env.local (gitignored). Without it, Thai NAVs carry forward.
#
# Env knobs: DRY_RUN=1 builds but does not commit/push (for testing).
set -uo pipefail

REPO="/Users/jack/investment-dashboard"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
mkdir -p "$REPO/logs"

echo "==================================================================="
echo "daily_update start: $(date '+%Y-%m-%d %H:%M:%S %z')"

# --- optional local env (SEC key etc.) -----------------------------------
[ -f "$REPO/.env.local" ] && source "$REPO/.env.local"
if [ -n "${SEC_OPENAPI_KEY:-}" ]; then echo "SEC key: present"; else echo "SEC key: absent (Thai NAVs carry forward)"; fi

# --- GitHub token from the gitignored rtf --------------------------------
TOKEN="$(python3 - <<'PY'
import re
try:
    raw = open("/Users/jack/investment-dashboard/Github token.rtf","rb").read().decode("utf-8","ignore")
    t = re.sub(r'\\[a-z]+-?\d* ?','',raw); t = re.sub(r'[{}]','',t)
    m = re.search(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}', t)
    print(m.group(0) if m else "")
except Exception:
    print("")
PY
)"
if [ -z "$TOKEN" ]; then echo "ERROR: no GitHub token found; aborting"; exit 1; fi
REMOTE="https://x-access-token:${TOKEN}@github.com/vsupakatitham-cloud/investment-dashboard.git"

# --- sync with remote (GitHub backstop runs / manual pushes) -------------
git pull --rebase --autostash "$REMOTE" main 2>&1 || { echo "ERROR: git pull failed; aborting"; exit 1; }

# --- build today's dashboard ---------------------------------------------
python3 pipeline/run_weekly.py --no-publish 2>&1 || { echo "ERROR: pipeline failed; aborting"; exit 1; }

# --- commit & push (only on a real diff) ---------------------------------
git add docs "TH Investment - Private Banking Summary.xlsx" pipeline/sec_fund_map.json
if git diff --cached --quiet; then
  echo "no changes to publish"; echo "daily_update done (no-op): $(date '+%H:%M:%S')"; exit 0
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1 — staged changes, skipping commit/push"
  git reset -q; exit 0
fi

git -c user.name="dashboard-bot" -c user.email="actions@github.com" \
    commit -q -m "Daily dashboard update — $(date +%Y-%m-%d)"
# push, with one rebase-retry if the remote advanced mid-run
if ! git push "$REMOTE" main 2>&1; then
  echo "push rejected — rebasing and retrying once"
  git pull --rebase --autostash "$REMOTE" main 2>&1 && git push "$REMOTE" main 2>&1
fi
echo "daily_update done: $(date '+%H:%M:%S')"
