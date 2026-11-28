#!/usr/bin/env python3
"""Summarise <work>/raw.json from bench.py into scripts/data/prompt-cache-timing-leaks.json.

Usage:
  python3 scripts/prompt-cache-timing/summarise.py <work-dir>

For the membership test it reports hit/miss medians and the accuracy of the
simplest attacker: probe the candidate and one fresh control of the same length,
call it "sent" when the candidate is faster (pairwise accuracy, 50% = no signal),
plus the accuracy of a fixed threshold picked on the first half of the trials and
scored on the second half.
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "scripts", "data", "prompt-cache-timing-leaks.json")


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))]


def member_stats(rows):
    trials = sorted({r["trial"] for r in rows})
    by = {(r["trial"], r["kind"]): r for r in rows}
    hits = [by[(t, "hit")]["ms"] for t in trials]
    miss = [by[(t, "miss")]["ms"] for t in trials]
    pair = sum(1 for t in trials if by[(t, "hit")]["ms"] < by[(t, "miss")]["ms"])
    half = len(trials) // 2
    train = [by[(t, k)]["ms"] for t in trials[:half] for k in ("hit", "miss")]
    best, best_acc = None, -1
    for th in sorted(train):
        acc = sum(1 for t in trials[:half] for k in ("hit", "miss")
                  if (by[(t, k)]["ms"] <= th) == (k == "hit"))
        if acc > best_acc:
            best, best_acc = th, acc
    test = [(by[(t, k)]["ms"] <= best) == (k == "hit") for t in trials[half:] for k in ("hit", "miss")]
    ct_hit = [by[(t, "hit")]["cached_tokens"] for t in trials]
    return {"n": len(trials),
            "prompt_tokens_median": statistics.median(by[(t, "hit")]["prompt_tokens"] for t in trials),
            "hit_ms_p50": round(statistics.median(hits), 1), "hit_ms_p90": round(q(hits, 90), 1),
            "miss_ms_p50": round(statistics.median(miss), 1), "miss_ms_p90": round(q(miss, 90), 1),
            "pairwise_acc_pct": round(100.0 * pair / len(trials), 1),
            "threshold_ms": round(best, 1),
            "threshold_test_acc_pct": round(100.0 * sum(test) / len(test), 1),
            "hit_cached_tokens_median": statistics.median(ct_hit) if all(c is not None for c in ct_hit) else None,
            "hits_ms": hits, "misses_ms": miss}


def main():
    work = sys.argv[1]
    raw = json.load(open(os.path.join(work, "raw.json")))
    out = {k: raw[k] for k in ("seed", "trials", "python", "template", "elapsed_s")}
    out["machine"] = "Apple M2 Pro, 16 GB, macOS; shared host (load varies)"
    out["model"] = ("SmolLM2-135M-Instruct, F32 GGUF, llama-server (llama.cpp build 12359), Metal, "
                    "-np 4 -c 32768, max_tokens 1, temperature 0; hardened server adds --cache-ram 0 -sps 0")

    ex = []
    for e in raw["extract"]:
        ex.append({"code": e["code"], "org": e["org"],
                   "field_guess": e["field_guess"], "field_probes": e["field_probes"],
                   "field_exact": e["field_guess"] == e["code"],
                   "time_guess": e["time_guess"], "time_probes": e["time_probes"],
                   "time_digits_right": sum(1 for a, b in zip(e["time_guess"], e["code"]) if a == b),
                   "field_log_first_digit": [r for r in e["field_log"] if r["pos"] == 0],
                   "time_log": e["time_log"]})
    out["extract"] = ex
    out["extract_summary"] = {
        "secrets": len(ex),
        "field_exact": sum(1 for e in ex if e["field_exact"]),
        "field_probes_median": statistics.median(e["field_probes"] for e in ex) if ex else None,
        "time_exact": sum(1 for e in ex if e["time_guess"] == e["code"]),
        "time_digits_right": sum(e["time_digits_right"] for e in ex),
        "time_digits_total": sum(len(e["code"]) for e in ex),
        "time_probes_each": ex[0]["time_probes"] if ex else None,
    }
    out["member"] = {n: member_stats(rows) for n, rows in raw["member"].items()}
    out["mitigate"] = {}
    for p, m in raw["mitigate"].items():
        s = member_stats(m["member"])
        s["field_guess"] = m["field_guess"]
        s["code"] = m["code"]
        out["mitigate"][p] = s
    out["hardened"] = {k: member_stats(rows) for k, rows in raw.get("hardened", {}).items()}
    out["victim_cost"] = {p: {"p50_ms": round(statistics.median(v), 1), "p90_ms": round(q(v, 90), 1),
                              "calls": len(v)} for p, v in raw["victim_cost"].items()}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("wrote", OUT)
    print(json.dumps(out["extract_summary"]))
    for n, s in out["member"].items():
        print("member", n, {k: s[k] for k in ("prompt_tokens_median", "hit_ms_p50", "miss_ms_p50",
                                             "pairwise_acc_pct", "threshold_test_acc_pct")})
    for p, s in out["mitigate"].items():
        print("mitigate", p, {k: s[k] for k in ("hit_ms_p50", "miss_ms_p50", "pairwise_acc_pct",
                                               "threshold_test_acc_pct", "field_guess")})
    for k, s in out["hardened"].items():
        print("hardened", k, {x: s[x] for x in ("hit_ms_p50", "miss_ms_p50", "pairwise_acc_pct",
                                               "threshold_test_acc_pct")})
    print("victim_cost", out["victim_cost"])


if __name__ == "__main__":
    main()
