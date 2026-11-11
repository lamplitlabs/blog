#!/usr/bin/env python3
"""Summarise a measure.sh work dir into scripts/data/go-pgo-m2pro.json.

Usage: python3 scripts/go-pgo/summarise.py <work-dir> [out.json]

Per (variant, config): medians over the five interleaved runs of the best
per-pass ns/line, and of instructions and cycles per routed line, where the
reps=0 load-only median is subtracted first and the rest is divided by
lines x reps. Also the PGO-only inlining and devirtualization decisions from
the -m diff, build times, binary sizes and the pprof diff. Nothing is typed in
by hand; every checksum must agree across variants or the script fails.
"""
import csv
import json
import os
import platform
import statistics as st
import subprocess
import sys

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/go-pgo-m2pro.json"
LINES = 1_000_000
REPS = 5
VARIANTS = ["off", "pgo", "pgo-noinline", "pgo-nodevirt", "pgo-short", "pgo-batchprof", "pgo-merged", "pgo-iter2"]
CONFIGS = ["api", "batch"]


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def rows(name):
    with open(os.path.join(work, name)) as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


runs, load = rows("runs.tsv"), rows("load.tsv")
checks = {}
for r in runs:
    checks.setdefault(r["config"], set()).add(r["checksum"])
for c, s in checks.items():
    if len(s) != 1:
        sys.exit(f"checksum mismatch for {c}: {s}")

load_med = {}
for v in VARIANTS:
    for c in CONFIGS:
        sel = [r for r in load if r["variant"] == v and r["config"] == c]
        load_med[(v, c)] = {k: st.median(float(r[k]) for r in sel) for k in ("instructions", "cycles")}

cells = {}
for v in VARIANTS:
    for c in CONFIGS:
        sel = [r for r in runs if r["variant"] == v and r["config"] == c]
        per = lambda k: [(float(r[k]) - load_med[(v, c)][k]) / (LINES * REPS) for r in sel]
        ins, cyc = per("instructions"), per("cycles")
        cells[f"{v}/{c}"] = {
            "runs": len(sel),
            "best_ns_per_line_median": round(st.median(float(r["best_ns"]) for r in sel), 1),
            "best_ns_per_line_min": round(min(float(r["best_ns"]) for r in sel), 1),
            "best_ns_per_line_max": round(max(float(r["best_ns"]) for r in sel), 1),
            "instructions_per_line_median": round(st.median(ins), 1),
            "instructions_per_line_spread_pct": round(100 * (max(ins) - min(ins)) / st.median(ins), 2),
            "cycles_per_line_median": round(st.median(cyc), 1),
            "cycles_per_line_min": round(min(cyc), 1),
            "ipc_median": round(st.median(i / y for i, y in zip(ins, cyc)), 3),
        }

for v in VARIANTS:
    for c in CONFIGS:
        base, cell = cells[f"off/{c}"], cells[f"{v}/{c}"]
        for k in ("best_ns_per_line_median", "instructions_per_line_median", "cycles_per_line_median", "cycles_per_line_min"):
            cell[k.replace("_median", "").replace("_min", "_min") + "_vs_off_pct"] = round(100 * (cell[k] / base[k] - 1), 1)


def lines(name):
    with open(os.path.join(work, name)) as fh:
        return [l.rstrip("\n") for l in fh]


m_off, m_pgo = set(lines("m-off.txt")), set(lines("m-pgo.txt"))
only_pgo = sorted(m_pgo - m_off)
only_off = sorted(m_off - m_pgo)
strip = lambda l: l.replace("example.com/logroute/", "")

builds = rows("builds.tsv")
build = {}
for mode in ("off", "pgo"):
    sel = [r for r in builds if r["mode"] == mode]
    build[mode] = {
        "full_rebuild_s_median": st.median(float(r["build_s"]) for r in sel),
        "binary_bytes": int(sel[0]["binary_bytes"]),
    }

pprof_samples = {}
for p in sorted(os.listdir(os.path.join(work, "profiles"))):
    head = sh("go", "tool", "pprof", "-top", "-nodecount=1", os.path.join(work, "profiles", p))
    for l in head.splitlines():
        if l.startswith("Duration:"):
            pprof_samples[p] = l
    pprof_samples[p + ":bytes"] = os.path.getsize(os.path.join(work, "profiles", p))

data = {
    "machine": {
        "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string"),
        "cores": int(sh("sysctl", "-n", "hw.ncpu") or 0),
        "os": f"macOS {platform.mac_ver()[0]}",
        "go": open(os.path.join(work, "go-version.txt")).read().strip(),
    },
    "method": "measure.sh: 1,000,000 seeded lines per config, 5 passes per run, 5 interleaved runs per (variant, config). "
              "Per-line counters subtract the reps=0 load-only median. best_ns is the fastest of 5 passes in a run.",
    "checksums": {c: next(iter(s)) for c, s in checks.items()},
    "cells": cells,
    "m_diff": {"only_with_pgo": [strip(l) for l in only_pgo], "only_without_pgo": [strip(l) for l in only_off],
               "inlining_lines_off": sum("inlin" in l for l in m_off), "inlining_lines_pgo": sum("inlin" in l for l in m_pgo)},
    "builds": build,
    "profiles": pprof_samples,
    "diff_top": lines("diff-top.txt"),
}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print("wrote", out)
for k, v in cells.items():
    print(f"{k:22s} ns={v['best_ns_per_line_median']:7.1f} ins={v['instructions_per_line_median']:7.1f} "
          f"({v['instructions_per_line_vs_off_pct']:+5.1f}%) cyc={v['cycles_per_line_median']:6.1f} "
          f"({v['cycles_per_line_vs_off_pct']:+5.1f}%) ipc={v['ipc_median']}")
