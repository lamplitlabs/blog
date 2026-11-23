#!/usr/bin/env bash
# Screenshot gomut's HTML report of the hand-written suite for the post.
#
#   BROWSER_PATH=<chrome-headless-shell> bash scripts/agent-tests-mutation/shots.sh <work-dir>
#
# Run after `harness.py human <work-dir>`. Re-runs gomut on <work-dir>/trees/human
# (the hand-written tests next to the pristine service) with a fixed title and
# saves a 1280-wide PNG of the survivors report to <work-dir>/shots/human-report.png.
set -euo pipefail
work="$(cd "$1" && pwd)"
here="$(cd "$(dirname "$0")" && pwd)"
browser="${BROWSER_PATH:?set BROWSER_PATH to a headless Chromium (chrome-headless-shell)}"
mkdir -p "$work/shots" "$work/bin"
(cd "$here/gomut" && go build -o "$work/bin/gomut" .)
"$work/bin/gomut" -dir "$work/trees/human" -j 4 -title "gomut: hand-written suite, quota service" \
  -html "$work/shots/human-report.html"
trap 'rm -rf "$work/shots/.chrome"' EXIT
"$browser" --headless=new --user-data-dir="$work/shots/.chrome" --hide-scrollbars \
  --force-device-scale-factor=1 --window-size=1280,1600 \
  --screenshot="$work/shots/human-report.png" "file://$work/shots/human-report.html" 2>/dev/null
echo "wrote $work/shots/human-report.png"
