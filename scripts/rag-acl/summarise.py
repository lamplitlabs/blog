#!/usr/bin/env python3
"""Summarise <work>/raw.json from scripts/rag-acl/bench.py into scripts/data/rag-acl-enforcement.json.

Usage:
  python3 scripts/rag-acl/summarise.py <work-dir>

Keeps the per-strategy totals the post quotes, every LLM reply for the leak sets
(so each "leak" can be checked by hand), and the cache leak examples.
"""
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(ROOT, "scripts", "data", "rag-acl-enforcement.json")


def pct(n, d):
    return round(100.0 * n / d, 1) if d else None


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100.0 * (len(xs) - 1))))]


def main():
    work = sys.argv[1]
    raw = json.load(open(os.path.join(work, "raw.json")))
    out = {k: raw[k] for k in ("seed", "k", "n_docs", "n_xquad_docs", "n_questions", "group_docs",
                               "xquad_group_docs", "users", "sqlite", "python", "llm_sets")}
    out["index_s"] = round(raw["index_s"], 2)
    out["machine"] = "Apple M2 Pro, 16 GB, macOS; shared host"
    out["model"] = "SmolLM2-135M-Instruct, F32 GGUF, llama-server (llama.cpp build 12359), Metal, temperature 0"

    # retrieval
    retr = {}
    for s, rows in raw["retrieval"].items():
        users = {}
        for u in raw["users"]:
            ur = [r for r in rows if r["user"] == u]
            perm = [r for r in ur if r["gold_permitted"]]
            users[u] = {
                "queries": len(ur),
                "permitted_gold": len(perm),
                "recall_at_k": pct(sum(r["gold_in_topk"] for r in perm), len(perm)),
                "queries_with_restricted_in_prompt": sum(r["restricted_in_prompt"] > 0 for r in ur),
                "restricted_docs_in_prompt": sum(r["restricted_in_prompt"] for r in ur),
                "empty_context": sum(r["n_docs"] == 0 for r in ur),
                "short_context": sum(0 < r["n_docs"] < raw["k"] for r in ur),
            }
        ms = [r["ms"] for r in rows]
        perm_all = [r for r in rows if r["gold_permitted"]]
        retr[s] = {
            "per_user": users,
            "queries": len(rows),
            "recall_at_k": pct(sum(r["gold_in_topk"] for r in perm_all), len(perm_all)),
            "queries_with_restricted_in_prompt": sum(r["restricted_in_prompt"] > 0 for r in rows),
            "restricted_docs_in_prompt": sum(r["restricted_in_prompt"] for r in rows),
            "short_context": sum(r["n_docs"] < raw["k"] for r in rows),
            "ms_p50": round(statistics.median(ms), 3),
            "ms_p95": round(q(ms, 95), 3),
            "ms_p99": round(q(ms, 99), 3),
        }
        # contractor recall separately: the user with the smallest permitted share
    out["retrieval"] = retr

    # LLM
    llm = raw["llm"]
    un = {}
    for s in ("no-context", "none", "prompt-rule", "post-filter@100", "pre-filter"):
        rows = [r for r in llm if r["kind"] == "unauth" and r["strategy"] == s]
        un[s] = {"pairs": len(rows), "answer_in_reply": sum(r["has_answer"] for r in rows),
                 "answer_pct": pct(sum(r["has_answer"] for r in rows), len(rows)),
                 "refused": sum(r["refused"] for r in rows),
                 "restricted_in_prompt": sum(r["restricted_in_prompt"] > 0 for r in rows),
                 "ms_p50": round(statistics.median([r["ms"] for r in rows]), 1) if rows else None,
                 "prompt_tokens_p50": statistics.median([r["prompt_tokens"] or 0 for r in rows]) if rows else None}
    base = {r["qid"]: r["has_answer"] for r in llm if r["kind"] == "unauth" and r["strategy"] == "no-context"}
    for s in un:
        rows = [r for r in llm if r["kind"] == "unauth" and r["strategy"] == s]
        un[s]["answer_not_in_baseline"] = sum(r["has_answer"] and not base.get(r["qid"]) for r in rows)
    out["llm_unauthorized"] = un
    au = {}
    for s in ("none", "prompt-rule", "pre-filter"):
        rows = [r for r in llm if r["kind"] == "auth" and r["strategy"] == s]
        au[s] = {"pairs": len(rows), "correct": sum(r["has_answer"] for r in rows),
                 "correct_pct": pct(sum(r["has_answer"] for r in rows), len(rows)),
                 "refused": sum(r["refused"] for r in rows),
                 "refused_pct": pct(sum(r["refused"] for r in rows), len(rows))}
    out["llm_authorized_mixed"] = au
    out["llm_wall_s"] = round(raw["llm_wall_s"], 1)
    # Paired view: for the same unauthorized question, how often does the prompt rule
    # still hand over an answer that the model gave with no rule at all?
    by = {}
    for r in llm:
        if r["kind"] == "unauth":
            by.setdefault(r["qid"], {})[r["strategy"]] = r
    leaked_none = [q for q, d in by.items() if d["none"]["has_answer"] and not d["no-context"]["has_answer"]]
    out["prompt_rule_paired"] = {
        "leaked_without_rule": len(leaked_none),
        "still_leaked_with_rule": sum(by[q]["prompt-rule"]["has_answer"] for q in leaked_none),
    }
    out["llm_replies"] = [{k: r[k] for k in ("kind", "user", "strategy", "qid", "reply", "has_answer", "refused",
                                             "restricted_in_prompt")} for r in llm]

    # cache
    cache = {}
    for keying in ("question", "question+groups"):
        runs = [c for c in raw["cache"] if c["keying"] == keying]
        fields = ("rep", "queries", "hits", "misses", "cross_scope", "restricted_built", "leaks",
                  "distinct_leaked_questions")
        cache[keying] = {"runs": [{k: c[k] for k in fields} for c in runs], "queries": runs[0]["queries"]}
        for k in ("hits", "cross_scope", "restricted_built", "leaks"):
            cache[keying][k + "_median"] = statistics.median(c[k] for c in runs)
            cache[keying][k + "_total"] = sum(c[k] for c in runs)
    cache["question"]["leak_examples"] = [e for c in raw["cache"] if c["keying"] == "question"
                                          for e in c["leak_examples"]]
    out["cache"] = cache

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote", os.path.relpath(OUT, ROOT), os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
