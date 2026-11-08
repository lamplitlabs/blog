#!/usr/bin/env python3
"""Build the replay-mix training files for the "replay data vs forgetting" post.

Every mix holds the same number of characters (TRAIN_CHARS). A mix with replay fraction p takes the
first (1-p)*TRAIN_CHARS characters of this blog's training posts (blog_train.txt from
scripts/finetune-eval/build_corpora.py) and p*TRAIN_CHARS characters of general English replay text:
the FLORES passages behind Belebele (English Wikinews, Wikivoyage and Wikibooks). The replay text is
deliberately not the general evaluation text (XQuAD's Wikipedia paragraphs), so a lower drift score
means the model kept general English, not that it saw the test paragraphs.

The two streams are cut into ~1,500-character blocks on paragraph boundaries and interleaved with a
seeded draw weighted by the characters each stream has left, so replay is spread across the whole
epoch, including the 5% tail that llama-finetune keeps as its validation split.

    python3 scripts/finetune-replay/build_mixes.py <corpus_dir> [--mixes 0,10,25,50]
"""
from __future__ import annotations

import argparse
import glob
import json
import random
from pathlib import Path

TRAIN_CHARS = 400_000
BLOCK = 1_500


def blocks(text: str) -> list[str]:
    out, cur = [], ""
    for para in text.split("\n\n"):
        cur = f"{cur}\n\n{para}" if cur else para
        if len(cur) >= BLOCK:
            out.append(cur)
            cur = ""
    if cur:
        out.append(cur)
    return out


def take(blks: list[str], n: int) -> list[str]:
    out, total = [], 0
    for b in blks:
        if total >= n:
            break
        b = b[: n - total]
        out.append(b)
        total += len(b) + 2
    return out


def runs(kinds: list[str], merged: list[str]) -> list[list]:
    out: list[list] = []
    for k, b in zip(kinds, merged):
        if out and out[-1][0] == k:
            out[-1][1] += len(b) + 2
        else:
            out.append([k, len(b) + 2])
    return out


def replay_text(hf_cache: Path) -> str:
    path = next(hf_cache.glob("datasets--facebook--belebele/snapshots/*/data/eng_Latn.jsonl"))
    seen, paras = set(), []
    for line in path.read_text(encoding="utf-8").splitlines():
        p = json.loads(line)["flores_passage"].strip()
        if p not in seen:
            seen.add(p)
            paras.append(p)
    random.Random(11).shuffle(paras)
    return "\n\n".join(paras)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("corpus")
    ap.add_argument("--hf-cache", default=str(Path.home() / ".cache/huggingface/hub"))
    ap.add_argument("--mixes", default="0,10,25,50", help="replay percentages")
    ap.add_argument("--order-seed", type=int, default=0,
                    help="re-draw the interleave order only (same blocks); writes mix_<pct>s<seed>.txt")
    a = ap.parse_args()
    corpus = Path(a.corpus)
    domain = (corpus / "blog_train.txt").read_text(encoding="utf-8")
    general = replay_text(Path(a.hf_cache))
    if not a.order_seed:  # shared files: written once, never while a seeded build runs beside a sweep
        (corpus / "replay_pool.txt").write_text(general + "\n", encoding="utf-8")
        # the "seen" perplexity text: blog text that every mix trains on (the head of the domain stream)
        (corpus / "train_seen.txt").write_text(domain[:100_000], encoding="utf-8")
    meta_path = corpus / "mixes.json"
    meta = {"train_chars": TRAIN_CHARS, "replay_pool_chars": len(general), "mixes": {}}
    if a.order_seed and meta_path.exists():  # keep the main mixes' entries
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    suffix = f"s{a.order_seed}" if a.order_seed else ""
    for pct in (int(x) for x in a.mixes.split(",")):
        n_gen = TRAIN_CHARS * pct // 100
        if n_gen > len(general):
            raise SystemExit(f"replay pool has {len(general)} chars, mix {pct}% needs {n_gen}")
        if pct == 0 and not a.order_seed:  # byte-identical to finetune-eval's train_subset.txt (head -c 400000)
            text = domain.encode()[:TRAIN_CHARS].decode("utf-8", "ignore")
            (corpus / "mix_00.txt").write_text(text, encoding="utf-8")
            meta["mixes"]["0"] = {"domain_chars": len(text), "replay_chars": 0, "replay_blocks": 0, "domain_blocks": None}
            continue
        d = take(blocks(domain), TRAIN_CHARS - n_gen)
        g = take(blocks(general), n_gen)
        rng = random.Random(pct + 1000 * a.order_seed)
        merged, kinds, di, gi = [], [], 0, 0
        d_left, g_left = sum(map(len, d)), sum(map(len, g))
        while di < len(d) or gi < len(g):
            if gi < len(g) and (di >= len(d) or rng.random() < g_left / (g_left + d_left)):
                merged.append(g[gi]); kinds.append("R"); g_left -= len(g[gi]); gi += 1
            else:
                merged.append(d[di]); kinds.append("D"); d_left -= len(d[di]); di += 1
        text = "\n\n".join(merged) + "\n"
        (corpus / f"mix_{pct:02d}{suffix}.txt").write_text(text, encoding="utf-8")
        tail = text[int(len(text) * 0.95):]
        meta["mixes"][f"{pct}{suffix}"] = {
            "domain_chars": sum(map(len, d)), "replay_chars": sum(map(len, g)),
            "domain_blocks": len(d), "replay_blocks": len(g),
            "replay_share_of_val_tail": round(sum(len(b) for b in g if b in tail) / max(1, len(tail)), 3),
            # file layout as runs of [kind, chars]: D = blog text, R = replay text (for the layout chart)
            "layout": runs(kinds, merged),
        }
    meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: {m: {f: v for f, v in x.items() if f != "layout"} for m, x in meta["mixes"].items()} if k == "mixes" else meta[k] for k in meta}))


if __name__ == "__main__":
    main()
