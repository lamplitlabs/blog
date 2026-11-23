#!/usr/bin/env python3
"""Collect the harness results into scripts/data/agent-tests-mutation-go.json.

Usage:
  python3 scripts/agent-tests-mutation/summarise.py <work>

Reads <work>/results/<run>.json and <run>.rep<N>.json (written by
harness.py measure/human) and <work>/agent_runs.tsv (model calls, tool steps
and wall seconds the agent runner reported per run, logged by hand). A seeded
defect counts as caught by a suite only when every repeat caught it; one that
was caught in some repeats and not others is listed as flaky.
"""
import csv
import glob
import json
import os
import re
import statistics
import sys

WORK = os.path.abspath(sys.argv[1])
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "agent-tests-mutation-go.json")
ARMS = ["human", "plain", "coverage", "mutants", "plainmut"]


def arm_of(run):
    return "human" if run == "human" else run.split("-")[0]


def main():
    reps = {}
    for p in sorted(glob.glob(os.path.join(WORK, "results", "*.json"))):
        name = os.path.basename(p)[:-5]
        if name.endswith(".gomut"):
            continue
        run = re.sub(r"\.rep\d+$", "", name)
        reps.setdefault(run, []).append(json.load(open(p)))
    agents = {}
    tsv = os.path.join(WORK, "agent_runs.tsv")
    if os.path.exists(tsv):
        for r in csv.DictReader(open(tsv), delimiter="\t"):
            agents[r["run"]] = {"model_calls": int(r["model_calls"]), "tool_steps": int(r["tool_steps"]),
                                "seconds": int(r["seconds"])}
    order = sorted(reps, key=lambda r: (ARMS.index(arm_of(r)), r))
    suites = []
    defect_ids = [d["id"] for d in reps[order[0]][0]["defects"]]
    meta = {d["id"]: {"cls": d["cls"], "title": d["title"]} for d in reps[order[0]][0]["defects"]}
    for run in order:
        rs = reps[run]
        g = rs[0]["gomut"]
        scores = sorted({float(r["gomut"]["mutation_score_pct"]) for r in rs})
        per_defect = {}
        for i, did in enumerate(defect_ids):
            t = [r["defects"][i]["test_fails"] for r in rs]
            ra = [r["defects"][i]["race_fails"] for r in rs]
            first = next((r["defects"][i]["test_first"] or r["defects"][i]["race_first"]
                          for r in rs if r["defects"][i]["test_first"] or r["defects"][i]["race_first"]), "")
            per_defect[did] = {
                "test": "yes" if all(t) else ("flaky" if any(t) else "no"),
                "race": "yes" if all(ra) else ("flaky" if any(ra) else "no"),
                "timeout": any(r["defects"][i].get("test_timeout") or r["defects"][i].get("race_timeout") for r in rs),
                "first": first,
            }
        seeded = [d for d in defect_ids if meta[d]["cls"] != "benign"]
        benign = [d for d in defect_ids if meta[d]["cls"] == "benign"]
        lived = [{"id": m["id"], "file": m["file"], "line": m["line"], "op": m["op"], "orig": m["orig"],
                  "repl": m["repl"], "snippet": m["snippet"]}
                 for m in g["mutants"] if m["status"] == "LIVED"]
        notcov = [{"id": m["id"], "file": m["file"], "line": m["line"], "op": m["op"]}
                  for m in g["mutants"] if m["status"] == "NOT COVERED"]
        suites.append({
            "run": run, "arm": arm_of(run), "repeats": len(rs),
            "tests": g["tests"], "test_lines": rs[0]["test_lines"],
            "test_files": rs[0]["test_files"], "source_edited_by_agent": rs[0]["source_edited_by_agent"],
            "coverage_pct": float(g["coverage_pct"]),
            "mutation_score_pct": scores[0] if len(scores) == 1 else scores,
            "covered_mutation_score_pct": g["covered_mutation_score_pct"],
            "mutant_counts": g["counts"],
            "gomut_seconds": [r["gomut"]["wall_seconds"] for r in rs],
            "suite_seconds": [r["suite_seconds"] for r in rs],
            "lived": lived, "not_covered": notcov,
            "caught_test": sum(per_defect[d]["test"] == "yes" for d in seeded),
            "caught_test_or_race": sum(per_defect[d]["test"] == "yes" or per_defect[d]["race"] == "yes" for d in seeded),
            "flaky": [d for d in seeded if "flaky" in (per_defect[d]["test"], per_defect[d]["race"])],
            "benign_failed": sum(per_defect[d]["test"] != "no" for d in benign),
            "defects": per_defect,
            "agent": agents.get(run),
        })

    def arm_stats(arm):
        ss = [s for s in suites if s["arm"] == arm]
        ms = [s["mutation_score_pct"][0] if isinstance(s["mutation_score_pct"], list) else s["mutation_score_pct"]
              for s in ss]
        out = {"runs": len(ss), "mutation_score_pct": [min(ms), max(ms)],
               "coverage_pct": sorted({s["coverage_pct"] for s in ss}),
               "caught_test": [s["caught_test"] for s in ss],
               "caught_test_or_race": [s["caught_test_or_race"] for s in ss],
               "tests": [s["tests"] for s in ss], "test_lines": [s["test_lines"] for s in ss]}
        ag = [s["agent"] for s in ss if s["agent"]]
        if ag:
            out["agent_median_seconds"] = statistics.median(a["seconds"] for a in ag)
            out["agent_median_model_calls"] = statistics.median(a["model_calls"] for a in ag)
        return out

    caught_by = {}
    for d in defect_ids:
        caught_by[d] = [s["run"] for s in suites
                        if s["defects"][d]["test"] == "yes" or s["defects"][d]["race"] == "yes"]
    host = {}
    try:
        import platform
        import subprocess
        host = {"go": subprocess.run(["go", "env", "GOVERSION"], capture_output=True, text=True).stdout.strip(),
                "machine": platform.machine(), "system": platform.system(),
                "cpu": subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                      text=True).stdout.strip()}
    except OSError:
        pass
    data = {
        "about": "Agent-written Go unit tests for ../ai-review-gates/svc measured with gomut (mutation score) "
                 "and with the 26 seeded defects + 5 behaviour-preserving changes of ../ai-review-gates/corpus.py. "
                 "Written by scripts/agent-tests-mutation/summarise.py; do not edit by hand.",
        "host": host,
        "mutants_total": suites[0]["mutant_counts"] and sum(suites[0]["mutant_counts"].values()),
        "defects": [{"id": d, **meta[d], "caught_by": caught_by[d]} for d in defect_ids],
        "arms": {a: arm_stats(a) for a in ARMS if any(s["arm"] == a for s in suites)},
        "suites": suites,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(data, open(OUT, "w"), indent=1)
    open(OUT, "a").write("\n")
    print("wrote", os.path.relpath(OUT))
    for s in suites:
        print(f"{s['run']:12} tests {s['tests']:3} cov {s['coverage_pct']:5} mut {s['mutation_score_pct']} "
              f"caught {s['caught_test']:2}/26 (+race {s['caught_test_or_race']:2}) flaky {s['flaky']} "
              f"benign-fail {s['benign_failed']}")


if __name__ == "__main__":
    main()
