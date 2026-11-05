#!/usr/bin/env python3
"""Parse the logs run_sweep.sh wrote into scripts/data/finetune-eval-smollm2-135m.json.

    python3 scripts/finetune-eval/summarise.py <work_dir> [out.json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def last(pattern: str, text: str, cast=float):
    m = re.findall(pattern, text)
    return cast(m[-1]) if m else None


def ppl(path: Path):
    t = path.read_text(errors="replace")
    m = re.findall(r"Final estimate: PPL = ([\d.]+) \+/- ([\d.]+)", t)
    return {"ppl": float(m[-1][0]), "pm": float(m[-1][1])} if m else None


def general(path: Path):
    t = path.read_text(errors="replace")
    out = ppl(path) or {}
    if "KL divergence statistics" in t:
        out.update(
            ppl=last(r"Mean PPL\(Q\)\s*:\s*([\d.]+)", t),
            pm=last(r"Mean PPL\(Q\)\s*:\s*[\d.]+\s*±\s*([\d.]+)", t),
            kld_mean=last(r"Mean\s+KLD:\s*([\d.]+)", t),
            kld_pm=last(r"Mean\s+KLD:\s*[\d.]+\s*±\s*([\d.]+)", t),
            kld_p99=last(r"99\.0%\s+KLD:\s*([\d.]+)", t),
            kld_median=last(r"Median\s+KLD:\s*([\d.]+)", t),
            same_top_p=last(r"Same top p:\s*([\d.]+)", t),
            same_top_p_pm=last(r"Same top p:\s*[\d.]+\s*±\s*([\d.]+)", t),
        )
    return out


def train(path: Path):
    t = path.read_text(errors="replace").replace("\r", "\n")
    tr = [l for l in t.splitlines() if l.startswith("train:")]
    va = [l for l in t.splitlines() if l.startswith("val:")]
    def parse(line):
        m = re.search(r"loss=([\d.]+)±([\d.]+) acc=([\d.]+)±([\d.]+)%", line)
        return {"loss": float(m[1]), "loss_pm": float(m[2]), "acc": float(m[3])} if m else None
    steps = last(r"data=\d+/(\d+)", tr[-1], int) if tr else None
    curve = []  # llama-finetune prints the running mean loss of the epoch so far
    for line in tr:
        m = re.search(r"data=(\d+)/\d+ loss=([\d.]+)", line)
        if m and (int(m[1]) % 50 == 0 or int(m[1]) == steps):
            curve.append([int(m[1]), float(m[2])])
    return {"train": parse(tr[-1]) if tr else None, "val": parse(va[-1]) if va else None,
            "chunks": steps, "running_loss": curve}


def main() -> None:
    work = Path(sys.argv[1])
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "scripts/data/finetune-eval-smollm2-135m.json")
    logs = work / "logs"
    rows = []
    for done in sorted(logs.glob("*.eval.done")):
        tag = done.name[: -len(".eval.done")]
        row = {"tag": tag}
        if tag == "base":
            row.update(lr=None, epoch=0)
        else:
            m = re.match(r"lr([\de.-]+)_ep(\d+)", tag)
            row.update(lr=m[1], epoch=int(m[2]))
            row["training"] = train(logs / f"{tag}.train.log")
            secs = logs / f"{tag}.train_seconds"
            row["train_seconds"] = int(secs.read_text()) if secs.exists() else None
        row["ppl_seen"] = ppl(logs / f"{tag}.ppl_seen.log")
        row["ppl_heldout"] = ppl(logs / f"{tag}.ppl_heldout.log")
        row["general"] = general(logs / f"{tag}.general.log")
        hs = (logs / f"{tag}.hellaswag.log").read_text(errors="replace")
        m = re.findall(r"^(\d+)\t([\d.]+)%\t\[([\d.]+)%, ([\d.]+)%\]", hs, re.M)
        row["hellaswag"] = {"tasks": int(m[-1][0]), "acc": float(m[-1][1]), "lo": float(m[-1][2]), "hi": float(m[-1][3])}
        wg = (logs / f"{tag}.winogrande.log").read_text(errors="replace")
        m = re.search(r"Final Winogrande score\((\d+) tasks\): ([\d.]+) \+/- ([\d.]+)", wg)
        row["winogrande"] = {"tasks": int(m[1]), "acc": float(m[2]), "pm": float(m[3])}
        sample = logs / f"{tag}.sample.txt"
        row["sample"] = sample.read_text(errors="replace").strip() if sample.exists() else None
        rows.append(row)
    rows.sort(key=lambda r: (float(r["lr"]) if r["lr"] else 0.0, r["epoch"]))
    meta = json.loads((work / "corpus/corpora.json").read_text())
    data = {
        "model": "HuggingFaceTB/SmolLM2-135M-Instruct (F32 GGUF via scripts/finetune-eval/hf_to_gguf.py)",
        "trainer": "llama-finetune (llama.cpp build 11669), full fine-tune, AdamW, ctx 256, 1 epoch per checkpoint, seed 1",
        "evaluator": "llama-perplexity, ctx 512; HellaSwag 1000 tasks; Winogrande validation (1266 tasks)",
        "host": "Apple M2 Pro, 16 GB, Metal (-ngl 99)",
        "corpora": {k: v for k, v in meta.items() if k != "heldout_posts"},
        "train_chars": (work / "corpus/train_subset.txt").stat().st_size,
        "seen_chars": (work / "corpus/train_seen.txt").stat().st_size,
        "runs": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} checkpoints)")


if __name__ == "__main__":
    main()
