#!/usr/bin/env python3
"""Summarise run_gates.py output into scripts/data/ai-review-gates-go.json.

Usage: python3 scripts/ai-review-gates/summarise.py <work-dir> [out.json]

Per case: which gates failed (and on how many of the reps), the first finding
of each failing gate, and median gate wall time. Per gate: defects caught,
benign PRs blocked, defects caught by that gate alone, median seconds per PR.
Nothing is typed in by hand.
"""
import json
import os
import platform
import statistics as st
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from corpus import FAKE_KEY  # noqa: E402

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/ai-review-gates-go.json"
R = json.load(open(f"{work}/results.json"))
gates = R["gates"]
block = [g["id"] for g in gates if g["kind"] == "block"]
cases = [c for c in R["cases"] if c["id"] != "BASE"]
base = next(c for c in R["cases"] if c["id"] == "BASE")
assert not any(v["fail"] for v in base["gates"].values()), "base tree must pass every gate"

defects = [c for c in cases if c["cls"] != "benign"]
benign = [c for c in cases if c["cls"] == "benign"]


def failed(c, g):
    return c["gates"][g]["fail"]


per_case = []
for c in cases:
    hit = [g["id"] for g in gates if failed(c, g["id"])]
    per_case.append({
        "id": c["id"], "cls": c["cls"], "title": c["title"], "diff_lines": c["diff_lines"],
        "failed_gates": hit,
        "flaky": {g: f"{sum(c['gates'][g]['fails'])}/{len(c['gates'][g]['fails'])}"
                  for g in hit if not all(c["gates"][g]["fails"])},
        "blocked": any(g in block for g in hit),
        "advisory_only": bool(hit) and not any(g in block for g in hit),
        "findings": {g: c["gates"][g]["finding"] for g in hit},
        # the seeded fake key stays split in the repository (see corpus.py)
        "diff": c["diff"].replace(FAKE_KEY, FAKE_KEY[:6] + "<fake key, see corpus.py>"),
    })

per_gate = []
for g in gates:
    gid = g["id"]
    alone = [c["id"] for c in defects
             if failed(c, gid) and not any(failed(c, o) for o in block if o != gid)]
    per_gate.append({
        "id": gid, "label": g["label"], "kind": g["kind"],
        "defects_caught": sum(failed(c, gid) for c in defects),
        "benign_flagged": [c["id"] for c in benign if failed(c, gid)],
        "only_gate_for": alone,
        "seconds_median": round(st.median(st.median(c["gates"][gid]["seconds"]) for c in R["cases"]), 3),
    })

# cumulative: defects blocked after gates 1..k in CI order (blocking gates only)
cum, seen = [], set()
for gid in block:
    seen |= {c["id"] for c in defects if failed(c, gid)}
    cum.append({"after": gid, "blocked": len(seen)})

by_cls = {}
for c in per_case:
    if c["cls"] == "benign":
        continue
    b = by_cls.setdefault(c["cls"], {"total": 0, "blocked": 0, "advisory": 0, "escaped": []})
    b["total"] += 1
    if c["blocked"]:
        b["blocked"] += 1
    elif c["advisory_only"]:
        b["advisory"] += 1
    else:
        b["escaped"].append(c["id"])

wall = [sum(st.median(c["gates"][g["id"]]["seconds"]) for g in gates) for c in R["cases"]]
cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout.strip()
json.dump({
    "host": {"cpu": cpu or platform.machine(), "os": platform.platform(terse=True)},
    "go": R["go"], "gitleaks": R["gitleaks"], "reps": R["reps"],
    "totals": {
        "defects": len(defects), "benign": len(benign),
        "blocked": sum(c["blocked"] for c in per_case if c["cls"] != "benign"),
        "advisory_only": sum(c["advisory_only"] for c in per_case if c["cls"] != "benign"),
        "not_blocked": [c["id"] for c in per_case if c["cls"] != "benign" and not c["blocked"]],
        "unflagged": [c["id"] for c in per_case if c["cls"] != "benign" and not c["failed_gates"]],
        "benign_blocked": [c["id"] for c in per_case if c["cls"] == "benign" and c["blocked"]],
        "benign_advisory": [c["id"] for c in per_case if c["cls"] == "benign" and c["advisory_only"]],
        "advisory_flagged": {g["id"]: [c["id"] for c in per_case if g["id"] in c["failed_gates"]]
                             for g in gates if g["kind"] == "advisory"},
        "pipeline_seconds_median": round(st.median(wall), 2),
        "pipeline_seconds_max": round(max(wall), 2),
    },
    "gates": per_gate, "cumulative": cum, "by_class": by_cls, "cases": per_case,
}, open(out, "w"), indent=1)
print(f"wrote {out}")
