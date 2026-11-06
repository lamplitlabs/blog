#!/usr/bin/env python3
"""Fold the raw gate results, the agent run log and the hand-coded report review
into scripts/data/spec-to-pr-agents.json (the only input of gen_images.py).

Usage:
  python3 scripts/spec-to-pr/summarise.py --raw .tmp/gates-raw.json
"""
import argparse
import csv
import json
import os
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "data", "spec-to-pr-agents.json")
GATES = ["own_tests", "scope", "diff_coverage", "mutation", "acceptance"]


def words(path):
    with open(path) as f:
        return len(f.read().split())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    a = ap.parse_args()
    raw = json.load(open(a.raw))
    runs = raw["runs"]

    agent = {}
    with open(os.path.join(HERE, "agent_runs.tsv")) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            agent[row["ws"]] = row
    coded = []
    with open(os.path.join(HERE, "assumptions_coded.tsv")) as f:
        rows = [l for l in f if not l.startswith("#")]
        coded = list(csv.DictReader(rows, delimiter="\t"))

    for r in runs:
        a_ = agent[r["run"]]
        r["agent"] = {"model_calls": int(a_["model_calls"]), "tool_steps": int(a_["tool_steps"]),
                      "seconds": int(a_["seconds"]), "self_reported_green": a_["agent_self_report_tests_pass"] == "yes"}
        r["blocked_by"] = [g for g in GATES if not r["gates"][g]["pass"]]

    def summary(sel):
        n = len(sel)
        out = {"runs": n}
        for g in GATES:
            out[f"{g}_pass"] = sum(1 for r in sel if r["gates"][g]["pass"])
        out["acceptance_tests_passed"] = sum(r["gates"]["acceptance"]["passed"] for r in sel)
        out["acceptance_tests_total"] = sum(r["gates"]["acceptance"]["total"] for r in sel)
        out["mutation_score_median"] = statistics.median(r["gates"]["mutation"]["score"] for r in sel)
        out["diff_coverage_median"] = statistics.median(r["gates"]["diff_coverage"]["pct"] for r in sel)
        out["own_tests_added_median"] = statistics.median(r["gates"]["own_tests"]["tests"] - 8 for r in sel)
        out["diff_lines_median"] = statistics.median(r["diff_lines_added"] for r in sel)
        out["agent_seconds_median"] = statistics.median(r["agent"]["seconds"] for r in sel)
        out["agent_calls_median"] = statistics.median(r["agent"]["model_calls"] for r in sel)
        out["wrong_prs"] = sum(1 for r in sel if not r["gates"]["acceptance"]["pass"])
        out["wrong_prs_blocked_before_acceptance"] = sum(
            1 for r in sel if not r["gates"]["acceptance"]["pass"]
            and any(not r["gates"][g]["pass"] for g in GATES[:4]))
        out["correct_prs_blocked_before_acceptance"] = sum(
            1 for r in sel if r["gates"]["acceptance"]["pass"]
            and any(not r["gates"][g]["pass"] for g in GATES[:4]))
        return out

    tickets = sorted({r["ticket_name"] for r in runs})
    spec_words = {t: {v: words(os.path.join(HERE, "specs", f"{t}.{v}.md")) for v in ("thin", "full")} for t in tickets}
    per_ticket = {}
    for t in tickets:
        per_ticket[t] = {v: summary([r for r in runs if r["ticket_name"] == t and r["variant"] == v]) for v in ("thin", "full")}
        per_ticket[t]["spec_words"] = spec_words[t]

    gate_seconds = {g: round(statistics.median(r["timings_s"][g] for r in runs), 3) for g in GATES}
    out = {
        "setup": {
            "python": raw["python"], "host": "Apple M2 Pro, macOS",
            "tickets": len(tickets), "variants": ["thin", "full"], "reps": 2, "runs": len(runs),
            "coverage_min": raw["coverage_min"], "mutation_min": raw["mutation_min"],
            "base_tests": 8,
        },
        "totals": {"all": summary(runs), "thin": summary([r for r in runs if r["variant"] == "thin"]),
                   "full": summary([r for r in runs if r["variant"] == "full"])},
        "per_ticket": per_ticket,
        "gate_seconds_median": gate_seconds,
        "report_review": {
            "failed_tests": len(coded),
            "named_in_report": sum(1 for c in coded if c["named"] == "yes"),
            "rows": coded,
        },
        "runs": runs,
    }
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out["totals"], indent=1))
    print("per-gate median seconds", gate_seconds)
    print("report review", out["report_review"]["named_in_report"], "/", out["report_review"]["failed_tests"])
    print({t: per_ticket[t]["spec_words"] for t in tickets})


if __name__ == "__main__":
    main()
