#!/usr/bin/env python3
"""Summarise run_experiment.py output into scripts/data/enterprise-ai-token-budgets.json.

    python3 scripts/enterprise-ai-token-budgets/summarise.py --raw .tmp/budgets-raw.jsonl --audit-dir .tmp/audit \
        --sweep .tmp/budget-sweep.jsonl

Medians over reps per (mode, concurrency). The spend curves (tokens billed over time) come from
the rep-0 audit logs at the highest concurrency.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "enterprise-ai-token-budgets.json")


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.median(xs), 2) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True)
    ap.add_argument("--audit-dir", required=True)
    ap.add_argument("--sweep", default=None, help="budget_sweep.py output (optional)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.raw)]
    modes = list(dict.fromkeys(r["mode"] for r in rows))
    concs = sorted({r["conc"] for r in rows})
    first = rows[0]["ledger"]["teams"]
    out = {
        "setup": {
            "model": "SmolLM2-135M-Instruct (F32 GGUF) on llama-server b11669, Metal, M2 Pro",
            "server": "llama-server -np 20 -c 81920",
            "batch_requests": 60, "batch_prompt_tokens_approx": 370, "batch_max_tokens": 1024,
            "support_requests": 24, "support_max_tokens_asked": 4096,
            "budgets": {t: first[t]["budget"] for t in first},
            "caps": {t: first[t]["cap"] for t in first},
            "reps": len({r["rep"] for r in rows}), "concurrency": concs, "modes": modes,
            "runs": len(rows),
        },
        "results": [],
        "spend_curves": {},
    }
    for conc in concs:
        for mode in modes:
            rs = [r for r in rows if r["mode"] == mode and r["conc"] == conc]
            b = [r["ledger"]["teams"]["batch-summariser"] for r in rs]
            s = [r["ledger"]["teams"]["support-bot"] for r in rs]
            comp = [c for r in rs for c in r["batch_completion_tokens"]]
            out["results"].append({
                "mode": mode, "conc": conc, "n": len(rs),
                "batch_spent": med([x["spent"] for x in b]),
                "batch_spent_max": max(x["spent"] for x in b),
                "batch_overshoot_pct": med([x["overshoot_pct"] for x in b]),
                "batch_overshoot_pct_max": max(x["overshoot_pct"] for x in b),
                "batch_served": med([x["served"] for x in b]),
                "batch_429": med([x["rejected_budget"] for x in b]),
                "batch_peak_in_flight": med([x["peak_in_flight"] for x in b]),
                "batch_exhausted_at_s": med([x["exhausted_at"] for x in b]),
                "batch_completion_mean": round(statistics.mean(comp), 1) if comp else None,
                "batch_completion_hit_cap_pct": round(100 * sum(1 for c in comp if c >= 1024) / len(comp), 1) if comp else None,
                "batch_utilisation_pct": med([100 * x["spent"] / x["budget"] for x in b]),
                "support_spent": med([x["spent"] for x in s]),
                "support_served": med([x["served"] for x in s]),
                "support_clamped": med([x["clamped"] for x in s]),
                "support_ms_p50": med([r["support_ms_p50"] for r in rs]),
                "shadow_403": med([sum(1 for st in v if st == 403) for r in rs for v in [sum(r["shadow_statuses"].values(), [])]]),
                "shadow_total": med([len(sum(r["shadow_statuses"].values(), [])) for r in rs]),
                "admission_ms_p50": med([r["admission_ms_p50"] for r in rs]),
                "admission_ms_p95": med([r["admission_ms_p95"] for r in rs]),
                "budget_429_ms_p50": med([r["budget_429_ms_p50"] for r in rs]),
                "wall_s": med([r["wall_s"] for r in rs]),
            })
    hi = max(concs)
    for mode in modes:
        path = os.path.join(a.audit_dir, f"audit-{mode}-c{hi}-r0.jsonl")
        if not os.path.exists(path):
            continue
        ev = [json.loads(l) for l in open(path)]
        ev = [e for e in ev if e["team"] == "batch-summariser" and e["decision"] == "admit"]
        # "ts" is stamped right after the admission decision; tokens are billed when the reply arrives
        for e in ev:
            e["done"] = e["ts"] + e["upstream_ms"] / 1000
        ev.sort(key=lambda e: e["done"])
        t0 = min(json.loads(l)["ts"] for l in open(path))
        cum, pts = 0, [[0.0, 0]]
        for e in ev:
            cum += e["prompt_tokens"] + e["completion_tokens"]
            pts.append([round(e["done"] - t0, 2), cum])
        out["spend_curves"][mode] = pts
    if a.sweep:
        out["budget_sweep"] = [json.loads(l) for l in open(a.sweep)]
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", os.path.relpath(OUT))
    for r in out["results"]:
        print(f"{r['mode']:9s} c={r['conc']:2d} spent={r['batch_spent']:>8} over={r['batch_overshoot_pct']:>6}% "
              f"(max {r['batch_overshoot_pct_max']}%) served={r['batch_served']} 429={r['batch_429']} "
              f"util={r['batch_utilisation_pct']}% adm_p50={r['admission_ms_p50']}ms support_served={r['support_served']}")


if __name__ == "__main__":
    main()
