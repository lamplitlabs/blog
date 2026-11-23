#!/usr/bin/env python3
"""Write the benign corpus the benches time the rules on: real question text, one line each.

Usage (needs pyarrow; see measure.sh for the interpreter it uses):
  python3 build_benign.py <out.txt>

Reads the GSM8K test split (questions and worked answers) and TruthfulQA questions from the local Hugging Face
cache - nothing is downloaded - and writes every question as one line with
newlines folded to spaces, plus a seeded shuffle so line order is not dataset order.
Nothing in it was written to trigger a rule.
"""
import glob
import os
import random
import sys

import pyarrow.parquet as pq

HUB = os.path.expanduser("~/.cache/huggingface/hub")
SOURCES = [
    ("datasets--openai--gsm8k", "main/test-*.parquet", "question"),
    ("datasets--openai--gsm8k", "main/test-*.parquet", "answer"),
    ("datasets--truthfulqa--truthful_qa", "multiple_choice/validation-*.parquet", "question"),
]

lines = []
for repo, pattern, column in SOURCES:
    files = sorted(glob.glob(os.path.join(HUB, repo, "snapshots", "*", pattern)))
    if not files:
        sys.exit(f"missing {repo}/{pattern} in {HUB}")
    for f in files:
        for v in pq.read_table(f, columns=[column]).column(column).to_pylist():
            v = " ".join(str(v).split())
            if v:
                lines.append(v)
random.Random(20261122).shuffle(lines)
with open(sys.argv[1], "w", encoding="utf-8") as out:
    out.write("\n".join(lines) + "\n")
print(f"{len(lines)} lines, {sum(len(x.encode()) + 1 for x in lines)} bytes -> {sys.argv[1]}", file=sys.stderr)
