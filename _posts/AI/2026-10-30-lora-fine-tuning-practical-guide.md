---
layout: post
title: "LoRA Fine-Tuning LLMs: A Practical Guide from Dataset to Eval Gate"
date: 2026-10-30 15:25:00 +0000
categories: [ai, fine-tuning]
tags: [lora, qlora, fine-tuning, model-training, evals, peft, transformers, llm]
author: the lamplit labs team
description: "A hands-on LoRA fine-tuning walkthrough: build a clean dataset, pick a rank, train with PEFT and TRL, and gate the merge on an eval harness instead of vibes."
image:
  path: /assets/img/posts/ai/lora-fine-tuning-practical-guide.webp
  alt: "Dark blueprint-style poster titled LoRA Fine-Tuning LLMs: A Practical Guide, showing a frozen pretrained base model weight matrix on the left with snowflake markers, an arrow labelled attach pointing to a green trainable LoRA adapter block on the right containing matrices A and B with a slim green rank bar marked rank r = 16."
---

You have a base model that answers well in general and badly on your domain: your ticket taxonomy, your API conventions, your compliance phrasing. Fine-tuning fixes that, but full fine-tuning of a 7B model wants hardware you may not have and can quietly overwrite the general ability you liked. LoRA - low-rank adaptation - is the practical middle path: freeze the base weights, train two small matrices per targeted layer, and merge or swap the result as a versioned adapter.

Our [cost and quality comparison of LoRA vs full fine-tuning]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %}) covered when to choose which. This guide is the sequel: once you have chosen LoRA, here is how to actually do it - dataset, rank, config, training, and the eval gate that decides whether the adapter ships.

## Dataset: quality beats quantity, and format beats both

For an instruction or chat fine-tune, 500-2,000 high-quality examples routinely outperform 50,000 scraped ones. Each record should be one complete conversation in the exact chat template your model ships with:

```json
{"messages": [
  {"role": "system", "content": "You are the Lamplit support triage assistant."},
  {"role": "user", "content": "Customer reports 429s on the gateway after deploy."},
  {"role": "assistant", "content": "A 429 storm right after a deploy usually means..."}
]}
```

Three checks before you train a single step:

- **Format lint.** Render every record through the tokenizer's chat template and diff it against what you expect. A wrong BOS token or a missing turn boundary teaches the model to emit broken structure at inference time.
- **Split near-duplicates, not just rows.** If a templated support case appears 40 times, all 40 copies belong in the same split. Otherwise your eval set leaks and reports a fantasy score.
- **Balance the negative space.** Include examples of the model correctly declining, asking a clarifying question, and saying "I don't know". A dataset of only happy-path answers produces a model that hallucinates confidently on out-of-scope prompts.

## Pick a rank: start small, spend memory where it matters

The rank `r` controls the capacity of the adapter: the weight update is factored as `A x B` with an inner dimension of `r`, so parameters and optimizer memory grow linearly with it. More rank is not more better - past a task-dependent plateau it mostly buys overfitting.

![Bar chart of trainable parameters in millions and AdamW optimizer memory in gigabytes across LoRA ranks 1, 4, 8, 16, 32, 64 and 128 for a 7B base model, with parameters climbing from about 4 million at rank 1 to about 537 million at rank 128 and a green callout marking ranks 8 to 32 as the sweet spot for most tasks.](/assets/img/posts/ai/lora-rank-parameters-memory.webp)

Rules of thumb that have held up across our runs:

- Start at **r = 16**, `alpha = 32` (so the effective scale `alpha / r` is 2). Drop to r = 8 for narrow style or format tasks; climb to 32-64 only when the eval shows the model lacks knowledge the base does not have.
- **Target more than the attention blocks.** Applying LoRA to the MLP projections (`gate_proj`, `up_proj`, `down_proj`) alongside `q_proj` and `v_proj` costs little and consistently helps knowledge-heavy tasks.
- Watch **optimizer memory, not parameter count**. AdamW keeps roughly 12 bytes of state per trainable parameter (fp32 master weight plus two moments), which is why the orange line in the chart is the one that fills your GPU.

## Training config that survives first contact

With PEFT and TRL the whole setup fits in a few dozen lines:

```python
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

peft_cfg = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    task_type="CAUSAL_LM",
)
train_cfg = SFTConfig(
    output_dir="runs/triage-v3",
    per_device_train_batch_size=4,
    gradient_accumulation_steps=8,   # effective batch 32
    learning_rate=1e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.03,
    num_train_epochs=3,
    logging_steps=10,
    save_strategy="epoch",
    bf16=True,
    max_length=2048,
)
trainer = SFTTrainer(model=model, args=train_cfg,
                     train_dataset=ds, peft_config=peft_cfg)
trainer.train()
```

The knobs that bite people, in order of frequency:

1. **Learning rate.** LoRA wants 10-50x the LR of a full fine-tune: `1e-4` to `2e-4` with cosine decay is a sane band. Full-fine-tune rates like `2e-5` train the adapter into noise-shaped nothing.
2. **Epochs.** Two to four. Loss that keeps falling after epoch three on a small dataset is usually memorization; the eval set is the arbiter.
3. **Packing vs padding.** Packing short examples into full sequences speeds training but mingles unrelated conversations; for chat data with hard turn boundaries, unpadded batches with a length-grouped sampler are safer.
4. **Smoke test first.** One epoch on 5% of the data, then check that loss decreased and a sample generation is syntactically coherent. Ten minutes here has saved us many multi-hour broken runs.

Tight on VRAM? QLoRA quantizes the frozen base to 4-bit and backpropagates through it - adapter quality is nearly identical and a 7B fine-tune drops from ~40 GB to ~12 GB. If you also plan to compress for serving, read our [quantization formats field guide]({% post_url AI/2026-10-28-quantization-gguf-vs-awq-vs-gptq-quality-latency %}) before you merge, because merge order matters.

## The eval gate is the deliverable

Training loss going down is not evidence the model got better at your task. Before the first run, build a held-out eval set of 100-300 prompts with rubric-checked expected answers, and score **both** the base model and every candidate adapter against it.

![Flow diagram of the fine-tuning loop in five boxes: dataset with JSONL chat records and a near-duplicate split, config with rank alpha dropout target modules and learning-rate schedule, train with a one-epoch smoke test and checkpoints, eval with a held-out rubric set and a base-versus-tuned regression gate, and merge with the adapter tagged and versioned, with a green feedback arrow from eval back to dataset labelled eval failures become new training examples.](/assets/img/posts/ai/lora-fine-tuning-pipeline.webp)

The loop that keeps quality honest:

- **Diff, don't just score.** The interesting artifact is the per-prompt delta table: where the adapter gained, where it regressed. A +8% average hiding a -30% cliff on one intent class is a no-merge.
- **Gate on regressions.** Ship criteria like "no eval category drops more than 2 points, target category improves at least 10". Automate it in CI the way you would gate a latency regression - our post on [fine-tuning pipeline regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) shows the harness pattern.
- **Feed failures back.** Every eval failure is a candidate training example for the next iteration. Three or four loops of this beat one heroic 10-epoch run every time.

## Merge, tag, version

When the gate passes, merge the adapter into the base weights for serving (`merge_and_unload()` in PEFT) or keep it as a sidecar if you serve multiple adapters per base. Either way, record the lineage: base model digest, dataset commit, config, eval scores, and the adapter artifact hash. Fine-tunes are experiments; the ones you cannot reproduce are the ones that regress in production six weeks later.

And a closing note on disclosure: a fine-tuned model inherits the base model's license obligations, and your training data's provenance travels with the adapter. Our [fine-tuning data curation and eval set construction guide]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %}) goes deeper on provenance and split hygiene.

## Where Pulse fits

This loop - dataset commit, training config, eval gate, merge decision - is exactly the kind of multi-step, check-gated workflow we are building Pulse to automate. Pulse is Lamplit Labs' self-improving automation product (coming soon): it turns repeated engineering rituals like eval gating into durable, versioned pipelines that get better each run. If your team re-runs fine-tunes monthly, that is the layer that keeps the fourth re-run as reliable as the first.

## Related posts

- [LoRA vs full fine-tuning for enterprise LLMs: a cost and quality comparison]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %})
- [Fine-tuning data curation: building eval sets you can trust]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %})
- [Fine-tuning pipeline regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [RAG vs fine-tuning for the enterprise internal copilot]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %})
