#!/usr/bin/env python3
"""Summarise a measure.sh work dir into scripts/data/guardrail-redos-m2pro.json.

Usage: python3 scripts/guardrail-redos/summarise.py <work-dir> [out.json]

Bench timings are the median over the reps of each rep's own median. Load tests
pool the benign requests of every rep per (engine, variant) and report counts by
status and latency percentiles from each request's scheduled send time.
Nothing is typed in by hand.
"""
import csv
import glob
import json
import os
import re
import statistics as st
import sys
from collections import defaultdict

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/guardrail-redos-m2pro.json"
here = os.path.dirname(os.path.abspath(__file__))
rules = json.load(open(os.path.join(here, "rules.json")))


def kv(path):
    d = {}
    for line in open(path):
        if ":" in line:
            k, v = line.split(":", 1)
            d[k.strip()] = v.strip()
    return d


def tsv(path):
    with open(path, newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = min(len(xs) - 1, max(0, int(round(p / 100 * len(xs) + 0.5)) - 1))
    return xs[k]


env = kv(os.path.join(work, "env.txt"))
meta = kv(os.path.join(work, "load-meta.txt"))

compile_rows = [
    {"rule": r[2], "variant": r[3], "ok": r[4] == "ok", "micros": int(r[5]), "message": r[6]}
    for r in tsv(os.path.join(work, "compile.tsv"))
]

# ---- benches
cells = defaultdict(list)        # (kind, engine, rule, variant, n) -> [ms]
meta_cells = {}                  # same key -> (bytes, matched)
benign_hits = {}
pos = {}
engine_names = {}
for path in sorted(glob.glob(os.path.join(work, "bench-*-*.tsv"))):
    tag = re.match(r"bench-(.+)-(\d+)\.tsv", os.path.basename(path)).group(1)
    for r in tsv(path):
        if len(r) < 8:
            continue
        kind, engine, rule, variant, n, nbytes, ms, matched = r[:8]
        engine_names[tag] = engine
        if kind == "pos":
            pos[(tag, rule, variant)] = matched == "True"
            continue
        key = (kind, tag, rule, variant, int(n))
        cells[key].append(float(ms))
        meta_cells[key] = (int(nbytes), matched)
        if kind == "benign":
            benign_hits[(tag, rule, variant)] = matched

bench = []
for key, xs in sorted(cells.items()):
    kind, tag, rule, variant, n = key
    nbytes, matched = meta_cells[key]
    bench.append({
        "kind": kind, "engine": tag, "rule": rule, "variant": variant, "n": n, "bytes": nbytes,
        "ms": round(st.median(xs), 4), "ms_runs": [round(x, 4) for x in xs],
        "capped": matched == "capped" or any(x >= rules["cap_s"] * 1000 for x in xs),
        "matched": matched,
    })

# worst ordinary line per (engine, rule, variant): the longest natural step reached
natural_worst = []
for (tag, rule, variant) in sorted({(b["engine"], b["rule"], b["variant"]) for b in bench if b["kind"] == "natural"}):
    steps = [b for b in bench if b["kind"] == "natural" and b["engine"] == tag and b["rule"] == rule and b["variant"] == variant]
    last = max(steps, key=lambda b: b["n"])
    natural_worst.append({"engine": tag, "rule": rule, "variant": variant, "words": last["n"],
                          "bytes": last["bytes"], "ms": last["ms"], "capped": last["capped"]})

# ---- load tests
load = []
for engine in ("rust", "go", "node", "nodefb", "python"):
    for variant in ("naive", "hardened"):
        files = sorted(glob.glob(os.path.join(work, f"load-{engine}-{variant}-*.tsv")))
        if not files:
            continue
        status = defaultdict(int)
        poison_status = defaultdict(int)
        ok_lat, all_lat, poison_lat = [], [], []
        per_rep_fail = []
        for f in files:
            fails = 0
            n = 0
            for kind, sched, lat, s in tsv(f):
                lat = float(lat)
                if kind == "poison":
                    poison_status[s.split(":")[0]] += 1
                    poison_lat.append(lat)
                    continue
                n += 1
                status[s.split(":")[0]] += 1
                all_lat.append(lat)
                if s == "200":
                    ok_lat.append(lat)
                else:
                    fails += 1
            per_rep_fail.append(round(100 * fails / n, 2))
        total = sum(status.values())
        load.append({
            "engine": engine, "variant": variant, "reps": len(files),
            "benign_requests": total, "benign_status": dict(status),
            "benign_failed_pct": round(100 * (total - status.get("200", 0)) / total, 2),
            "benign_failed_pct_per_rep": per_rep_fail,
            "ok_p50_ms": pct(ok_lat, 50), "ok_p99_ms": pct(ok_lat, 99), "ok_max_ms": max(ok_lat) if ok_lat else None,
            "poison_requests": sum(poison_status.values()), "poison_status": dict(poison_status),
            "poison_p50_ms": pct(poison_lat, 50),
        })

shots = {}
for name in ("curl.txt", "compile.txt", "v8-linear.txt"):
    p = os.path.join(work, "shots", name)
    if os.path.exists(p):
        shots[name] = open(p).read()

benign_path = os.path.join(work, "benign.txt")
benign_lines = open(benign_path, encoding="utf-8").read().splitlines()

doc = {
    "about": "ReDoS in AI guardrail regexes: five rules, naive vs hardened, five engines. Written by scripts/guardrail-redos/summarise.py from a measure.sh run.",
    "host": env,
    "engines": engine_names,
    "rules": [{k: r[k] for k in ("name", "what", "flags", "mode", "naive", "hardened")} for r in rules["rules"]],
    "budget_ms": rules["budget_ms"],
    "cap_s": rules["cap_s"],
    "benign_corpus": {"lines": len(benign_lines), "bytes": sum(len(x.encode()) + 1 for x in benign_lines),
                      "sources": "GSM8K test questions and answers, TruthfulQA questions"},
    "positives_all_matched": {f"{t}/{r}/{v}": ok for (t, r, v), ok in sorted(pos.items())},
    "benign_matches": {f"{t}/{r}/{v}": h for (t, r, v), h in sorted(benign_hits.items())},
    "compile": compile_rows,
    "bench": bench,
    "natural_worst": natural_worst,
    "load_meta": meta,
    "load": load,
    "shots": shots,
}
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w") as f:
    json.dump(doc, f, indent=1)
    f.write("\n")
print("wrote", out, f"{len(bench)} bench cells, {len(load)} load cells", file=sys.stderr)
