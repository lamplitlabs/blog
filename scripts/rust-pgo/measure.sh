#!/usr/bin/env bash
# Reproduce the measurements of the "Rust PGO vs Go PGO" post.
#
#   bash scripts/rust-pgo/measure.sh <work-dir>
#
# Needs: macOS (/usr/bin/time -l reports instructions retired and cycles), a
# Rust toolchain whose sysroot ships profiler_builtins (rustup's does; the post
# used rustc 1.95.0), an llvm-profdata of the same LLVM major as rustc
# (`rustc -vV | grep LLVM`; set LLVM_PROFDATA, default Homebrew llvm@22), a Go
# toolchain (go1.27.4) and python3. Nothing is downloaded: both programs use
# the standard library only and cargo runs with --offline.
#
# The Go program is scripts/go-pgo/logroute (also the input generator); the
# Rust program in ./logroute is a line-by-line port and must print the same
# checksum. Writes into <work-dir>:
#   api.log, batch.log      1,000,000 seeded lines each (from the Go generator)
#   api-short.log           the first 10,000 lines of api.log (1% profile)
#   prof/                   .profraw from instrumented runs, merged .profdata
#   profiles/*.pprof        Go CPU profiles
#   bin/<variant>           one binary per variant (VARIANTS below)
#   instrumented.tsv        ns/line of the instrumented (profile-generate) builds
#   load.tsv, runs.tsv      counters per (variant, config): reps=0 and REPS
#   remarks-*.txt           rustc -Cremark output (indirect-call promotion, inlining)
#   pgodebug-api.txt        go build -d=pgodebug=1: Go's hot call sites
#   devirt-api.txt          go build -gcflags=-m: Go's PGO devirtualizations
#   builds.tsv              clean-build wall time and binary size, 3 per mode
#   codesize.tsv, *.main.s  size and disassembly of logroute::main per Rust variant
#   rs-*.sample.txt/.folded/.svg   /usr/bin/sample profiles and flame graphs
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
crate="$here/logroute"
gosrc="$here/../go-pgo/logroute"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
PROFDATA="${LLVM_PROFDATA:-/opt/homebrew/opt/llvm@22/bin/llvm-profdata}"
mkdir -p "$work/bin" "$work/prof" "$work/profiles" "$work/logs"
LINES=1000000
REPS=5
PROFILE_REPS=10
ROUNDS=${ROUNDS:-10}

rbuild() { # rbuild <out> <cargo-profile> <rustflags> [cargo args...]
  local out=$1 prof=$2 flags=$3 tdir="$work/target-$1"
  shift 3
  RUSTFLAGS="$flags" CARGO_TARGET_DIR="$tdir" \
    cargo build --offline --profile "$prof" --manifest-path "$crate/Cargo.toml" "$@" >"$work/logs/build-$out.txt" 2>&1
  cp "$tdir/$prof/logroute" "$work/bin/$out"
}
gbuild() { # gbuild <out> <pgo-arg>
  (cd "$gosrc" && go build -trimpath -pgo="$2" -o "$work/bin/$1" .)
}

# 0. Input: the Go generator writes both configs; the 1% file is its head.
gbuild go-off off
for c in api batch; do
  [[ -f $work/$c.log ]] || "$work/bin/go-off" gen "$c" "$LINES" "$work/$c.log"
done
head -n 10000 "$work/api.log" >"$work/api-short.log"

# 1. Rust: instrumented builds (-Cprofile-generate) for the two cargo profiles.
rbuild rs-gen release "-Cprofile-generate=$work/prof/api"
rbuild rs-gen-lto release-lto "-Cprofile-generate=$work/prof/api-lto"
printf 'variant\tinput\tns_per_line_best\tns_per_line_mean\tchecksum\n' >"$work/instrumented.tsv"
inst() { # inst <variant> <raw-dir> <config> <file> <reps>
  local line
  line="$(LLVM_PROFILE_FILE="$work/prof/$2/%m_%p.profraw" "$work/bin/$1" run "$3" "$4" "$5")"
  awk -v v="$1" -v i="$2" '{ for (k = 1; k <= NF; k++) { split($k, kv, "="); f[kv[1]] = kv[2] }
    printf "%s\t%s\t%s\t%s\t%s\n", v, i, f["ns_per_line_best"], f["ns_per_line_mean"], f["checksum"] }' <<<"$line" >>"$work/instrumented.tsv"
}
rm -rf "$work/prof"/*
inst rs-gen api api "$work/api.log" "$PROFILE_REPS"
inst rs-gen-lto api-lto api "$work/api.log" "$PROFILE_REPS"
inst rs-gen api-short api "$work/api-short.log" 1
inst rs-gen batch batch "$work/batch.log" "$PROFILE_REPS"
for p in api api-lto api-short batch; do
  "$PROFDATA" merge -o "$work/prof/$p.profdata" "$work/prof/$p"
done
"$PROFDATA" show "$work/prof/api.profdata" --topn=12 >"$work/prof/api-top.txt" 2>&1 || true

# 2. Rust variants. Default release is thin-local LTO with 16 codegen units.
rbuild rs-off release ""
rbuild rs-lto release-lto ""
rbuild rs-pgo release "-Cprofile-use=$work/prof/api.profdata"
rbuild rs-pgo-lto release-lto "-Cprofile-use=$work/prof/api-lto.profdata"
rbuild rs-pgo-noicp release "-Cprofile-use=$work/prof/api.profdata -Cllvm-args=-disable-icp"
rbuild rs-pgo-short release "-Cprofile-use=$work/prof/api-short.profdata"
rbuild rs-pgo-batchprof release "-Cprofile-use=$work/prof/batch.profdata"
# Ablations for the cycle loss: no memcpy/memcmp size specialisation, and
# LLVM's ext-TSP basic-block layout instead of the default chain placement.
rbuild rs-pgo-nomemop release "-Cprofile-use=$work/prof/api.profdata -Cllvm-args=-disable-memop-opt"
rbuild rs-pgo-exttsp release "-Cprofile-use=$work/prof/api.profdata -Cllvm-args=-enable-ext-tsp-block-placement=true"
# The same profile with #[inline(never)] on HistSink::write (feature outline-write).
rbuild rs-pgo-outline release "-Cprofile-use=$work/prof/api.profdata" --features outline-write

# 3. Go variants: the same as the Go PGO post, profile from 10 passes over api.log.
"$work/bin/go-off" run api "$work/api.log" "$PROFILE_REPS" "$work/profiles/api.pprof" >/dev/null
gbuild go-pgo "$work/profiles/api.pprof"
(cd "$gosrc" && go build -a -trimpath -pgo="$work/profiles/api.pprof" -gcflags=-d=pgodebug=1 -o /dev/null . 2>&1 | grep -v '^#') >"$work/pgodebug-api.txt" || true
# pgodebug lists inlining only; devirtualization shows up in -m output.
(cd "$gosrc" && go build -a -trimpath -pgo="$work/profiles/api.pprof" -gcflags=-m -o /dev/null . 2>&1 | grep 'PGO devirtualizing' | sort) >"$work/devirt-api.txt" || true

VARIANTS="go-off go-pgo rs-off rs-lto rs-pgo rs-pgo-lto rs-pgo-noicp rs-pgo-nomemop rs-pgo-exttsp rs-pgo-outline rs-pgo-short rs-pgo-batchprof"

counters() { # counters <variant> <config> <reps> -> tab-separated fields
  local out
  out="$( { /usr/bin/time -l "$work/bin/$1" run "$2" "$work/$2.log" "$3"; } 2>&1 )"
  awk '
    /checksum=/ { for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
    / real / { real = $1; user = $3 }
    /instructions retired/ { ins = $1 }
    /cycles elapsed/ { cyc = $1 }
    /maximum resident set size/ { rss = $1 }
    END { printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n", f["ns_per_line_best"], f["ns_per_line_mean"], real, user, ins, cyc, rss, f["checksum"] }
  ' <<<"$out"
}
HDR='variant\tconfig\trun\tbest_ns\tmean_ns\treal_s\tuser_s\tinstructions\tcycles\tmax_rss\tchecksum\n'

# 4. Load-only cost (reps=0) per variant and config, 3 runs each.
printf "$HDR" >"$work/load.tsv"
for run in 1 2 3; do
  for v in $VARIANTS; do
    for c in api batch; do
      printf '%s\t%s\t%s\t%s\n' "$v" "$c" "$run" "$(counters "$v" "$c" 0)" >>"$work/load.tsv"
    done
  done
done

# 5. Timed runs: ROUNDS interleaved rounds so host load drifts over every cell alike.
printf "$HDR" >"$work/runs.tsv"
for run in $(seq 1 "$ROUNDS"); do
  for v in $VARIANTS; do
    for c in api batch; do
      printf '%s\t%s\t%s\t%s\n' "$v" "$c" "$run" "$(counters "$v" "$c" "$REPS")" >>"$work/runs.tsv"
    done
  done
done

# 6. What rustc did with the profile: indirect-call promotion and inlining remarks.
remarks() { # remarks <name> <cargo-profile> <rustflags>
  RUSTFLAGS="$3 -Cremark=pgo-icall-prom -Cremark=inline" CARGO_TARGET_DIR="$work/target-remarks-$1" \
    cargo build --offline --profile "$2" --manifest-path "$crate/Cargo.toml" 2>&1 |
    grep -E '^note: .*(pgo-icall-prom|inline) \(' | sed "s#$crate/##" >"$work/remarks-$1.txt" || true
}
remarks off release ""
remarks pgo release "-Cprofile-use=$work/prof/api.profdata"
remarks pgo-noicp release "-Cprofile-use=$work/prof/api.profdata -Cllvm-args=-disable-icp"
remarks pgo-batchprof release "-Cprofile-use=$work/prof/batch.profdata"

# 7. Build cost: clean builds, 3 per mode (Go: -a rebuilds the standard library too).
printf 'mode\trun\tseconds\tbytes\n' >"$work/builds.tsv"
now() { python3 -c 'import time; print(time.time())'; }
for run in 1 2 3; do
  for mode in rs-off rs-gen rs-pgo rs-lto rs-pgo-lto go-off go-pgo; do
    t0=$(now)
    case $mode in
      rs-off) rm -rf "$work/target-b"; RUSTFLAGS="" CARGO_TARGET_DIR="$work/target-b" cargo build --offline --release --manifest-path "$crate/Cargo.toml" 2>/dev/null; b="$work/target-b/release/logroute" ;;
      rs-gen) rm -rf "$work/target-b"; RUSTFLAGS="-Cprofile-generate=$work/prof/tmp" CARGO_TARGET_DIR="$work/target-b" cargo build --offline --release --manifest-path "$crate/Cargo.toml" 2>/dev/null; b="$work/target-b/release/logroute" ;;
      rs-pgo) rm -rf "$work/target-b"; RUSTFLAGS="-Cprofile-use=$work/prof/api.profdata" CARGO_TARGET_DIR="$work/target-b" cargo build --offline --release --manifest-path "$crate/Cargo.toml" 2>/dev/null; b="$work/target-b/release/logroute" ;;
      rs-lto) rm -rf "$work/target-b"; RUSTFLAGS="" CARGO_TARGET_DIR="$work/target-b" cargo build --offline --profile release-lto --manifest-path "$crate/Cargo.toml" 2>/dev/null; b="$work/target-b/release-lto/logroute" ;;
      rs-pgo-lto) rm -rf "$work/target-b"; RUSTFLAGS="-Cprofile-use=$work/prof/api-lto.profdata" CARGO_TARGET_DIR="$work/target-b" cargo build --offline --profile release-lto --manifest-path "$crate/Cargo.toml" 2>/dev/null; b="$work/target-b/release-lto/logroute" ;;
      go-off) (cd "$gosrc" && go build -a -trimpath -pgo=off -o "$work/bin/build-go" .); b="$work/bin/build-go" ;;
      go-pgo) (cd "$gosrc" && go build -a -trimpath -pgo="$work/profiles/api.pprof" -o "$work/bin/build-go" .); b="$work/bin/build-go" ;;
    esac
    t1=$(now)
    printf '%s\t%s\t%s\t%s\n' "$mode" "$run" "$(python3 -c "print(round($t1-$t0, 2))")" "$(stat -f %z "$b")" >>"$work/builds.tsv"
  done
done
rm -rf "$work/target-b" "$work/prof/tmp"

# 8. Code shape: size of logroute::main (where PGO inlines every hot callee)
#    and of the __text section, per Rust variant.
printf 'variant\tmain_bytes\tmain_insns\tmain_indirect_calls\tmain_sp_loads_stores\ttext_bytes\n' >"$work/codesize.tsv"
llvm_bin="$(dirname "$PROFDATA")"
for v in rs-off rs-lto rs-pgo rs-pgo-lto rs-pgo-noicp rs-pgo-outline; do
  sym="$("$llvm_bin/llvm-nm" "$work/bin/$v" | awk '/ t __ZN8logroute4main17h/ { print $3 }')"
  "$llvm_bin/llvm-objdump" -d --no-show-raw-insn --disassemble-symbols="$sym" "$work/bin/$v" >"$work/$v.main.s"
  text="$("$llvm_bin/llvm-size" -m "$work/bin/$v" | awk '/Section __text:/ { print $3; exit }')"
  python3 - "$v" "$text" "$work/$v.main.s" >>"$work/codesize.tsv" <<'PY'
import re, sys
v, text, path = sys.argv[1:]
addrs, blr, spill = [], 0, 0
for line in open(path):
    m = re.match(r"\s*(1[0-9a-f]+):\s+(\S+)\s*(.*)", line)
    if m:
        addrs.append(int(m.group(1), 16))
        blr += m.group(2) == "blr"
        spill += m.group(2) in ("ldr", "str", "ldp", "stp", "ldur", "stur") and "[sp" in m.group(3)
print(f"{v}\t{addrs[-1] - addrs[0] + 4}\t{len(addrs)}\t{blr}\t{spill}\t{text}")
PY
done

# 9. Where the time goes: /usr/bin/sample (no root) on the default and PGO
#    Rust builds, folded and drawn with the rust-profiling-logstat helpers.
prof="$here/../rust-profiling-logstat"
for v in rs-off rs-pgo; do
  "$work/bin/$v" run api "$work/api.log" 40 >/dev/null &
  pid=$!
  sleep 1
  /usr/bin/sample "$pid" 4 1 -mayDie -file "$work/$v.sample.txt" >/dev/null 2>&1
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  python3 "$prof/fold_sample.py" "$work/$v.sample.txt" >"$work/$v.folded"
  FLAMEGRAPH_ROOT="logroute::main" python3 "$prof/flamegraph_svg.py" "$work/$v.folded" "$work/$v.svg" "logroute $v (api config): CPU flame graph, /usr/bin/sample 4 s at 1 ms" 1400
done

{ rustc -vV; go version; "$PROFDATA" --version; } >"$work/versions.txt" 2>&1
echo "done: $work"
