---
layout: post
title: "Fine-Tuning Evaluation, Measured: Held-Out Perplexity, KL Drift and Benchmarks"
date: 2026-11-04 09:00:00 +0100
categories: ai
author: manishtiwari25
description: "We fine-tuned SmolLM2-135M on this blog with llama.cpp. At lr 1e-5, training-text perplexity fell 71% while held-out perplexity rose 30%. Four checks."
image:
  path: /assets/img/headers/ai/fine-tuning-evaluation-measured.webp
  alt: "Header card titled Fine-tuning evaluation, measured: SmolLM2-135M tuned on this blog with llama.cpp, one model, four scorecards. Four small bar charts compare the base model, the lr 1e-6 epoch 2 fine-tune and the lr 1e-5 epoch 2 fine-tune. Perplexity on text it trained on: 28.1, 10.1, 8.0. Perplexity on held-out posts: 22.9, 16.5, 29.8. Perplexity on general text: 16.5, 18.2, 53.9. HellaSwag accuracy: 42.6%, 42.3%, 34.8%."
tags: [fine-tuning, model-training, evals, llama.cpp, gguf, llm, benchmark]
---

The [LoRA practical guide]({% post_url AI/2026-10-30-lora-fine-tuning-practical-guide %}) ends with "the eval gate is the deliverable". This post puts numbers behind that sentence. We fine-tuned a small model on this blog's own posts, on a laptop, at three learning rates for two epochs each. Then we scored every checkpoint four ways and watched where the scores disagreed.

They disagreed a lot. **The checkpoint with the second-best perplexity on its own training text was worse than the untouched base model on posts it had not seen, and three times worse on ordinary English.** A run that is judged only on its training curve ships that model.

**The short version:**

- **Training-text perplexity is not an evaluation.** At learning rate 1e-5, perplexity on text the model trained on fell from 28.1 to 8.0 (-71%). On 33 held-out posts it rose from 22.9 to 29.8 (+30%).
- **Split by document, not by line.** The held-out set is whole posts the trainer never saw. A random line split would put sentences from the same post on both sides and hide the overfit.
- **Measure what the model forgets.** KL divergence to the base model on general text was 0.11 nats per token for the best checkpoint and 1.26 for the worst. On general text the worst checkpoint picked the same next token as the base model only 49% of the time.
- **Pick benchmarks the base model can pass.** HellaSwag (base 42.6%, chance 25%) caught an 8-point drop. Winogrande (base 52.9%, chance 50%) moved by noise only and could not tell any checkpoint apart.
- **The winner was the gentlest run.** Learning rate 1e-6 for two epochs cut held-out perplexity by 28%. It cost 10% general-text perplexity and no measurable benchmark accuracy.

## Setup

Everything ran on one Apple M2 Pro (16 GB) with llama.cpp build 11669. llama.cpp has a full fine-tuning example, `llama-finetune`. It trains every weight of a GGUF model in F32, so it is not LoRA. But the evaluation questions are the same for any fine-tune, and `llama-perplexity` answers all of them from the command line.

| | |
|---|---|
| Model | [SmolLM2-135M-Instruct](https://huggingface.co/HuggingFaceTB/SmolLM2-135M-Instruct), converted to an F32 GGUF |
| Domain data | this blog's 196 posts (front matter removed), split by a hash of the file path: 163 for training, 33 held out |
| Training text | the first 400 KB of the shuffled training posts (109,144 tokens), context 256, AdamW, one epoch per checkpoint |
| Learning rates | 1e-6, 3e-6 and 1e-5 (the `llama-finetune` default), two epochs each |
| General text | 240 English Wikipedia paragraphs from XQuAD (41,078 tokens) |
| Benchmarks | HellaSwag validation (first 1,000 tasks) and Winogrande validation (all 1,266) |

One epoch took 15 to 40 minutes. The machine was running other jobs, so wall time is not a benchmark here. Scoring one checkpoint with every check below took about half a minute. Evaluation is cheap compared with training, so a run that trains for an hour and skips evaluation saves almost nothing.

`llama-finetune` holds back the last 5% of the training file as its own validation split. With `-s 1` and `-s 2` it wrote byte-identical models: the seed did not change the data order or the result. The error bars below therefore measure the evaluation text, not run-to-run training noise.

## Check 1: three perplexities, not one

Perplexity is the exponential of the average loss per token. Lower means the model finds the text less surprising. We measured it on three texts with `llama-perplexity -c 512`: 100 KB of the training text, the 33 held-out posts, and general English.

![Three bar charts of perplexity for the base model and six fine-tuned checkpoints (learning rates 1e-6, 3e-6 and 1e-5, epochs 1 and 2). Text it trained on: base 28.1, and every checkpoint lower, down to 6.9 at lr 3e-6 epoch 2 and 8.0 at lr 1e-5 epoch 2. Held-out posts: base 22.9; lr 1e-6 epoch 2 is lowest at 16.5, lr 3e-6 is 18.1 and 17.5, and lr 1e-5 is worse than base at 31.4 and 29.8. General English: base 16.5; lr 1e-6 18.7 and 18.2, lr 3e-6 21.7 and 20.9, lr 1e-5 45.0 and 53.9.](/assets/img/posts/ai/fine-tuning-eval-three-perplexities.webp){: width="1400" height="760" }

Every checkpoint looks like progress on the left chart. The middle chart is the one that matters for a model meant to write like this blog. There, the lr 1e-5 runs are worse than doing nothing: 31.4 and 29.8 against the base model's 22.9. The two 1e-5 checkpoints have 15.1 and 8.0 perplexity on their training text. That is almost the same as the 1e-6 runs (15.6 and 10.1), which are the best on held-out posts. **The training-side number cannot separate the best run from the worst.**

The held-out set only works because it is split by post. Our [data curation guide]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %}) makes the same point for near-duplicates. A post repeats its own terms, code and phrasing. Put half its paragraphs in training and half in evaluation, and the evaluation set rewards memorising that post.

## Check 2: drift from the base model

A fine-tune that improves the target domain can still damage everything else. llama.cpp measures this directly. Save the base model's logits on a general text once. Then score each checkpoint against them:

```bash
# once, with the base model (writes every token's logits: 2.0 GB for 41k tokens)
llama-perplexity -m base.gguf -f general_wiki.txt -c 512 --kl-divergence-base base_general.kld

# per checkpoint
llama-perplexity -m lr1e-6_ep2.gguf -f general_wiki.txt -c 512 \
  --kl-divergence-base base_general.kld --kl-divergence
```

![Terminal output of llama-perplexity with --kl-divergence for two checkpoints on general text. For lr1e-6_ep2.gguf: Mean PPL(Q) 18.171863 against Mean PPL(base) 16.519535, a ratio of 1.100023, Mean KLD 0.106518, 99.0% KLD 0.585135, Median KLD 0.075572, Same top p 81.299%. For lr1e-5_ep2.gguf: Mean PPL(Q) 53.917389, ratio 3.263856, Mean KLD 1.257181, 99.0% KLD 5.930273, Median KLD 0.961118, Same top p 48.912%.](/assets/img/posts/ai/fine-tuning-eval-kl-divergence-terminal.webp){: width="1400" height="769" }

The same output is used to judge quantization, as in our [GGUF vs AWQ vs GPTQ comparison]({% post_url AI/2026-10-28-quantization-gguf-vs-awq-vs-gptq-quality-latency %}), and it reads the same way here. Mean KL divergence is the average number of nats by which the checkpoint's next-token distribution differs from the base model's. "Same top p" is the share of tokens where both models would pick the same next token. A 99th-percentile KLD of 5.9 means the lr 1e-5 model's predictions for the worst 1% of tokens have almost nothing in common with the base model's.

## Check 3: benchmarks the base model can actually pass

![Three panels. Mean KL divergence from base on general text, per checkpoint: lr 1e-6 epochs 1 and 2: 0.138 and 0.107; lr 3e-6: 0.305 and 0.265; lr 1e-5: 1.080 and 1.257. Same next-token pick as base: 79.6% and 81.3%, 70.8% and 73.0%, 51.8% and 48.9%. General benchmarks with error bars: HellaSwag accuracy stays between 39.6% and 42.6% for base, lr 1e-6 and lr 3e-6, and drops to about 34.7% for both lr 1e-5 checkpoints; Winogrande stays between 50.0% and 54.6% for every checkpoint, right above its 50% chance line.](/assets/img/posts/ai/fine-tuning-eval-forgetting-benchmarks.webp){: width="1400" height="700" }

HellaSwag works as a forgetting alarm for this model. The base model scores 42.6% (95% interval 39.6 to 45.7) against a 25% chance level. The lr 1e-5 checkpoints score 34.6% and 34.8%, and their intervals do not overlap the base model's. The gentler runs all stay inside the base interval.

Winogrande is useless at this scale, and it is the more instructive result. A 135M model scores 52.9% against a 50% chance level, so every checkpoint sits between 50.0% and 54.6% with a standard error of 1.4 points. That includes the lr 1e-5 model, which is three times worse on general text. **A benchmark that the base model is at chance on cannot detect damage, and a flat line there is not a pass.** Before you adopt a benchmark as a gate, check that the base model scores well above chance on it.

Also note that the second epoch at lr 1e-6 and 3e-6 *lowered* KL divergence slightly (0.138 to 0.107, 0.305 to 0.265). Drift does not only grow with training time. Measure every checkpoint instead of assuming the first one is the safest.

## Check 4: read the trainer's own validation loss, but not alone

![Line chart of the running mean training loss that llama-finetune prints, across 1,614 chunks of 256 tokens (two epochs). The lr 1e-6 curve ends epoch 2 at a train loss of 3.00 with validation loss 3.11. The lr 3e-6 curve falls lowest, ending at 2.77 train with validation 3.19. The lr 1e-5 curve rises during epoch 1 to about 3.7, drops at the start of epoch 2 and ends at 3.14 train with validation 3.89.](/assets/img/posts/ai/fine-tuning-eval-training-loss.webp){: width="1400" height="620" }

`llama-finetune` prints a running mean of the epoch's training loss and, at the end of each epoch, a validation loss. Two things in this chart were useful early warnings:

- **The lr 1e-5 training loss went up during epoch 1** (3.36 at chunk 50, 3.68 at the end). Training loss that rises inside an epoch means the step size is too large. You can see it without any held-out data.
- **The trainer's validation loss ranked the runs in the same order as the held-out posts did**: 3.11 (lr 1e-6) < 3.19 (lr 3e-6) < 3.89 (lr 1e-5). The lowest *training* loss (2.77, lr 3e-6) was not the lowest validation loss.

What the validation loss cannot show is forgetting. It is measured on blog text, so it says nothing about the 3x general-text perplexity. Use it to stop a bad run early. Use checks 2 and 3 to decide whether a finished run ships.

## Samples are a smell test, not a score

All seven checkpoints completed the same prompt with greedy decoding: "The first thing to check when an Azure OpenAI client starts getting 429 errors is". The base model blamed "the `http.client.get()` method". The lr 1e-6 epoch 2 model wrote about "the `response_body` property" and then repeated itself. The lr 1e-5 epoch 1 model answered "the only thing you have to know", followed by a markdown heading and a link with an empty URL. It had copied this blog's layout without its content. None of the three is right; a 135M model does not know about 429s (our [client-side rate limiting post]({% post_url AI/2026-10-21-enterprise-ai-client-side-rate-limiting-azure-openai-429-storms %}) does). Reading a few samples catches format collapse quickly, but three samples could not have ranked these checkpoints. The numbers above did.

## The gate we would ship

Our [regression gates post]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) argues for gating on deltas against the base model, not absolute scores. With the measurements above, that gate is three lines:

| Rule (vs. base) | 1e-6 ep1 | 1e-6 ep2 | 3e-6 ep1 | 3e-6 ep2 | 1e-5 ep1 | 1e-5 ep2 |
|---|---|---|---|---|---|---|
| held-out PPL at least 10% lower | -22.7% ✅ | -28.0% ✅ | -21.1% ✅ | -23.6% ✅ | +36.9% ❌ | +30.1% ❌ |
| mean KLD on general text ≤ 0.15 | 0.138 ✅ | 0.107 ✅ | 0.305 ❌ | 0.265 ❌ | 1.080 ❌ | 1.257 ❌ |
| HellaSwag no more than 2 points below base | -1.2 ✅ | -0.3 ✅ | -3.0 ❌ | -1.2 ✅ | -8.0 ❌ | -7.8 ❌ |
| **promote** | yes | **yes (best)** | no | no | no | no |

The thresholds are choices, not laws. Set them from what your product can tolerate. Set them *before* the run, and write them into the pipeline, not into a review comment. Then the lr 1e-5 run, which is the `llama-finetune` default, never reaches anyone's laptop.

What this experiment does not show: one model family at one small size, one domain, full fine-tuning rather than LoRA, a 109k-token training slice, and one training run per setting (the trainer is deterministic). A 7B model with LoRA forgets less per step. But it still needs the same three measurements to prove that.

## Reproduce it

The scripts and the measured numbers are in the blog repository under `scripts/finetune-eval/` and `scripts/data/finetune-eval-smollm2-135m.json`. They need llama.cpp on `PATH`, the SmolLM2-135M-Instruct safetensors, and the cached HellaSwag, Winogrande and XQuAD files from the Hugging Face hub.

```bash
# 1. F32 GGUF from the Hugging Face checkpoint (numpy only, no torch)
python3 scripts/finetune-eval/hf_to_gguf.py <SmolLM2-135M-Instruct snapshot> work/smollm2-135m-f32.gguf

# 2. post-level split + general text + benchmark files (needs pyarrow)
python3 scripts/finetune-eval/build_corpora.py work/corpus

# 3. train one epoch at a time and evaluate every checkpoint (about 2 hours here)
LRS="1e-6 3e-6 1e-5" EPOCHS=2 scripts/finetune-eval/run_sweep.sh work work/smollm2-135m-f32.gguf

# 4. logs -> JSON -> the charts in this post
python3 scripts/finetune-eval/summarise.py work
python3 scripts/finetune-eval/gen_post_images.py --work work
```

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. The loop in this post is the kind of work it is built for: train, score against fixed held-out data, compare with the previous best, and promote only what passes a gate written down in advance. A model, a prompt or a code change all need the same thing, which is a check that cannot be argued with. The [Pulse introduction]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) has more on what we are building.

## Related posts

- [LoRA fine-tuning: a practical guide]({% post_url AI/2026-10-30-lora-fine-tuning-practical-guide %})
- [Fine-tuning pipeline regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [Fine-tuning data curation and eval set construction]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %})
- [Quantization: GGUF vs AWQ vs GPTQ, quality and latency]({% post_url AI/2026-10-28-quantization-gguf-vs-awq-vs-gptq-quality-latency %})
- [LoRA vs full fine-tuning: cost and quality for the enterprise]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %})
