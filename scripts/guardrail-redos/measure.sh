#!/usr/bin/env bash
# Reproduce the measurements of the "ReDoS in AI guardrails, measured" post.
#
#   bash scripts/guardrail-redos/measure.sh <work-dir> [reps]
#
# Needs: macOS or Linux, cargo with regex 1.13.1 + serde_json 1.0.154 in the local
# cargo cache (built --offline), go, node, a python3 >= 3.11 with pyarrow for the
# corpus (PY and PYPATH below; the post used uv's CPython 3.13.5), and the GSM8K and
# TruthfulQA parquet files in ~/.cache/huggingface/hub. Nothing is downloaded.
#
# Writes into <work-dir>:
#   benign.txt              3,455 real question/answer lines (build_benign.py)
#   compile.tsv             Rust regex compile result per pattern
#   bench-<engine>-<rep>.tsv  per-engine timings (see bench.py for the columns)
#   load-<engine>-<variant>-<rep>.tsv  open-loop load test, one row per request
#   load-meta.txt           rate, poison body, durations, kern.ipc.somaxconn (caps every listen backlog)
#   shots/*.txt             raw terminal output the post's screenshots are drawn from
#                           (curl.txt, compile.txt, v8-linear.txt)
# Then: python3 scripts/guardrail-redos/summarise.py <work-dir>
# The full run takes about 35 minutes on an M2 Pro (most of it is capped matches).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${1:?usage: measure.sh <work-dir> [reps]}
REPS=${2:-3}
mkdir -p "$WORK/shots"
WORK=$(cd "$WORK" && pwd)
PY=${PY:-$HOME/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none/bin/python3}
PYPATH=${PYPATH:-$HOME/.cache/uv/archive-v0/Mzuk9nmDIb0tkEM6ZJsQV}
RULES="$HERE/rules.json"
PORT0=${PORT0:-18470}
RPS=${RPS:-200}
SECS=${SECS:-30}
EVERY=${EVERY:-5s}

echo "== build" >&2
CARGO_TARGET_DIR="$WORK/target" cargo build --release --offline --manifest-path "$HERE/rustbench/Cargo.toml" 2>&1 | tail -1 >&2
rm -f "$HERE/rustbench/Cargo.lock"
RB="$WORK/target/release/guardbench"
(cd "$HERE/gobench" && go build -o "$WORK/gobench" .)
(cd "$HERE/goguard" && go build -o "$WORK/goguard" .)
(cd "$HERE/loadgen" && go build -o "$WORK/loadgen" .)
PYTHONPATH="$PYPATH" "$PY" "$HERE/build_benign.py" "$WORK/benign.txt"

{
  echo "host: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m), $(sysctl -n hw.ncpu 2>/dev/null || nproc) cpus, $(sw_vers -productVersion 2>/dev/null || uname -r)"
  echo "rustc: $(rustc --version)"
  echo "go: $(go version)"
  echo "node: $(node --version)"
  echo "python: $("$PY" --version)"
  echo "date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$WORK/env.txt"

"$RB" compile "$RULES" > "$WORK/compile.tsv"

echo "== benches" >&2
for rep in $(seq 1 "$REPS"); do
  echo "rep $rep/$REPS (load $(uptime | sed 's/.*averages*: //'))" >&2
  "$RB" bench "$RULES" "$WORK/benign.txt" > "$WORK/bench-rust-$rep.tsv"
  "$WORK/gobench" "$RULES" "$WORK/benign.txt" > "$WORK/bench-go-$rep.tsv"
  node "$HERE/bench.mjs" "$RULES" "$WORK/benign.txt" > "$WORK/bench-node-$rep.tsv"
  node --enable-experimental-regexp-engine-on-excessive-backtracks "$HERE/bench.mjs" "$RULES" "$WORK/benign.txt" > "$WORK/bench-nodefb-$rep.tsv"
  "$PY" "$HERE/bench.py" "$RULES" "$WORK/benign.txt" > "$WORK/bench-python-$rep.tsv"
done

# The poison request for the load test: the fourth step of secret_assign's natural
# ladder, an ordinary 37-byte line, not a crafted attack string.
POISON="$WORK/poison.txt"
"$PY" - "$RULES" > "$POISON" <<'PYEOF'
import json, sys
r = next(r for r in json.load(open(sys.argv[1]))["rules"] if r["name"] == "secret_assign")
n = r["natural"]
sys.stdout.write(n["prefix"] + n["sep"].join(n["words"][:4]) + n["suffix"])
PYEOF
{
  echo "rps: $RPS"
  echo "secs: $SECS"
  echo "poison_every: $EVERY"
  echo "poison: $(cat "$POISON")"
  echo "somaxconn: $(sysctl -n kern.ipc.somaxconn 2>/dev/null || cat /proc/sys/net/core/somaxconn)"
} > "$WORK/load-meta.txt"

wait_port() {
  for _ in $(seq 1 100); do
    if curl -s -o /dev/null -X POST --data 'x' "http://127.0.0.1:$1/check"; then return 0; fi
    sleep 0.1
  done
  echo "server on :$1 did not start" >&2
  return 1
}

start_guard() { # start_guard <engine> <variant> <port>; prints the pid
  case $1 in
    rust)   "$RB" serve "$RULES" "$2" "$3" >/dev/null & ;;
    go)     "$WORK/goguard" "$RULES" "$2" "$3" >/dev/null & ;;
    node)   node "$HERE/server.mjs" "$RULES" "$2" "$3" >/dev/null & ;;
    nodefb) node --enable-experimental-regexp-engine-on-excessive-backtracks "$HERE/server.mjs" "$RULES" "$2" "$3" >/dev/null & ;;
    python) "$PY" "$HERE/server.py" "$RULES" "$2" "$3" >/dev/null & ;;
  esac
  echo $!
}

echo "== load" >&2
port=$PORT0
for rep in $(seq 1 "$REPS"); do
  for engine in rust go node nodefb python; do
    for variant in naive hardened; do
      port=$((port + 1))
      pid=$(start_guard "$engine" "$variant" "$port")
      wait_port "$port"
      echo "load $engine $variant rep $rep (load $(uptime | sed 's/.*averages*: //'))" >&2
      "$WORK/loadgen" -url "http://127.0.0.1:$port/check" -benign "$WORK/benign.txt" -poison "$POISON" \
        -rps "$RPS" -secs "$SECS" -poison-every "$EVERY" -timeout 5s -seed "$rep" \
        > "$WORK/load-$engine-$variant-$rep.tsv"
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    done
  done
done

echo "== shots" >&2
# Raw terminal output for the screenshots: one poison request against each guard,
# timed by curl, and the Rust compile check.
port=$((port + 1))
for engine in python node rust; do
  for variant in naive hardened; do
    port=$((port + 1))
    pid=$(start_guard "$engine" "$variant" "$port")
    wait_port "$port"
    {
      echo "\$ curl -s -w ' %{time_total}s\\n' --data-binary @poison.txt localhost:$port/check   # $engine guard, $variant rules"
      curl -s -w ' %{time_total}s\n' --data-binary @"$POISON" "http://127.0.0.1:$port/check"
    } >> "$WORK/shots/curl.txt"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
  done
done
{
  echo "\$ guardbench compile rules.json"
  cat "$WORK/compile.tsv"
} > "$WORK/shots/compile.txt"
node --enable-experimental-regexp-engine "$HERE/v8_linear_probe.mjs" "$RULES" > "$WORK/shots/v8-linear.txt"
echo "done: $WORK" >&2
