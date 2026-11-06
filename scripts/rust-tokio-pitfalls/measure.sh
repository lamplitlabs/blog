#!/usr/bin/env bash
# Reproduce the measurements of the "Tokio performance pitfalls, measured" post.
#
#   bash scripts/rust-tokio-pitfalls/measure.sh <work-dir> [reps]
#
# Builds the bench crate offline (tokio 1.53.1 and parking_lot 0.12.5 must be in the
# local cargo cache), then runs every experiment `reps` times (default 5),
# interleaving the variants inside each repetition so host load drifts hit every
# variant alike. Raw key=value lines go to <work-dir>/results.txt; summarise with
#   python3 scripts/rust-tokio-pitfalls/summarise.py <work-dir> > scripts/data/rust-tokio-pitfalls-m2pro.json
# The full run takes about 7 minutes on an M2 Pro.
set -euo pipefail

WORK=${1:?usage: measure.sh <work-dir> [reps]}
REPS=${2:-5}
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$WORK"
WORK=$(cd "$WORK" && pwd)

CARGO_TARGET_DIR="$WORK/target" cargo build --release --offline --manifest-path "$HERE/Cargo.toml" 2>&1 | tail -1
B="$WORK/target/release/tokiobench"
rm -f "$HERE/Cargo.lock"

{
  echo "# host: $(sysctl -n machdep.cpu.brand_string 2>/dev/null || uname -m), $(sysctl -n hw.ncpu 2>/dev/null) cpus"
  echo "# rustc: $(rustc --version)"
  echo "# date: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$WORK/results.txt"

for rep in $(seq 1 "$REPS"); do
  echo "rep $rep/$REPS (load: $(uptime | sed 's/.*averages*: //'))" >&2
  echo "# rep=$rep load=$(uptime | sed 's/.*averages*: //')" >> "$WORK/results.txt"
  "$B" blocking none 4 1 >> "$WORK/results.txt"
  for burst in 1 2 3 4 6 8; do
    for v in inline spawn_blocking block_in_place; do
      "$B" blocking "$v" 4 "$burst" >> "$WORK/results.txt"
    done
  done
  for v in std parking_lot tokio; do
    "$B" mutex "$v" >> "$WORK/results.txt"
  done
  for v in across_await scoped; do
    "$B" held "$v" 500 >> "$WORK/results.txt"
  done
  for work in 200 2000 20000; do
    items=$((200000000 / work))
    for v in per_item joinset chunked inline; do
      "$B" spawn "$v" "$items" "$work" >> "$WORK/results.txt"
    done
  done
  for v in tokio_seq tokio_join std_inline one_blocking; do
    "$B" fs "$v" "$WORK/files" 5000 >> "$WORK/results.txt"
  done
done
echo "done: $WORK/results.txt" >&2
