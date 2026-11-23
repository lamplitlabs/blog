#!/usr/bin/env python3
"""Summarise a measure.sh work dir into scripts/data/rust-pgo-vs-go-m2pro.json.

Usage: python3 scripts/rust-pgo/summarise.py <work-dir> [out.json]

Per (variant, config): medians over the ROUNDS (default 10) interleaved runs of the best
per-pass ns/line, and of instructions and cycles per routed line, where the
reps=0 load-only median is subtracted first and the rest is divided by
lines x reps. Percentages are against the same language's default build
(rs-off for Rust, go-off for Go). Also the rustc remarks (indirect-call
promotions, inlining counts), build times and binary sizes. Nothing is typed
in by hand; the checksum of every variant must equal Go's for each config.
"""
import csv
import json
import os
import platform
import re
import statistics as st
import subprocess
import sys

work = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "..", "data", "rust-pgo-vs-go-m2pro.json")
LINES, REPS = 1_000_000, 5  # REPS passes per timed run


def rows(name):
    with open(os.path.join(work, name)) as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


load, runs = rows("load.tsv"), rows("runs.tsv")
variants = list(dict.fromkeys(r["variant"] for r in runs))
configs = ["api", "batch"]

checks = {}
for r in runs:
    checks.setdefault(r["config"], set()).add(r["checksum"])
for c, s in checks.items():
    if len(s) != 1:
        sys.exit(f"checksum mismatch for {c}: {s}")


def med(xs):
    return st.median(xs)


cells = {}
for v in variants:
    for c in configs:
        lo = [r for r in load if r["variant"] == v and r["config"] == c]
        rr = [r for r in runs if r["variant"] == v and r["config"] == c]
        base_ins = med([int(r["instructions"]) for r in lo])
        base_cyc = med([int(r["cycles"]) for r in lo])
        ins = [(int(r["instructions"]) - base_ins) / (LINES * REPS) for r in rr]
        cyc = [(int(r["cycles"]) - base_cyc) / (LINES * REPS) for r in rr]
        cells[f"{v}/{c}"] = {
            "best_ns_per_line_median": round(med([float(r["best_ns"]) for r in rr]), 1),
            "best_ns_per_line_runs": [float(r["best_ns"]) for r in rr],
            "instructions_per_line_median": round(med(ins), 1),
            "instructions_per_line_spread_pct": round((max(ins) - min(ins)) / med(ins) * 100, 2),
            "cycles_per_line_median": round(med(cyc), 1),
            "ipc_median": round(med(ins) / med(cyc), 2),
            "max_rss_mb_median": round(med([int(r["max_rss"]) for r in rr]) / 2**20, 1),
            "checksum": rr[0]["checksum"],
        }
for k, cell in cells.items():
    v, c = k.split("/")
    base = cells[("go-off" if v.startswith("go") else "rs-off") + "/" + c]
    for key, src in (("instructions_per_line_vs_off_pct", "instructions_per_line_median"),
                     ("cycles_per_line_vs_off_pct", "cycles_per_line_median"),
                     ("ns_per_line_vs_off_pct", "best_ns_per_line_median")):
        cell[key] = round((cell[src] / base[src] - 1) * 100, 1)
    go = cells["go-off/" + c]
    cell["instructions_per_line_vs_go_off_pct"] = round((cell["instructions_per_line_median"] / go["instructions_per_line_median"] - 1) * 100, 1)

# rustc remarks
NOTE = re.compile(r"src/main\.rs:(\d+):(\d+) (pgo-icall-prom|inline) \((\w+)\): (.*)$")
SYM = re.compile(r"_ZN\d+_\$LT\$logroute\.\.(\w+)\$u20\$as\$u20\$logroute\.\.(\w+)\$GT\$\d+(\w+?)17h[0-9a-f]+E")


def demangle(s):
    s = SYM.sub(lambda m: f"<{m.group(1)} as {m.group(2)}>::{m.group(3)}", s)
    return re.sub(r"_ZN\d+logroute\d+(\w+?)17h[0-9a-f]+E", r"\1", s)


remarks = {}
for name in ("off", "pgo", "pgo-noicp", "pgo-batchprof"):  # measure.sh step 6
    icp, inl_ok, inl_missed = [], 0, 0
    with open(os.path.join(work, f"remarks-{name}.txt")) as fh:
        for line in fh:
            m = NOTE.search(line)
            if not m:
                continue
            if m.group(3) == "pgo-icall-prom" and m.group(4) == "success":
                icp.append({"line": int(m.group(1)), "text": demangle(m.group(5))})
            elif m.group(3) == "inline":
                if m.group(4) == "success":
                    inl_ok += 1
                else:
                    inl_missed += 1
    remarks[name] = {"icall_promotions": icp, "inline_success": inl_ok, "inline_missed": inl_missed}

builds = {}
for r in rows("builds.tsv"):
    b = builds.setdefault(r["mode"], {"seconds": [], "bytes": int(r["bytes"])})
    b["seconds"].append(float(r["seconds"]))
for b in builds.values():
    b["seconds_median"] = med(b["seconds"])

inst = rows("instrumented.tsv")
codesize = {r["variant"]: {k: int(v) for k, v in r.items() if k != "variant"} for r in rows("codesize.tsv")}
vers = open(os.path.join(work, "versions.txt")).read()
data = {
    "host": {"cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip(),
             "os": platform.platform(),
             "rustc": re.search(r"rustc [^\n]+", vers).group(0),
             "llvm": re.search(r"LLVM version: (\S+)", vers).group(1),
             "go": re.search(r"go version (\S+)", vers).group(1)},
    "lines": LINES, "reps": REPS,
    "cells": cells,
    "instrumented": inst,
    "remarks": remarks,
    "builds": builds,
    "codesize": codesize,
}
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w") as fh:
    json.dump(data, fh, indent=2)
    fh.write("\n")
print("wrote", out)
for k, v in cells.items():
    print(f"{k:22s} ns={v['best_ns_per_line_median']:7.1f} ({v['ns_per_line_vs_off_pct']:+5.1f}%) "
          f"ins={v['instructions_per_line_median']:7.1f} ({v['instructions_per_line_vs_off_pct']:+5.1f}%, "
          f"vs go-off {v['instructions_per_line_vs_go_off_pct']:+5.1f}%) cyc={v['cycles_per_line_median']:6.1f} "
          f"({v['cycles_per_line_vs_off_pct']:+5.1f}%) ipc={v['ipc_median']} spread={v['instructions_per_line_spread_pct']}%")
for n, r in remarks.items():
    print(n, "icp", len(r["icall_promotions"]), "inline ok", r["inline_success"], "missed", r["inline_missed"])
for m, b in builds.items():
    print(m, b["seconds_median"], b["bytes"])
for r in inst:
    print(r)
for v, r in codesize.items():
    print(v, r)
