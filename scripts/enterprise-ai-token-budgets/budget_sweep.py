#!/usr/bin/env python3
"""Sweep the batch team's budget to show how far "post" and "reserve" can land from it.

    python3 scripts/enterprise-ai-token-budgets/budget_sweep.py --out .tmp/budget-sweep.jsonl

Same workload as run_experiment.py at 16 workers (rep 0), one run per (mode, budget).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gateway  # noqa: E402
import run_experiment as R  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default="127.0.0.1:18431")
    ap.add_argument("--port", type=int, default=18700)
    ap.add_argument("--budgets", default="20000,26000,32000,36000,44000,50000")
    ap.add_argument("--modes", default="post,reserve")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    n = 0
    for budget in [int(b) for b in a.budgets.split(",")]:
        gateway.DEFAULT_TEAMS["batch-summariser"]["budget"] = budget
        for mode in a.modes.split(","):
            row = R.run_once(a.upstream, a.port + n, mode, 16, 0, None)
            n += 1
            b = row["ledger"]["teams"]["batch-summariser"]
            out = {"mode": mode, "budget": budget, "spent": b["spent"], "overshoot_pct": b["overshoot_pct"],
                   "served": b["served"], "rejected": b["rejected_budget"]}
            print(json.dumps(out), flush=True)
            with open(a.out, "a") as f:
                f.write(json.dumps(out) + "\n")


if __name__ == "__main__":
    main()
