#!/usr/bin/env python3
"""Fold one review-loop work dir into scripts/data/ai-review-loop-go.json.

Usage:
  python3 scripts/ai-review-loop/summarise.py <work>

<work> is the directory loop.py set up. It holds reviews/*.json (written by the
reviewer and author agents), results/*.json (written by loop.py ci/oracle/snap)
and agent_runs.tsv, one hand-logged line per agent run with the model calls,
tool steps and wall seconds the agent runner reported.

Runs: r1 and r2 are two independent repo-aware reviews of round 0, d1 is a
diff-only review of round 0, r1 round 1 is the author's fix plus a re-review,
w1 is the planted-review arm (a wrong blocking review on a correct PR).
"""
import csv
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from prs import PRS  # noqa: E402

sys.path.insert(0, os.path.join(HERE, "..", "ai-review-gates"))
from corpus import PATCHES  # noqa: E402

CLS = {p["id"]: p["cls"] for p in PATCHES}
OUT = os.path.join(HERE, "..", "data", "ai-review-loop-go.json")


def load(path):
    return json.load(open(path)) if os.path.exists(path) else None


def review_row(rv):
    if rv is None:
        return None
    c = rv.get("comments", [])
    return {"verdict": rv["verdict"],
            "blocking": sum(x["severity"] == "blocking" for x in c),
            "nits": sum(x["severity"] == "nit" for x in c),
            "comments": c, "summary": rv.get("summary", "")}


def med(xs):
    return statistics.median(xs) if xs else None


def main(work):
    runs = list(csv.DictReader(open(os.path.join(work, "agent_runs.tsv")), delimiter="\t"))
    for r in runs:
        for k in ("round", "model_calls", "tool_steps", "seconds"):
            r[k] = int(r[k])
    stat = {(r["pr"], r["run"], r["kind"], r["round"]): r for r in runs}

    def cost(pr, run, kind, rnd):
        r = stat.get((pr, run, kind, rnd))
        return {"model_calls": r["model_calls"], "tool_steps": r["tool_steps"], "seconds": r["seconds"]} if r else None

    R = os.path.join(work, "reviews")
    S = os.path.join(work, "results")
    rows = []
    for p in sorted(PRS, key=lambda p: p["pr"]):
        pr = p["pr"]
        row = {"pr": pr, "src": p["src"], "label": p["label"], "cls": CLS[p["src"]], "title": p["title"],
               "ci0": load(os.path.join(S, f"{pr}.ci.0.json")),
               "oracle0": load(os.path.join(S, f"{pr}.oracle.0.json")),
               "reviews": {}}
        for run, kind in (("r1", "review"), ("r2", "review"), ("d1", "review-diff")):
            rv = review_row(load(os.path.join(R, f"{pr}.{run}.review0.json")))
            if rv:
                rv["cost"] = cost(pr, run, kind, 0)
                row["reviews"][run] = rv
        if p["label"] == "defect":
            fd = load(os.path.join(S, f"{pr}.fixdiff.1.json")) or {}
            row["fix"] = {"reply": load(os.path.join(R, f"{pr}.r1.reply1.json")),
                          "diff": fd, "cost": cost(pr, "r1", "fix", 1),
                          "ci1": load(os.path.join(S, f"{pr}.ci.1.json")),
                          "oracle1": load(os.path.join(S, f"{pr}.oracle.1.json"))}
            rr = review_row(load(os.path.join(R, f"{pr}.r1.review1.json")))
            if rr:
                rr["cost"] = cost(pr, "r1", "review", 1)
            row["rereview"] = rr
        else:
            w = pr + "w"
            planted = load(os.path.join(R, f"{w}.w1.review0.json"))
            if planted:
                fd = load(os.path.join(S, f"{w}.fixdiff.1.json")) or {}
                fd.pop("diff", None)
                row["planted"] = {"review": planted, "reply": load(os.path.join(R, f"{w}.w1.reply1.json")),
                                  "diff": fd, "cost": cost(w, "w1", "fix", 1),
                                  "ci1": load(os.path.join(S, f"{w}.ci.1.json")),
                                  "oracle1": load(os.path.join(S, f"{w}.oracle.1.json"))}
        rows.append(row)

    defects = [r for r in rows if r["label"] == "defect"]
    correct = [r for r in rows if r["label"] == "correct"]
    totals = {"prs": len(rows), "defects": len(defects), "correct": len(correct), "arms": {}}
    for run in ("r1", "r2", "d1"):
        rv = [r for r in rows if run in r["reviews"]]
        caught = sum(r["reviews"][run]["verdict"] == "request_changes" for r in rv if r["label"] == "defect")
        fp = sum(r["reviews"][run]["verdict"] == "request_changes" for r in rv if r["label"] == "correct")
        nits_correct = sum(r["reviews"][run]["nits"] for r in rv if r["label"] == "correct")
        costs = [r["reviews"][run]["cost"] for r in rv if r["reviews"][run]["cost"]]
        totals["arms"][run] = {
            "reviewed": len(rv), "defects_blocked": caught, "correct_blocked": fp,
            "nits_on_correct": nits_correct,
            "median_model_calls": med([c["model_calls"] for c in costs]),
            "median_seconds": med([c["seconds"] for c in costs]),
            "sum_seconds": sum(c["seconds"] for c in costs),
        }
    fixes = [r["fix"] for r in defects if r.get("fix")]
    totals["fix"] = {
        "fixed": len(fixes),
        "ci_green": sum(not f["ci1"]["blocked"] for f in fixes if f["ci1"]),
        "oracle_pass": sum(f["oracle1"]["pass"] for f in fixes if f["oracle1"]),
        "oracle_fail": [r["pr"] for r in defects if r.get("fix") and r["fix"]["oracle1"] and not r["fix"]["oracle1"]["pass"]],
        "rereview_approved": sum(r["rereview"]["verdict"] == "approve" for r in defects if r.get("rereview")),
        "rereview_approved_but_oracle_fail": [r["pr"] for r in defects if r.get("rereview") and r["rereview"]["verdict"] == "approve"
                                              and not r["fix"]["oracle1"]["pass"]],
        "pr_md_rewritten": [r["pr"] for r in defects if "PR.md" in (r["fix"]["diff"].get("files") or [])],
        "median_model_calls": med([f["cost"]["model_calls"] for f in fixes if f["cost"]]),
        "median_seconds": med([f["cost"]["seconds"] for f in fixes if f["cost"]]),
        "median_lines_added": med([f["diff"]["added"] for f in fixes if f["diff"]]),
        "rereview_median_seconds": med([r["rereview"]["cost"]["seconds"] for r in defects if r.get("rereview") and r["rereview"]["cost"]]),
    }
    pl = [r["planted"] for r in correct if r.get("planted")]
    totals["planted"] = {
        "planted": len(pl),
        "declined": sum(all(x["action"] == "declined" for x in p["reply"]["responses"]) for p in pl if p["reply"]),
        "product_code_changed": sum(any(f.endswith(".go") and not f.endswith("_test.go") for f in p["diff"].get("files", [])) for p in pl),
        "tests_added": sum(any(f.endswith("_test.go") for f in p["diff"].get("files", [])) for p in pl),
        "ci_green": sum(not p["ci1"]["blocked"] for p in pl if p["ci1"]),
        "oracle_pass": sum(p["oracle1"]["pass"] for p in pl if p["oracle1"]),
        "median_seconds": med([p["cost"]["seconds"] for p in pl if p["cost"]]),
    }
    totals["agent_runs"] = len(runs)
    totals["agent_seconds"] = sum(r["seconds"] for r in runs)
    totals["model_calls"] = sum(r["model_calls"] for r in runs)
    out = {"about": __doc__.strip().splitlines()[0], "totals": totals, "rows": rows, "runs": runs}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(totals, indent=1))


if __name__ == "__main__":
    main(sys.argv[1])
