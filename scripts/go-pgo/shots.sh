#!/usr/bin/env bash
# Screenshot the pprof web UI for the "Go PGO in practice" post.
#
#   BROWSER_PATH=<chrome-headless-shell> bash scripts/go-pgo/shots.sh <work-dir>
#
# Run after measure.sh. Serves two profiles with `go tool pprof -http` (no
# browser is opened) and saves 1440-wide PNG screenshots into <work-dir>/shots:
#   flame-off.png      flame graph of profiles/api.pprof (the PGO input, PGO-off build)
#   flame-pgo.png      flame graph of profiles/api-pgo-build.pprof (the PGO build)
#   source-off.png     source view of scanFields/setField in the PGO input profile
set -euo pipefail
work="$(cd "$1" && pwd)"
browser="${BROWSER_PATH:?set BROWSER_PATH to a headless Chromium (chrome-headless-shell)}"
mkdir -p "$work/shots"
port_off=${PORT_OFF:-18731}
port_pgo=${PORT_PGO:-18732}

go tool pprof -no_browser -http="127.0.0.1:$port_off" -source_path="$(cd "$(dirname "$0")" && pwd)/logroute" -trim_path=example.com/logroute "$work/bin/off" "$work/profiles/api.pprof" >/dev/null 2>&1 &
p1=$!
go tool pprof -no_browser -http="127.0.0.1:$port_pgo" "$work/bin/pgo" "$work/profiles/api-pgo-build.pprof" >/dev/null 2>&1 &
p2=$!
trap 'kill $p1 $p2 2>/dev/null || true; rm -rf "$work/shots/.chrome"' EXIT
for port in $port_off $port_pgo; do
  for _ in $(seq 1 50); do
    curl -fs "http://127.0.0.1:$port/ui/" >/dev/null && break
    sleep 0.2
  done
done

shot() { # shot <url> <png> <height>
  rm -rf "$work/shots/.chrome"
  "$browser" --headless=new --user-data-dir="$work/shots/.chrome" --hide-scrollbars \
    --window-size="1440,$3" --virtual-time-budget=4000 --screenshot="$2" "$1" >/dev/null 2>&1
}
shot "http://127.0.0.1:$port_off/ui/flamegraph" "$work/shots/flame-off.png" 900
shot "http://127.0.0.1:$port_pgo/ui/flamegraph" "$work/shots/flame-pgo.png" 900
shot "http://127.0.0.1:$port_off/ui/source?f=main.scanFields%24" "$work/shots/source-off.png" 1500
ls -l "$work/shots"
