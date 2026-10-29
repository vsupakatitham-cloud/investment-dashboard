#!/bin/bash
#
# morning_brief.sh — plumbing for the daily Morning Brief tab.
#
# The scheduled Claude task (instructions: pipeline/news/TASK.md) does the
# reading and writing; this script does everything around it:
#
#   scripts/morning_brief.sh prepare             sync with GitHub, then collect today's context
#   scripts/morning_brief.sh check [draft]       validate the draft against the source policy
#   scripts/morning_brief.sh publish [draft]     check + publish docs/brief.json, commit, push
#
# The draft defaults to news_work/<today in Bangkok>/draft.json, so the unattended task can
# run all three as fixed commands.
#
# Runs from any checkout: the daily cloud routine ("Morning brief (cloud)", 05:45 BKT)
# pushes with its own GitHub access; on the Mac the token is read from "Github token.rtf"
# (gitignored) the same way scripts/daily_update.sh does.
# Env knobs: DRY_RUN=1 publishes into docs/ locally but does not commit or push.
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO" || { echo "repo not found: $REPO"; exit 1; }
TODAY="$(TZ=ICT-7 date +%F)"   # Bangkok date (UTC+7, no DST) without needing tzdata

read_token() {
  python3 - "$REPO/Github token.rtf" <<'PY'
import re, sys
try:
    raw = open(sys.argv[1], "rb").read().decode("utf-8", "ignore")
    t = re.sub(r'\\[a-z]+-?\d* ?', '', raw); t = re.sub(r'[{}]', '', t)
    m = re.search(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,}', t)
    print(m.group(0) if m else "")
except Exception:
    print("")
PY
}

remote() {
  local token; token="$(read_token)"
  if [ -n "$token" ]; then
    echo "https://x-access-token:${token}@github.com/vsupakatitham-cloud/investment-dashboard.git"
  else
    echo "origin"
  fi
}

on_main() {
  local b; b="$(git branch --show-current)"
  if [ "$b" != "main" ]; then
    echo "ERROR: repo is on branch '$b', not main — switch back to main (git switch main) and re-run"; exit 1
  fi
}

case "${1:-}" in
  prepare)
    on_main
    REMOTE="$(remote)"
    git pull --rebase --autostash "$REMOTE" main 2>&1 | tail -2 || { echo "ERROR: git pull failed"; exit 1; }
    python3 pipeline/news/collect.py "${@:2}" || { echo "ERROR: collect failed"; exit 1; }
    ;;

  check)
    DRAFT="${2:-news_work/$TODAY/draft.json}"
    [ -f "$DRAFT" ] || { echo "no draft at $DRAFT"; exit 2; }
    python3 pipeline/news/check_brief.py "$DRAFT"
    ;;

  publish)
    DRAFT="${2:-news_work/$TODAY/draft.json}"
    [ -f "$DRAFT" ] || { echo "no draft at $DRAFT"; exit 2; }
    on_main
    python3 pipeline/news/publish_brief.py "$DRAFT" || exit 1
    git add docs/brief.json docs/briefs pipeline/news/calendar.json pipeline/news/cik_cache.json
    if git diff --cached --quiet; then echo "no changes to publish"; exit 0; fi
    if [ "${DRY_RUN:-0}" = "1" ]; then
      echo "DRY_RUN=1 — staged changes, skipping commit/push"; git reset -q; exit 0
    fi
    REMOTE="$(remote)"
    git -c user.name="dashboard-bot" -c user.email="actions@github.com" \
        commit -q -m "Morning brief — $TODAY"
    # push, with one rebase-retry if the daily dashboard job pushed meanwhile
    if ! git push "$REMOTE" main 2>&1 | tail -1; then :; fi
    if [ "$(git rev-parse HEAD)" != "$(git ls-remote "$REMOTE" refs/heads/main | cut -f1)" ]; then
      echo "push rejected or incomplete — rebasing and retrying once"
      git pull --rebase --autostash "$REMOTE" main 2>&1 | tail -1 && git push "$REMOTE" main 2>&1 | tail -1
    fi
    echo "published: https://vsupakatitham-cloud.github.io/investment-dashboard/"
    ;;

  *)
    sed -n '3,17p' "$0"; exit 2 ;;
esac
