#!/usr/bin/env bash
# Reproduce the measurements of the "Rust error handling: thiserror vs anyhow" post.
#
#   bash scripts/rust-error-handling/measure.sh <work-dir>
#
# Needs: a Rust toolchain with anyhow 1.0.104 and thiserror 2.0.21 reachable
# (crates.io or the local cargo cache; add --offline via CARGO_NET_OFFLINE=true),
# python3 for summarise.py. Writes into <work-dir>:
#   runs.tsv      5 interleaved runs per (variant, fault rate, backtrace) cell
#   allocs.tsv    heap allocations per line from the count-alloc build
#   sizes.txt     size_of the error and Result types
#   show.txt      one bad line rendered every way; show-bt.txt with RUST_LIB_BACKTRACE=1
#   env.tsv       anyhow at 5% faults under four backtrace environment settings
#   debugfmt.tsv  time to format one anyhow error with {:?}, backtraces off and on
#   build.tsv     clean release build time and binary size of four probe crates
#   e0004.txt     rustc's answer when a thiserror enum gains a variant a match misses
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
export CARGO_TARGET_DIR="$work/target"
LINES=200000
REPS=5

cargo build --release --manifest-path "$here/Cargo.toml" 2>&1 | tail -1
bin="$CARGO_TARGET_DIR/release/errbench"
"$bin" sizes >"$work/sizes.txt"
env -u RUST_BACKTRACE RUST_LIB_BACKTRACE=0 "$bin" show >"$work/show.txt"
env -u RUST_BACKTRACE RUST_LIB_BACKTRACE=1 "$bin" show >"$work/show-bt.txt"

# 1. Time per line: every variant at five fault rates, backtraces off, plus the
#    two anyhow-backed variants and hybrid with RUST_LIB_BACKTRACE=1. Runs are
#    interleaved so host load drifts over all cells alike.
printf 'run\tvariant\tpermille\tbacktrace\tns_per_line\terr\tchecksum\n' >"$work/runs.tsv"
for run in 1 2 3 4 5; do
  for permille in 0 10 50 250 1000; do
    for v in typed anyhow eager hybrid; do
      for bt in 0 1; do
        [[ $bt == 1 && $v == typed ]] && continue   # thiserror captures no backtrace on stable
        [[ $bt == 1 && $permille == 1000 ]] && continue
        out="$(env -u RUST_BACKTRACE RUST_LIB_BACKTRACE=$bt "$bin" run "$v" "$permille" render "$LINES" "$REPS")"
        awk -v run="$run" -v bt="$bt" '{ for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
          END { printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", run, f["variant"], f["permille"], bt, f["ns_per_line"], f["err"], f["checksum"] }' \
          <<<"$out" >>"$work/runs.tsv"
      done
    done
  done
  echo "run $run done"
done

# 1b. Which environment variables switch anyhow's backtrace capture on: the
#     anyhow variant at 5% faults under four settings a service might run with.
printf 'run\tenv\tns_per_line\n' >"$work/env.tsv"
for run in 1 2 3 4 5; do
  for e in unset RUST_BACKTRACE=1 RUST_LIB_BACKTRACE=1 'RUST_BACKTRACE=1 RUST_LIB_BACKTRACE=0'; do
    if [[ $e == unset ]]; then
      out="$(env -u RUST_BACKTRACE -u RUST_LIB_BACKTRACE "$bin" run anyhow 50 render "$LINES" "$REPS")"
    else
      # shellcheck disable=SC2086
      out="$(env -u RUST_BACKTRACE -u RUST_LIB_BACKTRACE $e "$bin" run anyhow 50 render "$LINES" "$REPS")"
    fi
    ns="$(sed 's/.*ns_per_line=\([0-9.]*\).*/\1/' <<<"$out")"
    printf '%s\t%s\t%s\n' "$run" "$e" "$ns" >>"$work/env.tsv"
  done
done

# 1c. Cost of printing one anyhow error with {:?}: first print (symbolication)
#     and the median of the next 200, backtraces off and on, 5 processes each.
printf 'run\tbacktrace\tdebug_first_us\tdebug_rest_median_us\tdebug_bytes\n' >"$work/debugfmt.tsv"
for run in 1 2 3 4 5; do
  for bt in 0 1; do
    env -u RUST_BACKTRACE RUST_LIB_BACKTRACE=$bt "$bin" debugfmt |
      awk -v run="$run" -v bt="$bt" '{ for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
        END { printf "%s\t%s\t%s\t%s\t%s\n", run, bt, f["debug_first_us"], f["debug_rest_median_us"], f["debug_bytes"] }' \
      >>"$work/debugfmt.tsv"
  done
done

# 2. Heap allocations per line (count-alloc build, one pass is exact).
CARGO_TARGET_DIR="$work/target-alloc" cargo build --release --features count-alloc --manifest-path "$here/Cargo.toml" 2>&1 | tail -1
printf 'variant\tpermille\tbacktrace\tallocs_per_line\talloc_bytes_per_line\terr\n' >"$work/allocs.tsv"
for permille in 0 50 1000; do
  for v in typed anyhow eager hybrid; do
    for bt in 0 1; do
      [[ $bt == 1 && $v == typed ]] && continue
      RUST_LIB_BACKTRACE=$bt "$work/target-alloc/release/errbench" run "$v" "$permille" render 20000 1 |
        awk -v bt="$bt" '{ for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
          END { printf "%s\t%s\t%s\t%s\t%s\t%s\n", f["variant"], f["permille"], bt, f["allocs_per_line"], f["alloc_bytes_per_line"], f["err"] }' \
        >>"$work/allocs.tsv"
    done
  done
done

# 3. Build cost: four probe crates (none, anyhow, thiserror, both), clean
#    release build, 3 runs each, plus the stripped binary size.
probe() {
  local name=$1 deps=$2 body=$3
  mkdir -p "$work/probes/$name/src"
  printf '[package]\nname = "%s"\nversion = "0.1.0"\nedition = "2024"\n\n[dependencies]\n%b\n[profile.release]\nstrip = true\n' \
    "$name" "$deps" >"$work/probes/$name/Cargo.toml"
  printf '%s\n' "$body" >"$work/probes/$name/src/main.rs"
}
probe none '' 'fn main() { let r: Result<u32, std::num::ParseIntError> = std::env::args().nth(1).unwrap_or_default().parse(); if let Err(e) = r { eprintln!("{e}"); } }'
probe anyhow 'anyhow = "=1.0.104"\n' 'use anyhow::Context; fn main() -> anyhow::Result<()> { let n: u32 = std::env::args().nth(1).unwrap_or_default().parse().context("arg 1")?; println!("{n}"); Ok(()) }'
probe thiserror 'thiserror = "=2.0.21"\n' '#[derive(Debug, thiserror::Error)] enum E { #[error("arg 1: {0}")] Arg(#[from] std::num::ParseIntError) } fn main() -> Result<(), E> { let n: u32 = std::env::args().nth(1).unwrap_or_default().parse()?; println!("{n}"); Ok(()) }'
probe both 'anyhow = "=1.0.104"\nthiserror = "=2.0.21"\n' '#[derive(Debug, thiserror::Error)] enum E { #[error("arg 1: {0}")] Arg(#[from] std::num::ParseIntError) } fn p() -> Result<u32, E> { Ok(std::env::args().nth(1).unwrap_or_default().parse()?) } fn main() -> anyhow::Result<()> { use anyhow::Context; println!("{}", p().context("parse")?); Ok(()) }'
printf 'crate\trun\tbuild_s\tbinary_bytes\n' >"$work/build.tsv"
for run in 1 2 3; do
  for c in none anyhow thiserror both; do
    rm -rf "$work/probes/$c/target"
    s=$(python3 -c 'import time; print(time.time())')
    (cd "$work/probes/$c" && CARGO_TARGET_DIR="$work/probes/$c/target" cargo build --release -q)
    e=$(python3 -c 'import time; print(time.time())')
    size=$(wc -c <"$work/probes/$c/target/release/$c" | tr -d ' ')
    python3 -c "print('$c\t$run\t%.3f\t$size' % ($e - $s))" >>"$work/build.tsv"
  done
done
# 4. What a typed error buys the caller: add a variant to the enum and let
#    rustc point at the match that no longer covers every case (E0004).
mkdir -p "$work/probes/exhaustive/src"
printf '[package]\nname = "retry_policy"\nversion = "0.1.0"\nedition = "2024"\n\n[dependencies]\nthiserror = "=2.0.21"\n' \
  >"$work/probes/exhaustive/Cargo.toml"
cat >"$work/probes/exhaustive/src/main.rs" <<'RS'
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("missing field `{0}`")]
    Missing(&'static str),
    #[error("unknown model {0:?}")]
    UnknownModel(String),
    #[error("status {0} out of range 100..=599")]
    BadStatus(u16),
    // added in the next release of the parser crate:
    #[error("record truncated after {0} bytes")]
    Truncated(usize),
}

/// The caller decides per error kind: skip the line, or page someone.
fn should_page(e: &ParseError) -> bool {
    match e {
        ParseError::Missing(_) | ParseError::BadStatus(_) => false,
        ParseError::UnknownModel(_) => true,
    }
}

fn main() {
    println!("{}", should_page(&ParseError::Missing("model")));
}
RS
(cd "$work/probes/exhaustive" && CARGO_TARGET_DIR="$work/probes/exhaustive/target" cargo build 2>&1 |
  grep -v -E '^[[:space:]]*(Compiling|Locking|Downloaded|Downloading)' >"$work/e0004.txt") || true
echo "done: $work"
