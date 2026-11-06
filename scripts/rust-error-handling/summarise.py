#!/usr/bin/env python3
"""Summarise a measure.sh work dir into scripts/data/rust-error-handling-m2pro.json.

Usage: python3 scripts/rust-error-handling/summarise.py <work-dir> [out.json]

Medians over the five interleaved runs per (variant, fault rate, backtrace)
cell, allocations per line from the count-alloc build, size_of lines, the
env-variable sweep and the probe-crate build times. Nothing is typed in by hand.
"""
import csv
import json
import os
import platform
import statistics as st
import subprocess
import sys
from collections import defaultdict

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/rust-error-handling-m2pro.json"


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def tsv(name):
    return list(csv.DictReader(open(os.path.join(work, name)), delimiter="\t"))


cells = defaultdict(list)
checks = defaultdict(set)
errs = {}
for r in tsv("runs.tsv"):
    k = (r["variant"], int(r["permille"]), int(r["backtrace"]))
    cells[k].append(float(r["ns_per_line"]))
    checks[int(r["permille"])].add(r["checksum"])
    errs[int(r["permille"])] = int(r["err"])
# every variant must render the same error text at the same fault rate
assert all(len(v) == 1 for v in checks.values()), checks

timing = [
    {
        "variant": v, "fault_permille": p, "backtrace": bool(b),
        "ns_per_line_median": round(st.median(xs), 1),
        "ns_per_line_min": round(min(xs), 1), "ns_per_line_max": round(max(xs), 1),
        "runs": len(xs), "errors_per_pass": errs[p],
    }
    for (v, p, b), xs in sorted(cells.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0]))
]

allocs = [
    {
        "variant": r["variant"], "fault_permille": int(r["permille"]), "backtrace": r["backtrace"] == "1",
        "allocs_per_line": float(r["allocs_per_line"]), "alloc_bytes_per_line": float(r["alloc_bytes_per_line"]),
        "errors": int(r["err"]),
    }
    for r in tsv("allocs.tsv")
]
# allocations per *error*, the number a reader can reason about: (with faults - without) / error share
base = {(a["variant"], a["backtrace"]): a for a in allocs if a["fault_permille"] == 0}
for a in allocs:
    if a["fault_permille"] == 1000:
        z = base[(a["variant"], a["backtrace"])]
        a["allocs_per_error"] = round(a["allocs_per_line"] - z["allocs_per_line"], 2)
        a["bytes_per_error"] = round(a["alloc_bytes_per_line"] - z["alloc_bytes_per_line"], 1)

env = defaultdict(list)
for r in tsv("env.tsv"):
    env[r["env"]].append(float(r["ns_per_line"]))
env_sweep = [{"env": e, "ns_per_line_median": round(st.median(xs), 1), "runs": len(xs)} for e, xs in env.items()]

builds = defaultdict(list)
size = {}
for r in tsv("build.tsv"):
    builds[r["crate"]].append(float(r["build_s"]))
    size[r["crate"]] = int(r["binary_bytes"])
build = [
    {"crate": c, "clean_release_build_s_median": round(st.median(xs), 2), "runs": len(xs), "stripped_binary_bytes": size[c]}
    for c, xs in builds.items()
]

dbg = defaultdict(lambda: defaultdict(list))
for r in tsv("debugfmt.tsv"):
    for k in ("debug_first_us", "debug_rest_median_us", "debug_bytes"):
        dbg[r["backtrace"] == "1"][k].append(float(r[k]))
debug_format = [
    {"backtrace": b, "runs": len(m["debug_bytes"]),
     "first_print_us_median": round(st.median(m["debug_first_us"]), 1),
     "later_print_us_median": round(st.median(m["debug_rest_median_us"]), 1),
     "output_bytes": int(st.median(m["debug_bytes"]))}
    for b, m in sorted(dbg.items())
]

sizes = dict(ln.split("=", 1) for ln in open(os.path.join(work, "sizes.txt")).read().split("\n") if "=" in ln)
sizes = {k: int(v) for k, v in sizes.items()}

data = {
    "what": "errbench: one log-record parser, error handling written four ways (thiserror, anyhow, anyhow with eager .context(format!()), thiserror inside + anyhow at the caller)",
    "lines_per_pass": 200000,
    "passes_per_run": 5,
    "host": {
        "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string"),
        "os": f"macOS {platform.mac_ver()[0]}",
        "rustc": sh("rustc", "--version"),
        "cargo": sh("cargo", "--version"),
        "crates": {"anyhow": "1.0.104", "thiserror": "2.0.21"},
    },
    "timing": timing,
    "allocs": allocs,
    "env_sweep_anyhow_5pct": env_sweep,
    "debug_format_anyhow": debug_format,
    "build": build,
    "size_of": sizes,
}
os.makedirs(os.path.dirname(out), exist_ok=True)
json.dump(data, open(out, "w"), indent=1)
print("wrote", out)
