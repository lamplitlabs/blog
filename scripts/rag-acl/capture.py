#!/usr/bin/env python3
"""Capture one real request/reply transcript per strategy for the post's terminal screenshot.

Usage (same environment as bench.py, llama-server running):
  python3 scripts/rag-acl/capture.py --work <scratch-dir> --qid <xquad id> [--user contractor]

Rebuilds the same seeded corpus and index as bench.py, runs the question for the user
under prompt-rule and pre-filter, and writes <work>/capture-<qid>.txt: the documents
that reached the prompt (group label, first words), the model's reply verbatim, and
whether the gold answer is readable by the user at all.
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--qid", required=True, action="append")
    ap.add_argument("--user", default="contractor")
    ap.add_argument("--llm", default="127.0.0.1:18651")
    ap.add_argument("--seed", type=int, default=20261125)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    docs, questions = bench.build_corpus(rng)
    doc_group = {d["id"]: d["group"] for d in docs}
    db = bench.index(docs, os.path.join(args.work, "kb-capture.sqlite"))
    groups = bench.USERS[args.user]
    by = {q["qid"]: q for q in questions}
    for qid in args.qid:
        q = by[qid]
        lines = ["$ rag-ask --user %s --groups %s" % (args.user, ",".join(groups)),
                 "question: %s" % q["question"],
                 "gold answer (from XQuAD): %s   gold document group: %s" % (q["answers"][0], doc_group[q["gold"]])]
        for strategy in ("prompt-rule", "pre-filter"):
            ids, ms = bench.retrieve(db, strategy, q["question"], groups, doc_group)
            system, prompt = bench.prompt_for(strategy, ids, docs, groups, q["question"])
            reply, usage = bench.chat(args.llm, system, prompt)
            lines.append("")
            lines.append("--- strategy: %s   retrieval %.1f ms   prompt %s tokens" % (strategy, ms, usage.get("prompt_tokens")))
            for n, d in enumerate(ids, 1):
                g = doc_group[d]
                tag = ("RESTRICTED: %s only" % g) if (strategy == "prompt-rule" and g not in groups) else g
                words = " ".join(docs[d]["text"].split()[:9])
                lines.append("[document %d, %s] %s ..." % (n, tag, words))
            lines.append("model> " + " ".join(reply.split()))
            lines.append("# gold answer in reply: %s" % ("YES" if bench.contains_answer(reply, q["answers"]) else "no"))
        out = os.path.join(args.work, "capture-%s.txt" % qid)
        with open(out, "w") as fh:
            fh.write("\n".join(lines) + "\n")
        print("\n".join(lines))
        print("wrote", out)


if __name__ == "__main__":
    main()
