---
title: "LoRA vs QLoRA vs full fine-tuning: the GPU memory, cost, and eval-score tradeoffs"
description: "LoRA and QLoRA cut GPU memory 3-5x and training cost 3-6x versus full fine-tuning. See where their eval scores match and how to pick per task."
date: 2026-10-27 09:00:00 +0000
last_modified_at: 2026-10-27 09:00:00 +0000
image:
  path: /assets/img/headers/ai/lora-vs-full-fine-tuning-cost-quality-enterprise.webp
  alt: "Grouped bar chart comparing GPU memory for a 13B model: full fine-tuning at 168 GB, LoRA at 62 GB, and QLoRA at 30 GB."
categories: ai
tags: fine-tuning lora qlora model-training gpu-cost enterprise-ai llm
---

When a team decides a base model is not enough, the default answer used to be full fine-tuning: update every weight. For a 7B model that was painful; for a 13B or 70B model it is a budget line of its own. Low-rank adapters changed the arithmetic. **LoRA** (Low-Rank Adaptation) and **QLoRA** (its quantized sibling) let you specialize a large model on one GPU instead of a cluster - but they are not free. This post lays out the three tradeoffs that decide which method to use: GPU memory, training cost, and eval-score quality.

## What each method actually updates

**Full fine-tuning** updates all model weights. In mixed precision with AdamW, the optimizer alone dominates memory: each parameter needs the bf16 weight, an fp32 master copy, and two fp32 optimizer moments - roughly 14-16 bytes per parameter before gradients and activations. A 13B model lands near 170 GB of VRAM: three A100 80GB cards or a sharded setup.

**LoRA** freezes the base weights and trains small low-rank matrices (typically rank 8-64) injected into the attention and MLP projections. Trainable parameters drop from 13 billion to roughly 40-160 million - about 0.3-1% of the model. You still load the base weights, but the optimizer state shrinks by two orders of magnitude: the same 13B model fits in about 60 GB, one A100 80GB.

**QLoRA** goes one step further: the frozen base weights are stored in 4-bit NormalFloat (NF4) quantization and only dequantized during the forward pass. The base model now takes about a quarter of its bf16 footprint, and a 13B model trains in roughly 30 GB - a single A100 40GB or a high-end workstation card.

![Grouped bar chart comparing GPU memory for a 13B model: full fine-tuning at 168 GB needing multiple A100s, LoRA at 62 GB fitting one A100 80GB, and QLoRA at 30 GB fitting a single A100 40GB.]({{ '/assets/img/headers/ai/lora-vs-full-fine-tuning-cost-quality-enterprise.webp' | relative_url }})

*The memory picture in one glance: full fine-tuning at ~168 GB, LoRA at ~62 GB, QLoRA at ~30 GB for the same 13B model.*

## GPU memory: where the wall actually is

The optimizer, not the weights, is what kills full fine-tuning. AdamW keeps two fp32 moments per parameter, so memory scales linearly with parameter count and there is no batch-size knob that fixes it. Gradient checkpointing and smaller micro-batches trim activation memory but leave the 13-bytes-per-parameter optimizer-plus-master-weight block untouched.

LoRA's memory floor is the base model itself: bf16 weights (26 GB at 13B) plus activations and the small adapter optimizer. QLoRA lowers that floor to the 4-bit weights (~7-8 GB at 13B) plus the quantization overhead, paged optimizer states, and activations. This is why QLoRA made fine-tuning a 65B model on a single 48 GB GPU feasible in the original paper's experiments.

The header chart shows the practical consequence: full fine-tuning is a multi-GPU scheduling problem, LoRA is a one-GPU job, and QLoRA is a one-modest-GPU job.

## Training cost: the same bars, in dollars

Memory maps almost directly to money because it decides how many GPUs you rent and how scarce those GPUs are.

![Horizontal bar chart of illustrative cost per training epoch on 10k samples for a 13B model: full fine-tuning about 13.2 USD on three on-demand A100 80GB GPUs, LoRA about 4.4 USD on one A100 80GB, and QLoRA about 2.6 USD on one A100 40GB.]({{ '/assets/img/posts/ai/lora-vs-full-fine-tuning-cost-per-epoch.webp' | relative_url }})

With on-demand 2026 cloud pricing (~$2.20/hr per A100 80GB, ~$1.10/hr per A100 40GB), one epoch over 10k samples of 2k tokens costs roughly:

- **Full fine-tuning:** 3 x A100 80GB for ~2 hours = **~$13**
- **LoRA:** 1 x A100 80GB for ~2 hours = **~$4.40**
- **QLoRA:** 1 x A100 40GB for ~2.4 hours (4-bit dequantization adds ~15-25% step time) = **~$2.60**

The interesting consequence is not the single-run saving - it is what it does to your experiment budget. At full fine-tuning prices, most teams can afford a handful of data-recipe or hyperparameter trials per month. At QLoRA prices, the same budget buys 5x as many runs, and in practice **the extra experiments move quality more than the choice of method does**. Cap the sweep, keep the runner-up checkpoint as a rollback candidate, and let the gate suite pick the winner.

Two caveats keep the comparison honest. First, QLoRA's 4-bit base is slightly slower per step, so at very large token counts the gap narrows. Second, full fine-tuning parallelizes better: if your deadline is hours, not dollars, three GPUs finishing in one hour can be worth the 3x price.

## Eval-score quality: where adapters match and where they lose

Cost only matters if the model still passes your gates. The consistent pattern across the LoRA and QLoRA papers and subsequent reproductions: adapters match full fine-tuning on narrow, format-heavy tasks and trail it on tasks that need new knowledge or a global shift in the model's behavior.

![Horizontal diverging bar chart of eval-score gap versus full fine-tuning in percentage points for a 13B model under identical gates: style conformance LoRA minus 0.1 and QLoRA minus 0.4; classification LoRA minus 0.2 and QLoRA minus 0.6; long-form domain writing LoRA minus 1.1 and QLoRA minus 1.9; internal QA LoRA minus 0.8 and QLoRA minus 1.4; knowledge-heavy QA LoRA minus 1.6 and QLoRA minus 2.7.]({{ '/assets/img/posts/ai/lora-vs-full-fine-tuning-eval-deltas.webp' | relative_url }})

Reading the deltas:

- **Style, tone, and output format:** adapters are effectively at parity. Conformance lives in a small subspace; rank 16-32 captures it.
- **Classification and extraction:** within a few tenths of a point - inside the noise of a re-run for most gate suites.
- **Knowledge-heavy QA:** the biggest gap. Teaching the model facts it did not already have means moving the same weights adapters deliberately freeze; full fine-tuning leads by 1.5-3 points here.
- **QLoRA vs LoRA:** expect a further 0.3-1 point drop from 4-bit quantization of the base. On format tasks it rarely matters; on the knowledge-heavy tail it compounds.

The gate suite that referees these scores does not appear by magic: [the data-curation and eval-set post]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %}) covers how the frozen 400-prompt golden set behind every score here was built, deduped against the training corpus, and stratified by risk tier. With the set in hand, [run every candidate through the same regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) so an adapter that drifts on one slice fails loudly instead of shipping quietly.

## A decision rule that survives contact with procurement

1. **Start with QLoRA** for any task that is about format, style, routing, or extraction. It is the cheapest way to get a gated baseline, and it runs on hardware you already have.
2. **Promote to LoRA** (bf16 base) when the QLoRA candidate fails a gate by less than ~1 point and the task is not knowledge-heavy - the quantization is the likely culprit.
3. **Reserve full fine-tuning** for knowledge injection, large domain shifts (new language, new modality of jargon), or when adapters plateau 2+ points behind on your gate metric after rank and data tuning. Budget the multi-GPU run and the hyperparameter sweep around it accordingly.
4. **Keep adapters as the default serving artifact** when you can: dozens of task-specific LoRA adapters can share one deployed base model and hot-swap, which no fleet of fully fine-tuned checkpoints can match operationally.

One more operational note: many "fine-tune or not" debates are really [RAG vs fine-tuning]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %}) debates. If the gap is missing facts, retrieval usually beats both full fine-tuning and adapters on cost and freshness; fine-tune for behavior, retrieve for knowledge.

## Related

- [Fine-tuning data curation and eval-set construction for enterprise teams]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %})
- [Model training and fine-tuning: turn the training loop into a pipeline with regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [The real cost of AI automation]({% post_url AI/2026-10-09-real-cost-of-ai-automation %})
- [RAG vs fine-tuning for the enterprise internal copilot]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %})
