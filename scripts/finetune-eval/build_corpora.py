#!/usr/bin/env python3
"""Build the text files the fine-tuning evaluation post trains and measures on.

Domain data: this blog's own posts (front matter stripped). Posts are split by a hash of their
path, so a held-out post never shares a paragraph with a training post (post-level split, not a
random chunk split). General data: English Wikipedia paragraphs from XQuAD (deduplicated), used to
see what the fine-tune forgets. Benchmarks: HellaSwag and Winogrande validation files in the
layouts llama-perplexity expects.

    python3 scripts/finetune-eval/build_corpora.py <out_dir> [--hf-cache ~/.cache/huggingface/hub]

The parquet benchmarks need pyarrow; run with any Python that has it (the post used uv's 3.13).
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import random
import re
from pathlib import Path

HOLDOUT_PERCENT = 20


def post_body(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", text, re.S)
    body = text[m.end():] if m else text
    body = re.sub(r"\{%.*?%\}", "", body)  # liquid tags
    return body.strip() + "\n"


def bucket(path: str) -> int:
    return int(hashlib.sha256(path.encode()).hexdigest(), 16) % 100


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--hf-cache", default=str(Path.home() / ".cache/huggingface/hub"))
    ap.add_argument("--posts-before", default="2026-11-04", help="ignore posts dated on/after this")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    posts = sorted(p for p in glob.glob("_posts/**/*.md", recursive=True)
                   if re.search(r"/\d{4}-\d\d-\d\d-", p) and Path(p).name[:10] < a.posts_before)
    train = [p for p in posts if bucket(p) >= HOLDOUT_PERCENT]
    held = [p for p in posts if bucket(p) < HOLDOUT_PERCENT]
    rng = random.Random(7)
    rng.shuffle(train)  # mix categories so the trainer's tail val split is not one topic
    (out / "blog_train.txt").write_text("\n".join(post_body(p) for p in train), encoding="utf-8")
    (out / "blog_heldout.txt").write_text("\n".join(post_body(p) for p in sorted(held)), encoding="utf-8")

    hub = Path(a.hf_cache)
    import pyarrow.parquet as pq  # noqa: E402

    xq = next(hub.glob("datasets--google--xquad/snapshots/*/xquad.en/validation-*.parquet"))
    seen, paras = set(), []
    for c in pq.read_table(xq).column("context").to_pylist():
        if c not in seen:
            seen.add(c)
            paras.append(c.strip())
    (out / "general_wiki.txt").write_text("\n\n".join(paras) + "\n", encoding="utf-8")

    hs = next(hub.glob("datasets--Rowan--hellaswag/snapshots/*/data/validation-*.parquet"))
    lines = []
    for r in pq.read_table(hs).to_pylist():
        ctx = r["ctx"].replace("\n", " ")
        lines += [ctx, str(int(r["label"]))] + [e.replace("\n", " ") for e in r["endings"]]
    (out / "hellaswag_val.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    wg = next(hub.glob("datasets--allenai--winogrande/snapshots/*/winogrande_xl/validation-*.parquet"))
    with (out / "winogrande_val.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["index", "sentence", "option1", "option2", "answer"])
        for i, r in enumerate(pq.read_table(wg).to_pylist()):
            w.writerow([i, r["sentence"], r["option1"], r["option2"], r["answer"]])

    meta = {
        "posts_total": len(posts), "posts_train": len(train), "posts_heldout": len(held),
        "chars_train": (out / "blog_train.txt").stat().st_size,
        "chars_heldout": (out / "blog_heldout.txt").stat().st_size,
        "general_paragraphs": len(paras),
        "heldout_posts": sorted(held),
    }
    (out / "corpora.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in meta.items() if k != "heldout_posts"}))


if __name__ == "__main__":
    main()
