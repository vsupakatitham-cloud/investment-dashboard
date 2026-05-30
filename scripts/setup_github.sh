#!/usr/bin/env bash
# One-time GitHub Pages setup for the weekly dashboard.
#
# Usage:
#   scripts/setup_github.sh https://github.com/<you>/<repo>.git
#
# Prereqs: create an EMPTY repo on github.com first (no README), then pass its
# URL here. After this runs, enable Pages in the repo:
#   Settings -> Pages -> Source: "Deploy from a branch" -> Branch: main / folder: /docs
# Your dashboard will be live at https://<you>.github.io/<repo>/
set -euo pipefail
cd "$(dirname "$0")/.."

REMOTE="${1:-}"
if [[ -z "$REMOTE" ]]; then
  echo "Pass your empty GitHub repo URL, e.g.:"
  echo "  scripts/setup_github.sh https://github.com/<you>/<repo>.git"
  exit 1
fi

[[ -d .git ]] || git init -b main
git add -A
git commit -m "Initial commit — private-client investment dashboard" || echo "(nothing new to commit)"

if git remote get-url origin >/dev/null 2>&1; then
  git remote set-url origin "$REMOTE"
else
  git remote add origin "$REMOTE"
fi

git push -u origin main
echo
echo "Pushed. Now enable GitHub Pages:"
echo "  Settings -> Pages -> Deploy from a branch -> main -> /docs"
echo "Then the weekly Action (.github/workflows/weekly.yml) keeps it fresh every Saturday 09:00 BKT."
