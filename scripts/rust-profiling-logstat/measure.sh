#!/usr/bin/env bash
# Reproduce the measurements of the "Rust profiling practical guide" post.
#
#   bash scripts/rust-profiling-logstat/measure.sh <work-dir>
#
# Needs: macOS (uses /usr/bin/sample and /usr/bin/time -l), a Rust toolchain,
# python3. Writes into <work-dir>: access.log (1,000,000 seeded lines, 119 MB),
# <v>.sample.txt, <v>.folded, <v>.svg per version, counters.tsv (5 runs per
# version: wall ms, user s, instructions retired, cycles, peak RSS) and
# allocs.tsv (heap allocations per log line from the count-alloc build).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
export CARGO_TARGET_DIR="$work/target"

cargo build --release --manifest-path "$here/Cargo.toml" 2>&1 | tail -1
bin="$CARGO_TARGET_DIR/release/logstat"
[[ -f $work/access.log ]] || "$bin" generate "$work/access.log" 1000000

# 1. Counters: 5 runs per version, interleaved so host load hits all versions alike.
printf 'version\trun\twall_ms\tuser_s\tinstructions\tcycles\tmax_rss_bytes\tchecksum\n' >"$work/counters.tsv"
for run in 1 2 3 4 5; do
  for v in v0 v1 v2 v3 v4; do
    out="$( { /usr/bin/time -l "$bin" run "$v" "$work/access.log"; } 2>&1 )"
    awk -v v="$v" -v run="$run" '
      /checksum=/ { for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
      / user / { user = $3 }
      /instructions retired/ { ins = $1 }
      /cycles elapsed/ { cyc = $1 }
      /maximum resident set size/ { rss = $1 }
      END { printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", v, run, f["per_rep_ms"], user, ins, cyc, rss, f["checksum"] }
    ' <<<"$out" >>"$work/counters.tsv"
  done
done

# 2. Allocation counts from the counting-allocator build.
CARGO_TARGET_DIR="$work/target-alloc" cargo build --release --features count-alloc --manifest-path "$here/Cargo.toml" 2>&1 | tail -1
printf 'version\tallocs_per_line\n' >"$work/allocs.tsv"
for v in v0 v1 v2 v3 v4; do
  "$work/target-alloc/release/logstat" run "$v" "$work/access.log" | sed 's/.*allocs_per_line=//' | sed "s/^/$v\t/" >>"$work/allocs.tsv"
done

# 3. Profiles: run each version long enough for a 4 s sample at 1 ms, skip the file read.
for v in v0 v1 v2 v3 v4; do
  case $v in v0) reps=2 ;; v1) reps=6 ;; *) reps=30 ;; esac
  "$bin" run "$v" "$work/access.log" "$reps" >/dev/null &
  pid=$!
  sleep 0.5
  /usr/bin/sample "$pid" 4 1 -mayDie -file "$work/$v.sample.txt" >/dev/null 2>&1
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  python3 "$here/fold_sample.py" "$work/$v.sample.txt" >"$work/$v.folded"
  python3 "$here/flamegraph_svg.py" "$work/$v.folded" "$work/$v.svg" "logstat $v: CPU flame graph"
done
echo "done: $work"
