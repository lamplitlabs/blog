#!/usr/bin/env python3
"""Summarise both arms (default AGENTS.md, merge-friendly AGENTS.md) into one JSON for the post.

Usage: python3 scripts/agent-pr-merge-queue/summarise.py [WORK_DEFAULT] [WORK_SPLIT]
       (default .tmp/merge-queue .tmp/merge-queue-split)
Writes scripts/data/agent-pr-merge-queue.json.
"""
import collections
import csv
import json
import os
import platform
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "agent-pr-merge-queue.json")
WORKS = {"default": sys.argv[1] if len(sys.argv) > 1 else ".tmp/merge-queue",
         "split": sys.argv[2] if len(sys.argv) > 2 else ".tmp/merge-queue-split"}
PATCHDIR = {"default": "patches", "split": "patches-split"}
RUNS = {"default": "agent_runs.tsv", "split": "agent_runs_split.tsv"}
POLICIES = ["stale", "strict", "queue1", "queue4"]


def norm(stage):
    return "build" if stage == "vet" else stage


def patch_stats(d):
    rows = []
    for f in sorted(os.listdir(os.path.join(HERE, d))):
        files, add, rem, new = set(), 0, 0, 0
        for line in open(os.path.join(HERE, d, f)):
            if line.startswith("diff --git"):
                files.add(line.split(" b/")[-1].strip())
            elif line.startswith("new file mode"):
                new += 1
            elif line.startswith("+") and not line.startswith("+++"):
                add += 1
            elif line.startswith("-") and not line.startswith("---"):
                rem += 1
        rows.append({"ticket": f[:-6], "files": sorted(files), "new_files": new, "added": add, "removed": rem})
    return rows


def arm(name):
    work = WORKS[name]
    m = json.load(open(os.path.join(work, "matrix.json")))
    sim = json.load(open(os.path.join(work, "simulate.json")))
    cache = json.load(open(os.path.join(work, "ci-cache.json")))
    pairs = m["pairs"]
    for p in pairs:
        p["result"] = norm(p["result"])
    counts = collections.Counter(p["result"] for p in pairs)
    m_r = {(p["a"], p["b"]): p["result"] for p in pairs}
    conflict_files = collections.Counter()
    for p in pairs:
        for f in p.get("files", []):
            conflict_files[f] += 1
    semantic = [p for p in pairs if p["result"] in ("build", "test")]
    sem_pairs = collections.Counter(tuple(sorted((p["a"], p["b"]))) for p in semantic)
    pol = {}
    orders = sim["orders"]
    for k in POLICIES:
        st = [o[k] for o in orders]
        why = collections.Counter(norm(b["why"]) for s in st for b in s["bounced"])
        landed = [len(s["landed"]) for s in st]
        pol[k] = {
            "landed_mean": round(statistics.mean(landed), 2), "landed_min": min(landed), "landed_max": max(landed),
            "ci_runs_mean": round(statistics.mean(s["ci_runs"] for s in st), 1),
            "ci_rounds_mean": round(statistics.mean(s["ci_rounds"] for s in st), 1),
            "bounced_by": dict(why),
            "red_main_commits": sum(s["red_main_commits"] for s in st),
            "orders_main_red": sum(1 for s in st if s.get("main_red_at_end") or s["red_main_commits"]),
            "wasted_runs": sum(s.get("wasted_runs", 0) for s in st),
        }
    st = [o["stale"] for o in orders]
    pol["stale"]["landed_before_first_red_mean"] = round(statistics.mean(
        (s["first_red_at"] - 1) if s["first_red_at"] else len(s["landed"]) for s in st), 2)
    pol["stale"]["red_share_of_main_commits"] = round(
        sum(s["red_main_commits"] for s in st) / sum(len(s["landed"]) for s in st), 3)
    red_causes = collections.Counter(c["first"] for o in orders for c in o["stale"].get("red_causes", []))
    secs = [v["seconds"] for v in cache.values()]
    runs = list(csv.DictReader(open(os.path.join(HERE, RUNS[name])), delimiter="\t"))
    return {
        "solo_green": sum(1 for v in m["solo"].values() if v["ok"]), "tickets": len(m["solo"]),
        "pairs": len(pairs), "pair_results": dict(counts),
        "matrix": {f'{p["a"]}>{p["b"]}': p["result"] for p in pairs},
        "semantic_examples": [{"a": p["a"], "b": p["b"], "stage": p["result"], "first": p["first"]} for p in semantic],
        "semantic_unordered_pairs": len(sem_pairs),
        "order_independent": all(p["result"] == m_r[(p["b"], p["a"])] for p in pairs),
        "conflict_files": dict(conflict_files.most_common()),
        "orders": len(orders), "policies": pol,
        "stale_red_causes": dict(red_causes.most_common()),
        "unique_trees_tested": len(cache),
        "ci_seconds_median": round(statistics.median(secs), 2), "ci_seconds_p90": round(sorted(secs)[int(.9 * len(secs))], 2),
        "agent_runs": {"model_calls": sum(int(r["model_calls"]) for r in runs),
                       "tool_steps": sum(int(r["tool_steps"]) for r in runs),
                       "seconds": sum(int(r["seconds"]) for r in runs),
                       "self_report_green": sum(1 for r in runs if r["agent_self_report_green"] == "yes")},
        "patches": patch_stats(PATCHDIR[name]),
    }


def cmd(*a):
    try:
        return subprocess.run(a, capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


out = {
    "host": {"cpu": cmd("sysctl", "-n", "machdep.cpu.brand_string"), "cores": cmd("sysctl", "-n", "hw.ncpu"),
             "os": platform.platform()},
    "go": cmd("go", "version"), "git": cmd("git", "--version"),
    "seed": 20261123,
    "arms": {a: arm(a) for a in WORKS},
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(out, open(OUT, "w"), indent=1)
for a, v in out["arms"].items():
    print(a, v["pair_results"], {k: (p["landed_mean"], p["ci_runs_mean"], p["red_main_commits"], p["bounced_by"])
                                 for k, p in v["policies"].items()})
