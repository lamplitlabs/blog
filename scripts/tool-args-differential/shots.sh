#!/usr/bin/env bash
# Screenshot the per-payload report of the tool-call argument differential bench.
#
#   BROWSER_PATH=<chrome-headless-shell> bash scripts/tool-args-differential/shots.sh <work-dir>
#
# Run after bench.py. Serves <work-dir>/report.html over 127.0.0.1 and saves
# <work-dir>/shots/report.png (1440 wide, first rows) and report-full.png.
set -euo pipefail
work="$(cd "$1" && pwd)"
browser="${BROWSER_PATH:?set BROWSER_PATH to a headless Chromium (chrome-headless-shell)}"
port=${PORT:-18761}
mkdir -p "$work/shots"
python3 -m http.server "$port" --bind 127.0.0.1 --directory "$work" >/dev/null 2>&1 &
srv=$!
trap 'kill $srv 2>/dev/null || true; rm -rf "$work/shots/.chrome"' EXIT
for _ in $(seq 1 50); do curl -fs "http://127.0.0.1:$port/report.html" >/dev/null && break; sleep 0.2; done
shot() { # shot <png> <width> <height>
  rm -rf "$work/shots/.chrome"
  "$browser" --headless=new --user-data-dir="$work/shots/.chrome" --hide-scrollbars \
    --window-size="$2,$3" --virtual-time-budget=3000 --screenshot="$1" "http://127.0.0.1:$port/report.html" >/dev/null 2>&1
}
shot "$work/shots/report.png" 1440 900
shot "$work/shots/report-full.png" 1440 2400
ls -l "$work/shots"
