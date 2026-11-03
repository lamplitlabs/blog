#!/usr/bin/env python3
"""Summarise a measure.sh work dir into scripts/data/rust-profiling-logstat-m2pro.json.

Usage: python3 scripts/rust-profiling-logstat/summarise.py <work-dir> [out.json]

Medians over the five interleaved runs per version for wall time, user CPU,
instructions retired and cycles (from /usr/bin/time -l); allocations per line
from the count-alloc build; per-frame inclusive and self sample shares from
each version's folded profile. Nothing is typed in by hand.
"""
import csv
import json
import os
import platform
import statistics as st
import subprocess
import sys
from collections import Counter

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/rust-profiling-logstat-m2pro.json"
VERSIONS = ["v0", "v1", "v2", "v3", "v4"]


def sh(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


rows = list(csv.DictReader(open(os.path.join(work, "counters.tsv")), delimiter="\t"))
allocs = {r["version"]: float(r["allocs_per_line"]) for r in csv.DictReader(open(os.path.join(work, "allocs.tsv")), delimiter="\t")}

data = {
    "host": {
        "cpu": sh("sysctl", "-n", "machdep.cpu.brand_string"),
        "cores": sh("sysctl", "-n", "hw.ncpu"),
        "os": "macOS " + platform.mac_ver()[0],
        "rustc": sh("rustc", "-V"),
    },
    "input": {"lines": 1_000_000, "bytes": os.path.getsize(os.path.join(work, "access.log"))},
    "versions": {},
}
for v in VERSIONS:
    rs = [r for r in rows if r["version"] == v]
    med = lambda k, f=float: st.median(f(r[k]) for r in rs)
    prof = Counter()
    selfc = Counter()
    total = 0
    for line in open(os.path.join(work, f"{v}.folded")):
        stack, _, n = line.rstrip().rpartition(" ")
        n = int(n)
        frames = stack.split(";")
        total += n
        for f in set(frames):
            prof[f] += n
        selfc[frames[-1]] += n
    data["versions"][v] = {
        "runs": len(rs),
        "checksums": sorted({r["checksum"] for r in rs}),
        "wall_ms_median": med("wall_ms"),
        "wall_ms_min": min(float(r["wall_ms"]) for r in rs),
        "wall_ms_max": max(float(r["wall_ms"]) for r in rs),
        "user_s_median": med("user_s"),
        "instructions_median": med("instructions", int),
        "cycles_median": med("cycles", int),
        "max_rss_mb_median": round(med("max_rss_bytes", int) / 2**20, 1),
        "allocs_per_line": allocs[v],
        "profile_samples": total,
        "inclusive_pct": {f: round(100 * n / total, 1) for f, n in prof.most_common() if n / total >= 0.02},
        "self_pct": {f: round(100 * n / total, 1) for f, n in selfc.most_common(12)},
    }
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as fh:
    json.dump(data, fh, indent=1)
print("wrote", out)
for v in VERSIONS:
    d = data["versions"][v]
    print(v, d["wall_ms_median"], d["user_s_median"], f'{d["instructions_median"]/1e9:.2f}G', f'{d["cycles_median"]/1e9:.2f}G', d["allocs_per_line"], d["checksums"])
