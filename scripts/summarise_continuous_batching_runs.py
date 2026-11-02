#!/usr/bin/env python3
"""Summarise raw llama-batched-bench / llama-server load runs into one JSON file.

Usage: python3 scripts/summarise_continuous_batching_runs.py RAW_DIR OUT_JSON

RAW_DIR holds bench_r{1,2,3}.jsonl (llama-batched-bench --output-format jsonl) and
load_<config>_r{1,2,3}.jsonl (written by scripts/llama_server_loadgen.py).
The post's charts are drawn from OUT_JSON by scripts/gen_continuous_batching_post_images.py.
"""
import glob, json, os, sys

RAW, OUT = sys.argv[1], sys.argv[2]

CONFIGS = {
    "serial": "-np 1",
    "static8": "-np 8 -nocb",
    "cont8": "-np 8",
    "cont8b64": "-np 8 -b 64 -ub 64",
    "cont16": "-np 16",
    "cont16kvu": "-np 16 -kvu",
}


GAP_QUANTILES = [50, 75, 90, 95, 97.5, 99, 99.5, 99.9, 100]


def pct(xs, p):
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def bench_runs():
    runs = []
    for path in sorted(glob.glob(os.path.join(RAW, "bench_r*.jsonl"))):
        rows = []
        for line in open(path):
            line = line.strip()
            if line.startswith("{"):
                d = json.loads(line)
                rows.append({k: d[k] for k in ("pp", "tg", "pl", "n_kv", "t_pp", "speed_pp", "t_tg", "speed_tg")})
        runs.append(rows)
    return runs


def load_summary(rs):
    ttft = [r["first"] - r["arrive"] for r in rs]
    e2e = [r["done"] - r["arrive"] for r in rs]
    short = [r["done"] - r["arrive"] for r in rs if r["n_predict"] <= 64]
    tpot = [(r["done"] - r["first"]) / (r["tokens"] - 1) for r in rs if r["tokens"] > 1]
    gaps = [g for r in rs for g in r["gaps"]]
    t0 = min(r["arrive"] for r in rs)
    t1 = max(r["done"] for r in rs)
    toks = sum(r["tokens"] for r in rs)
    return {
        "ttft_p50_s": pct(ttft, 50), "ttft_p95_s": pct(ttft, 95),
        "e2e_p50_s": pct(e2e, 50), "e2e_p95_s": pct(e2e, 95),
        "short_e2e_p50_s": pct(short, 50),
        "tpot_p50_ms": pct(tpot, 50) * 1000, "tpot_p95_ms": pct(tpot, 95) * 1000,
        "gap_p50_ms": pct(gaps, 50) * 1000, "gap_p99_ms": pct(gaps, 99) * 1000, "gap_max_ms": max(gaps) * 1000,
        "gap_quantiles_ms": {str(q): round(pct(gaps, q) * 1000, 2) for q in GAP_QUANTILES},
        "throughput_tok_s": toks / (t1 - t0), "makespan_s": t1 - t0, "tokens": toks,
        "all_complete": all(r["tokens"] == r["n_predict"] for r in rs),
    }


def main():
    out = {"bench": bench_runs(), "load": {}}
    for name, flags in CONFIGS.items():
        paths = sorted(glob.glob(os.path.join(RAW, f"load_{name}_r*.jsonl")))
        if not paths:
            continue
        runs, timeline = [], None
        for i, path in enumerate(paths):
            rs = [json.loads(l) for l in open(path)]
            runs.append(load_summary(rs))
            if i == 0:
                timeline = [[round(r["arrive"], 3), round(r["first"], 3), round(r["done"], 3), r["n_predict"]] for r in rs]
        out["load"][name] = {"flags": flags, "runs": runs, "timeline_run1": timeline}
    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
