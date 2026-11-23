#!/usr/bin/env python3
"""Summarise a measure.py work dir into scripts/data/ai-sdlc-flaky-gates-go.json.

Usage: python3 scripts/ai-sdlc-flaky-gates/summarise.py <work-dir> [out.json]

Per (case, mode): failing runs out of all runs with a Wilson 95% interval,
median wall seconds, which tests failed and how often the race detector spoke.
Per CI policy: how often each case would merge, judged on the recorded runs
themselves, not on an independence model. A policy with k attempts takes
consecutive, non-overlapping groups of k runs in one mode; the PR merges if
any attempt in its group is green (that is what "re-run failed jobs" does),
and costs the seconds of the attempts it used. An "all" policy is the inverse:
it merges only if every run in the group is green. Nothing is typed in by hand;
the script fails if the unpatched base tree ever went red.
"""
import collections
import json
import math
import re
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from corpus import CASES  # noqa: E402

work = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "scripts/data/ai-sdlc-flaky-gates-go.json"
meta = json.load(open(os.path.join(work, "meta.json")))
runs = collections.defaultdict(list)
for line in open(os.path.join(work, "runs.jsonl")):
    r = json.loads(line)
    runs[(r["case"], r["mode"])].append(r)
for v in runs.values():
    v.sort(key=lambda r: r["rep"])
MODES = list(meta["modes"])
assert not any(r["rc"] for m in MODES for r in runs[("BASE", m)]), "base tree went red; fix the host before publishing"


def wilson(k, n, z=1.96):
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round(max(0.0, (c - h) / d), 4), round(min(1.0, (c + h) / d), 4)]


cases = []
for c in CASES:
    row = {"id": c["id"], "kind": c["kind"], "title": c["title"], "src": c.get("src"),
           "vet": meta["builds"][c["id"]]["vet"], "modes": {}}
    for m in MODES:
        rs = runs[(c["id"], m)]
        k = sum(1 for r in rs if r["rc"])
        tests = collections.Counter(t for r in rs for t in r["fails"])
        row["modes"][m] = {"n": len(rs), "fail": k, "rate": round(k / len(rs), 4) if rs else 0.0,
                           "ci95": wilson(k, len(rs)),
                           "race_reports": sum(1 for r in rs if r["race"]),
                           "median_s": round(st.median(r["s"] for r in rs), 4) if rs else 0.0,
                           "failing_tests": dict(tests.most_common())}
    cases.append(row)

POLICIES = [
    {"id": "plain1", "label": "go test, one run", "mode": "plain", "attempts": 1},
    {"id": "plain3", "label": "go test, re-run failed job (up to 3 tries)", "mode": "plain", "attempts": 3},
    {"id": "plain_all3", "label": "go test 3 times, every run must pass", "mode": "plain", "attempts": 3, "all": True},
    {"id": "shuffle1", "label": "go test -shuffle=on, one run", "mode": "shuffle", "attempts": 1},
    {"id": "race1", "label": "go test -race, one run", "mode": "race", "attempts": 1},
    {"id": "rs1", "label": "go test -race -shuffle=on, one run", "mode": "race_shuffle", "attempts": 1},
    {"id": "rs3", "label": "go test -race -shuffle=on, re-run (up to 3 tries)", "mode": "race_shuffle", "attempts": 3},
    {"id": "stress", "label": "go test -race -shuffle=on -count=10, one run", "mode": "stress10", "attempts": 1},
]


def policy(p, cid):
    rs = runs[(cid, p["mode"])]
    k = p["attempts"]
    groups = [rs[i:i + k] for i in range(0, len(rs) - k + 1, k)]
    merged, secs, retried = 0, [], 0
    for g in groups:
        used = 0.0
        ok = False
        if p.get("all"):
            # the inverse of a retry: a red on any run of the same commit blocks
            used = sum(r["s"] for r in g)
            ok = not any(r["rc"] for r in g)
        else:
            for j, r in enumerate(g):
                used += r["s"]
                if not r["rc"]:
                    ok = True
                    retried += j > 0
                    break
        merged += ok
        secs.append(used)
    return {"groups": len(groups), "merged": merged, "merge_rate": round(merged / len(groups), 4) if groups else 0.0,
            "green_after_red": retried, "median_s": round(st.median(secs), 4) if secs else 0.0,
            "mean_s": round(st.mean(secs), 4) if secs else 0.0}


pol = []
for p in POLICIES:
    per = {c["id"]: policy(p, c["id"]) for c in CASES}
    bykind = collections.defaultdict(list)
    for c in CASES:
        bykind[c["kind"]].append(per[c["id"]]["merge_rate"])
    pol.append(dict(p, cases=per,
                    defect_merge_mean=round(st.mean(bykind["defect"]), 4),
                    test_flake_merge_mean=round(st.mean(bykind["test-flake"]), 4),
                    correct_block_mean=round(1 - st.mean(bykind["correct"] + bykind["control"]), 4),
                    median_s_correct=round(st.median(per[c["id"]]["median_s"] for c in CASES if c["kind"] in ("correct", "control")), 4)))

# Retry curve: chance a PR merges when CI re-runs a red job up to k times, from the plain
# runs. Sliding windows over the recorded sequence, all k from the same start positions,
# so the curve cannot dip from one k to the next by picking different groups.
KMAX = 5
curve = {}
for c in CASES:
    if c["kind"] in ("defect", "test-flake"):
        rs = runs[(c["id"], "plain")]
        starts = range(len(rs) - KMAX + 1)
        curve[c["id"]] = [round(sum(any(not r["rc"] for r in rs[i:i + k]) for i in starts) / len(starts), 4)
                          for k in range(1, KMAX + 1)]

samples = {}
sd = os.path.join(work, "samples")
for f in sorted(os.listdir(sd)) if os.path.isdir(sd) else []:
    txt = open(os.path.join(sd, f)).read()[:6000]
    # keep paths relative: <work>/trees/<id>/x.go -> x.go, GOROOT -> $GOROOT
    txt = re.sub(r"\S*/trees/[A-Z0-9]+/", "", txt)
    txt = re.sub(r"\S*/libexec/src/", "$GOROOT/src/", txt)
    samples[f[:-4]] = txt

# Busy-runner rounds from contention.py (optional): fail rate per case with P binaries at once.
contention = {}
cp = os.path.join(work, "contention.jsonl")
if os.path.exists(cp):
    crs = [json.loads(l) for l in open(cp)]
    assert not any(r["rc"] for r in crs if r["case"] == "BASE"), "base tree went red under contention"
    for c in CASES:
        rs = [r for r in crs if r["case"] == c["id"]]
        k = sum(1 for r in rs if r["rc"])
        contention[c["id"]] = {"n": len(rs), "fail": k, "rate": round(k / len(rs), 4) if rs else 0.0,
                                "ci95": wilson(k, len(rs)), "median_s": round(st.median(r["s"] for r in rs), 3) if rs else 0.0,
                                "failing_tests": dict(collections.Counter(t for r in rs for t in r["fails"]).most_common())}
    contention = {"parallel": crs[0]["parallel"], "rounds": len({r["round"] for r in crs}),
                  "load1_median": round(st.median(r["load1"] for r in crs), 2), "cases": contention}

# Optional timing.py output: race runtime with and without its 1 s exit sleep.
timing = {}
tp = os.path.join(work, "timing.jsonl")
if os.path.exists(tp):
    trs = [json.loads(l) for l in open(tp)]
    for v in ("plain", "race", "race_nosleep", "stress10_nosleep"):
        green = [r["s"] for r in trs if r["variant"] == v and not r["rc"]]
        timing[v] = {"runs": sum(1 for r in trs if r["variant"] == v), "green_runs": len(green),
                     "green_median_s": round(st.median(green), 4) if green else 0.0}
    # per-case red runs with and without the exit sleep (F1/F4 are random either way, so
    # compare counts, not single seeds)
    timing["fails_by_case"] = {c["id"]: {v: sum(1 for r in trs if r["case"] == c["id"] and r["variant"] == v and r["rc"])
                                         for v in ("plain", "race", "race_nosleep", "stress10_nosleep")} for c in CASES}
    timing["reps"] = max(r["rep"] for r in trs)

loads = [r["load1"] for v in runs.values() for r in v]
data = {
    "host": {"cpu": meta["cpu"], "os": meta["os"], "ncpu": meta["ncpu"],
             "load1_median": round(st.median(loads), 2), "load1_max": max(loads)},
    "go": meta["go"],
    "modes": meta["modes"],
    "total_runs": sum(len(v) for v in runs.values()),
    "cases": cases,
    "policies": pol,
    "retry_curve_plain": curve,
    "contention": contention,
    "timing": timing,
    "samples": samples,
}
json.dump(data, open(out, "w"), indent=1)
print("wrote", out, data["total_runs"], "runs")
for p in pol:
    print(f'{p["id"]:9s} defects merge {p["defect_merge_mean"]:.3f}  test-flakes merge {p["test_flake_merge_mean"]:.3f}  '
          f'correct blocked {p["correct_block_mean"]:.3f}  median {p["median_s_correct"]:.3f}s')
