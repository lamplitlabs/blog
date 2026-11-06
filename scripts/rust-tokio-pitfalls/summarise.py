#!/usr/bin/env python3
"""Summarise <work-dir>/results.txt from measure.sh into one JSON document.

  python3 scripts/rust-tokio-pitfalls/summarise.py <work-dir> > scripts/data/rust-tokio-pitfalls-m2pro.json

Every metric is the median over the repetitions; min and max are kept beside it
so the spread is visible.
"""
import json
import platform
import re
import statistics
import subprocess
import sys
from collections import defaultdict

work = sys.argv[1]
lines = open(f"{work}/results.txt").read().splitlines()

meta = {}
loads = []
groups = defaultdict(list)
for ln in lines:
    if ln.startswith("# rep="):
        loads.append(float(re.search(r"load=([\d.]+)", ln).group(1)))
        continue
    if ln.startswith("#"):
        k, _, v = ln[2:].partition(": ")
        meta[k] = v
        continue
    kv = dict(p.split("=", 1) for p in ln.split())
    key_fields = ("experiment", "variant", "burst", "items", "work", "tasks", "files")
    key = tuple((k, kv[k]) for k in key_fields if k in kv)
    groups[key].append({k: float(v) for k, v in kv.items() if k not in key_fields})


def num(v):
    try:
        return int(v)
    except ValueError:
        return v


out = defaultdict(list)
for key, runs in groups.items():
    row = {k: num(v) for k, v in key if k != "experiment"}
    row["runs"] = len(runs)
    for m in runs[0]:
        vals = sorted(r[m] for r in runs)
        row[m] = round(statistics.median(vals), 3)
        if m in ("p99_us", "p999_us", "ns_per_op", "ns_per_item", "us_per_file", "wall_ms", "total_ms"):
            row[m + "_min"] = round(vals[0], 3)
            row[m + "_max"] = round(vals[-1], 3)
    out[dict(key)["experiment"]].append(row)


def sh(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


doc = {
    "host": {
        "cpu": sh(["sysctl", "-n", "machdep.cpu.brand_string"]) or platform.machine(),
        "os": f"macOS {platform.mac_ver()[0]}" if platform.mac_ver()[0] else platform.platform(),
        "rustc": meta.get("rustc", ""),
        "crates": {"tokio": "1.53.1", "parking_lot": "0.12.5"},
        "tokio_worker_threads": 4,
        "load_avg_1m_per_rep": loads,
    },
    "date": meta.get("date", ""),
    "reps": max(len(r) for r in groups.values()),
    "workloads": {
        "blocking": "4,000 light requests/s (~40 us CPU each) from an open-loop spinning generator thread for 4 s, "
                    "plus 20 heavy jobs/s (~37 ms CPU each) arriving in bursts of `burst`; latency from scheduled arrival",
        "mutex": "64 tasks x 20,000 HashMap increments under one mutex, yield every 64 ops",
        "held": "500 tasks: lock a tokio::sync::Mutex, update, then a 2 ms fake network call (guard held vs dropped)",
        "spawn": "200,000,000 xorshift rounds split into items of `work` rounds; per-item spawn vs JoinSet vs 16 chunks vs inline",
        "fs": "read 5,000 cached 4 KiB files",
    },
}
for k in ("blocking", "mutex", "held", "spawn", "fs"):
    doc[k] = out[k]
json.dump(doc, sys.stdout, indent=1)
print()
