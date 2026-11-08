#!/usr/bin/env python3
"""Parse the logs run_mixes.sh wrote into scripts/data/finetune-replay-smollm2-135m.json.

    python3 scripts/finetune-replay/summarise.py <work_dir> [out.json]

Reuses the log parsers of scripts/finetune-eval/summarise.py (same llama.cpp tools, same formats).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "finetune-eval"))
from summarise import general, ppl, train  # noqa: E402


def main() -> None:
    work = Path(sys.argv[1])
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "scripts/data/finetune-replay-smollm2-135m.json")
    logs = work / "logs"
    rows = []
    for done in sorted(logs.glob("*.eval.done")):
        tag = done.name[: -len(".eval.done")]
        row = {"tag": tag}
        if tag == "base":
            row.update(replay_pct=None, lr=None, epoch=0)
        else:
            m = re.match(r"mix(\d+)(?:s(\d+))?_lr([\de.-]+)_ep(\d+)", tag)
            row.update(replay_pct=int(m[1]), order_seed=int(m[2] or 0), lr=m[3], epoch=int(m[4]))
            row["training"] = train(logs / f"{tag}.train.log")
            secs = logs / f"{tag}.train_seconds"
            row["train_seconds"] = int(secs.read_text()) if secs.exists() else None
        row["ppl_seen"] = ppl(logs / f"{tag}.ppl_seen.log")
        row["ppl_heldout"] = ppl(logs / f"{tag}.ppl_heldout.log")
        row["general"] = general(logs / f"{tag}.general.log")
        hs = (logs / f"{tag}.hellaswag.log").read_text(errors="replace")
        m = re.findall(r"^(\d+)\t([\d.]+)%\t\[([\d.]+)%, ([\d.]+)%\]", hs, re.M)
        row["hellaswag"] = {"tasks": int(m[-1][0]), "acc": float(m[-1][1]), "lo": float(m[-1][2]), "hi": float(m[-1][3])}
        rows.append(row)
    rows.sort(key=lambda r: (r["replay_pct"] is not None, -float(r["lr"] or 0), r["replay_pct"] or 0, r.get("order_seed", 0), r["epoch"]))
    corpus = work / "corpus"
    meta = json.loads((corpus / "corpora.json").read_text())
    mixes = json.loads((corpus / "mixes.json").read_text())
    trained = {f"{r['replay_pct']}" + (f"s{r['order_seed']}" if r.get("order_seed") else "") for r in rows if r["epoch"]}
    mixes["mixes"] = {k: v for k, v in mixes["mixes"].items() if k in trained}  # only mixes that were run
    data = {
        "model": "HuggingFaceTB/SmolLM2-135M-Instruct (F32 GGUF via scripts/finetune-eval/hf_to_gguf.py)",
        "trainer": "llama-finetune (full fine-tune, AdamW, ctx 256, 1 epoch per run, -lr as tagged, -s 1)",
        "evaluator": "llama-perplexity, ctx 512; KL divergence vs the base model's logits on general_wiki.txt; HellaSwag 1000 tasks",
        "host": "Apple M2 Pro, 16 GB, Metal (-ngl 99)",
        "domain_data": "this blog's posts, post-level hash split (scripts/finetune-eval/build_corpora.py)",
        "replay_data": "FLORES English passages behind Belebele (Wikinews/Wikivoyage/Wikibooks), not the XQuAD eval text",
        "general_eval_data": "240 English Wikipedia paragraphs from XQuAD",
        "corpora": {k: v for k, v in meta.items() if k != "heldout_posts"},
        "mixes": mixes,
        "runs": rows,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(rows)} checkpoints)")


if __name__ == "__main__":
    main()
