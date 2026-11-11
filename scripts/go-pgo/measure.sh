#!/usr/bin/env bash
# Reproduce the measurements of the "Go PGO in practice" post.
#
#   bash scripts/go-pgo/measure.sh <work-dir>
#
# Needs: macOS (/usr/bin/time -l reports instructions retired and cycles), a Go
# toolchain (the post used go1.27.2), python3 for summarise.py. Nothing is
# downloaded: logroute uses the standard library only. Writes into <work-dir>:
#   api.log, batch.log    1,000,000 seeded lines each (~143 MB each)
#   profiles/*.pprof      the CPU profiles every PGO build is made from
#   bin/<variant>         one binary per build variant (see VARIANTS below)
#   runs.tsv              5 interleaved runs per (variant, config): wall, counters
#   load.tsv              the same counters for reps=0 (file load only), subtracted per line
#   builds.tsv            go build -a wall time and binary size, 3 builds per mode
#   m-off.txt, m-pgo.txt  -gcflags=-m output of the routing package without and with PGO
#   m-short.txt           the same with the one-pass profile
#   pgodebug-*.txt        -d=pgodebug=1: hot call sites and budgets the compiler chose
#   diff-top.txt          go tool pprof -top -diff_base=off pgo (api config)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
src="$here/logroute"
work="$(mkdir -p "$1" && cd "$1" && pwd)"
mkdir -p "$work/bin" "$work/profiles"
LINES=1000000
REPS=5
PROFILE_REPS=10

build() { # build <out> <pgo-arg> [extra go build args...]
  local out=$1 pgo=$2
  shift 2
  (cd "$src" && go build -trimpath -pgo="$pgo" "$@" -o "$work/bin/$out" .)
}

build off off
for c in api batch; do
  [[ -f $work/$c.log ]] || "$work/bin/off" gen "$c" "$LINES" "$work/$c.log"
done

# 1. Profiles from the PGO-off binary: the "production" profile is 10 passes
#    over the api log (about 3 s of samples), the short one a single pass.
"$work/bin/off" run api "$work/api.log" "$PROFILE_REPS" "$work/profiles/api.pprof" >/dev/null
"$work/bin/off" run api "$work/api.log" 1 "$work/profiles/api-short.pprof" >/dev/null
"$work/bin/off" run batch "$work/batch.log" "$PROFILE_REPS" "$work/profiles/batch.pprof" >/dev/null
go tool pprof -proto "$work/profiles/api.pprof" "$work/profiles/batch.pprof" >"$work/profiles/merged.pprof" 2>/dev/null

# 2. Build variants.
build pgo "$work/profiles/api.pprof"
build pgo-noinline "$work/profiles/api.pprof" -gcflags=all=-d=pgoinline=0
build pgo-nodevirt "$work/profiles/api.pprof" -gcflags=all=-d=pgodevirtualize=0
build pgo-short "$work/profiles/api-short.pprof"
build pgo-batchprof "$work/profiles/batch.pprof"
build pgo-merged "$work/profiles/merged.pprof"
# Second round: profile the PGO binary itself and rebuild from that profile.
"$work/bin/pgo" run api "$work/api.log" "$PROFILE_REPS" "$work/profiles/api-from-pgo.pprof" >/dev/null
build pgo-iter2 "$work/profiles/api-from-pgo.pprof"
VARIANTS="off pgo pgo-noinline pgo-nodevirt pgo-short pgo-batchprof pgo-merged pgo-iter2"

counters() { # counters <variant> <config> <reps> -> tab-separated fields
  local out
  out="$( { /usr/bin/time -l "$work/bin/$1" run "$2" "$work/$2.log" "$3"; } 2>&1 )"
  awk '
    /checksum=/ { for (i = 1; i <= NF; i++) { split($i, kv, "="); f[kv[1]] = kv[2] } }
    / real / { real = $1; user = $3 }
    /instructions retired/ { ins = $1 }
    /cycles elapsed/ { cyc = $1 }
    END { printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n", f["ns_per_line_best"], f["ns_per_line_mean"], real, user, ins, cyc, f["checksum"] }
  ' <<<"$out"
}

# 3. Load-only cost (reps=0) per variant and config, 3 runs each.
printf 'variant\tconfig\trun\tbest_ns\tmean_ns\treal_s\tuser_s\tinstructions\tcycles\tchecksum\n' >"$work/load.tsv"
for run in 1 2 3; do
  for v in $VARIANTS; do
    for c in api batch; do
      printf '%s\t%s\t%s\t%s\n' "$v" "$c" "$run" "$(counters "$v" "$c" 0)" >>"$work/load.tsv"
    done
  done
done

# 4. Timed runs: 5 interleaved rounds so host load drifts over every cell alike.
printf 'variant\tconfig\trun\tbest_ns\tmean_ns\treal_s\tuser_s\tinstructions\tcycles\tchecksum\n' >"$work/runs.tsv"
for run in 1 2 3 4 5; do
  for v in $VARIANTS; do
    for c in api batch; do
      printf '%s\t%s\t%s\t%s\n' "$v" "$c" "$run" "$(counters "$v" "$c" "$REPS")" >>"$work/runs.tsv"
    done
  done
done

# 5. What the compiler did differently: inlining and devirtualization decisions
#    for the routing package (-m prints only for the package being compiled).
(cd "$src" && go build -a -trimpath -pgo=off -gcflags=-m -o /dev/null . 2>&1 | grep -E 'inlin|devirt' | sort) >"$work/m-off.txt"
(cd "$src" && go build -a -trimpath -pgo="$work/profiles/api.pprof" -gcflags=-m -o /dev/null . 2>&1 | grep -E 'inlin|devirt' | sort) >"$work/m-pgo.txt"
(cd "$src" && go build -a -trimpath -pgo="$work/profiles/api-short.pprof" -gcflags=-m -o /dev/null . 2>&1 | grep -E 'inlin|devirt' | sort) >"$work/m-short.txt"
# The compiler's own account of which call sites the profile made hot.
for p in api api-short; do
  (cd "$src" && go build -a -trimpath -pgo="$work/profiles/$p.pprof" -gcflags=-d=pgodebug=1 -o /dev/null . 2>&1 | grep -v '^#') >"$work/pgodebug-$p.txt"
done

# 6. Build cost: a full rebuild (-a, standard library included) with and without PGO.
printf 'mode\trun\tbuild_s\tbinary_bytes\n' >"$work/builds.tsv"
for run in 1 2 3; do
  for mode in off pgo; do
    pgo=off
    [[ $mode == pgo ]] && pgo="$work/profiles/api.pprof"
    t0=$(python3 -c 'import time; print(time.time())')
    (cd "$src" && go build -a -trimpath -pgo="$pgo" -o "$work/bin/build-$mode" .)
    t1=$(python3 -c 'import time; print(time.time())')
    printf '%s\t%s\t%s\t%s\n' "$mode" "$run" "$(python3 -c "print(round($t1-$t0, 2))")" "$(stat -f %z "$work/bin/build-$mode")" >>"$work/builds.tsv"
  done
done

# 7. Where the CPU time moved: profile the PGO build on the same input, diff against off.
"$work/bin/pgo" run api "$work/api.log" "$PROFILE_REPS" "$work/profiles/api-pgo-build.pprof" >/dev/null
go tool pprof -top -nodecount=14 -diff_base="$work/profiles/api.pprof" "$work/profiles/api-pgo-build.pprof" >"$work/diff-top.txt" 2>/dev/null
go version >"$work/go-version.txt"
echo "done: $work"
