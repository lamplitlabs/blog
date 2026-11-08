---
layout: post
title: "Replay Data vs Catastrophic Forgetting, Measured: Mixing General Text into a Fine-Tune"
date: 2026-11-08 06:00:00 +0100
categories: ai
tags: [fine-tuning, model-training, catastrophic-forgetting, replay, evals, llama.cpp, gguf, llm, benchmark]
author: manishtiwari25
description: "Mixing 10-50% general text into a SmolLM2-135M fine-tune cut drift from the base model by 22-30%. Cutting the learning rate 10x cut it by 91%."
image:
  path: /assets/img/headers/ai/fine-tuning-replay-mix-forgetting.webp
  alt: "Header card titled Replay data vs forgetting, measured: SmolLM2-135M fine-tuned on this blog with llama.cpp, with 0 to 50% general text mixed in. Three bar charts after 2 epochs at lr 1e-5. Held-out posts perplexity: base 22.9, then 27.5, 27.7, 32.4 and 30.4 for 0, 10, 25 and 50% replay. General-text KL drift: 1.13, 0.88, 0.94, 0.80. HellaSwag accuracy: base 42.6, then 34.4, 37.2, 36.7, 37.7."
---

Our [fine-tuning evaluation post]({% post_url AI/2026-11-04-fine-tuning-evaluation-measured-llama-cpp %}) found that SmolLM2-135M, fully fine-tuned on this blog at `llama-finetune`'s default learning rate of 1e-5, forgot a lot of general English. Its perplexity on Wikipedia text more than tripled and HellaSwag fell 8 points. The usual fix is **replay**: mix some general text back into the training data so the model keeps practising what it already knew.

We measured how much replay helps. We kept the training budget at 400 KB and varied only the share of general text: 0%, 10%, 25% and 50%. Then we ran the same four checks as before on every checkpoint. The short answer: replay helped, but the learning rate mattered far more.

| Change (2 epochs, vs. lr 1e-5 with 0% replay) | Drift on general text (mean KL) | Held-out blog perplexity | HellaSwag |
|---|---|---|---|
| no change: lr 1e-5, 0% replay | 1.131 | 27.5 | 34.4% |
| add 10% replay | 0.884 (-22%) | 27.7 | 37.2% |
| add 50% replay | 0.796 (-30%) | 30.4 | 37.7% |
| lr 1e-6 instead, 0% replay | 0.104 (-91%) | 16.4 | 42.1% |
| lr 1e-6 and 25% replay | 0.099 (-91%) | 17.0 | 43.0% |
| *base model, untouched* | *0* | *22.9* | *42.6%* |

## Setup

- **Model:** HuggingFaceTB/SmolLM2-135M-Instruct. We converted it to an F32 GGUF with the numpy-only `scripts/finetune-eval/hf_to_gguf.py` from the earlier post.
- **Trainer:** `llama-finetune` (llama.cpp build 11669). This is a full fine-tune with AdamW, context 256 and batch 256 on Metal (`-ngl 99`) on an M2 Pro with 16 GB. We trained one epoch per run, starting the second epoch from the first epoch's checkpoint.
- **Task data:** this blog's posts, split by post with a hash. 163 posts are for training and 33 are held out. Each mix starts with the first part of the training posts.
- **Replay data:** 233 KB of English Wikinews, Wikivoyage and Wikibooks passages (the FLORES text behind Belebele). It is a *different* source from the general-text evaluation set, 240 Wikipedia paragraphs from XQuAD. A drop in drift therefore means the model kept general English, not that it had seen the test paragraphs.
- **Mixes:** `scripts/finetune-replay/build_mixes.py` cuts both streams into blocks of about 1,500 characters and interleaves them with a seeded draw. Every mix is 400 KB. The 0% mix is built the same way as the training file of the earlier post. Since then the blog's posts have changed by about 1 KB, and that small change alone moved the lr 1e-5 epoch-2 KL from the earlier post's 1.257 to 1.131 here. Keep that in mind for Result 2.
- **Checks:** `llama-perplexity -c 512` on 100 KB of training text, on the 33 held-out posts and on the general text, with `--kl-divergence` against the base model's logits. We also ran HellaSwag on 1,000 tasks.

![Four horizontal bars, one per training file, each 400 thousand characters long. The 0% replay file is all blue (this blog's posts). The 10%, 25% and 50% files show orange general-English replay blocks spread along the whole bar between blue blog blocks. A dashed line at 380 thousand characters marks the last 5%, which llama-finetune keeps as its validation split.](/assets/img/posts/ai/fine-tuning-replay-mix-layout.webp){: width="1400" height="520" }

## Result 1: replay cut drift by about a quarter

![Four line charts of epoch 1 and epoch 2 checkpoints against the replay share of 0, 10, 25 and 50%, at lr 1e-5. Blog text it trained on, perplexity after epoch 2: 8.1, 7.7, 9.3, 9.5 (base 28.1). Drift on general English, mean KL divergence: 1.131, 0.884, 0.936, 0.796. 33 held-out blog posts, perplexity: 27.5, 27.7, 32.4, 30.4 (base 22.9). HellaSwag accuracy: 34.4, 37.2, 36.7, 37.7 (base 42.6). Orange diamonds show the 25% mix trained again with its blocks shuffled into a different order: KL 0.884 and held-out perplexity 26.9.](/assets/img/posts/ai/fine-tuning-replay-mix-tradeoff.webp){: width="1400" height="1000" }

At lr 1e-5 the 0% mix ended epoch 2 with a mean KL divergence of 1.131 nats per token on general text. The model picked the same top token as the base model only 50.9% of the time. With 10% replay, KL fell to 0.884, and with 50% replay it fell to 0.796. That is a 22% to 30% reduction, with error bars of about ±0.007. The general-text perplexity tells the same story. The base model scores 16.5. The 0% mix ended at 47.1 and the 50% mix at 32.4, so the model is still twice as confused as the base.

![Terminal output of llama-perplexity with --kl-divergence on general text for two epoch-2 checkpoints. For mix00_lr1e-5_ep2.gguf (0% replay): Mean PPL(Q) 47.114419 against Mean PPL(base) 16.519535, ratio 2.852043, Mean KLD 1.130668, 99th percentile KLD 4.876587, Median KLD 0.885395, Same top p 50.917%. For mix50_lr1e-5_ep2.gguf (50% replay): Mean PPL(Q) 32.400900, ratio 1.961369, Mean KLD 0.795794, 99th percentile KLD 4.297515, Median KLD 0.569933, Same top p 56.966%.](/assets/img/posts/ai/fine-tuning-replay-kl-terminal.webp){: width="1400" height="769" }

HellaSwag moved in the right direction, from 34.4% with no replay to between 36.7% and 37.7% with replay. Its 95% intervals, however, overlap: 0% replay spans 31.5 to 37.4, and 50% replay spans 34.7 to 40.7. With 1,000 tasks, a 3-point change is a hint, not a result. None of the lr 1e-5 checkpoints got back into the base model's interval of 39.6 to 45.7.

Replay also cost very little on the task itself. Perplexity on the blog text the model trained on was 8.1 with 0% replay and 9.5 with 50%, even though the 50% mix contains half as much blog text.

## Result 2: the order of the blocks moved the result as much as the mix

`llama-finetune` gave byte-identical models for different `-s` seeds in our earlier runs, so it does not shuffle the data for you. The order of the file *is* the order of training. To see how much that matters, we rebuilt the 25% mix with the same blocks in a different order (`build_mixes.py --order-seed 1`) and trained it again.

| 25% replay, epoch 2 | KL on general text | Held-out PPL | HellaSwag |
|---|---|---|---|
| original order | 0.936 | 32.4 ± 0.5 | 36.7% |
| same blocks, reshuffled | 0.884 | 26.9 ± 0.5 | 37.4% |

The reshuffled run moved held-out perplexity by 5.5 points, far beyond the evaluation error bars. That is more than the whole gap between the 10% and 50% mixes. So the curve in Result 1 has noise from training order that the error bars do not show. The only effect we would trust from a single run per point is "any replay beats none on drift": every epoch-2 replay checkpoint, in both orders, landed between 0.80 and 0.94 against 1.13 for none. A ranking between 10%, 25% and 50% would need several orders per mix.

## Result 3: the learning rate did what replay could not

![Three bar charts of epoch-2 checkpoints, each labelled with its learning rate and replay share. Drift on general English, mean KL divergence: lr 1e-5 with 0, 10, 25 and 50% replay 1.131, 0.884, 0.936, 0.796; lr 1e-6 with 0 and 25% replay 0.104 and 0.099. Held-out blog posts perplexity (base 22.9): 27.5, 27.7, 32.4, 30.4, then 16.4 and 17.0. Blog text it trained on (base 28.1): 8.1, 7.7, 9.3, 9.5, then 10.2 and 10.9.](/assets/img/posts/ai/fine-tuning-replay-vs-learning-rate.webp){: width="1400" height="640" }

At lr 1e-6 with no replay, KL drift after two epochs was 0.104. That is 91% lower than at lr 1e-5, and the model agreed with the base model's top token 81.5% of the time. Held-out perplexity *improved* from the base model's 22.9 to 16.4, while every lr 1e-5 run made it worse. HellaSwag stayed at 42.1%. The price was a little memorisation: training-text perplexity was 10.2 instead of 8.1.

Adding 25% replay at lr 1e-6 still helped a little. KL fell from 0.104 to 0.099, general perplexity from 18.1 to 17.0 (base 16.5) and HellaSwag rose from 42.1% to 43.0%. Held-out perplexity rose slightly, from 16.4 to 17.0. Once the learning rate is right, replay polishes the result. When the learning rate is wrong, replay cannot rescue the run.

## A trap: the trainer's validation loss now measures something else

`llama-finetune` uses the last 5% of the training file as its validation split. With replay in the file, that tail is partly general English: 6% of it in the 10% mix and 48% in the 50% mix. The final validation losses for the lr 1e-5 runs (3.73, 3.68, 3.62, 3.60) therefore are not comparable across mixes. Each one is measured on a different blend of text. Keep a fixed validation file outside the training file, and score every checkpoint against it with `llama-perplexity`, as the checks above do.

## What we would do

1. **Sweep the learning rate first.** Score each run on held-out task text *and* KL drift on general text. In our runs a 10x lower learning rate cut drift by 91%, and no replay share got past 30%.
2. **Then add 10% to 25% replay from a source that is not your evaluation set.** It is cheap, because 10% replay did not hurt the task here. It also gives a small extra margin on general text.
3. **Shuffle the training file before every run, and train two orders before you trust a 2-point difference.** One run per setting showed a 5.5-point swing in held-out perplexity from block order alone.
4. **Gate on drift as well as task metrics.** For example, mean KL under 0.15 nats/token on general text and HellaSwag within the base model's 95% interval. Of the 14 fine-tuned checkpoints we measured, only the four lr 1e-6 ones pass both.

## Reproduce it

You need llama.cpp (`llama-finetune`, `llama-perplexity`), Python 3 with numpy and matplotlib, pyarrow for the corpus builder, and these Hugging Face hub files in the local cache: SmolLM2-135M-Instruct safetensors, XQuAD, HellaSwag, Winogrande and Belebele. The full set below took about 9 hours on a busy M2 Pro. One epoch takes 8 to 70 minutes, depending on host load.

```bash
# 1. F32 GGUF and the post-level split (same scripts as the evaluation post)
python3 scripts/finetune-eval/hf_to_gguf.py <SmolLM2-135M-Instruct snapshot> work/base.gguf
python3 scripts/finetune-eval/build_corpora.py work/corpus

# 2. 400 KB mixes with 0/10/25/50% replay, plus a reshuffled 25% mix
python3 scripts/finetune-replay/build_mixes.py work/corpus
python3 scripts/finetune-replay/build_mixes.py work/corpus --mixes 25 --order-seed 1

# 3. train 2 epochs per mix and run every check (resumable)
scripts/finetune-replay/run_mixes.sh work work/base.gguf
MIXES="25s1" scripts/finetune-replay/run_mixes.sh work work/base.gguf
MIXES="0 25" LR=1e-6 scripts/finetune-replay/run_mixes.sh work work/base.gguf

# 4. logs -> scripts/data/finetune-replay-smollm2-135m.json -> the charts above
python3 scripts/finetune-replay/summarise.py work
python3 scripts/finetune-replay/gen_post_images.py --work work
```

## Where Pulse fits

Pulse, Lamplit Labs' multi-project self-improving automation product, is coming soon. This post is the kind of experiment it is built to run without supervision: change one variable, hold the budget fixed, score against data the change cannot see, and repeat the run before believing a small difference. The 5.5-point swing from block order alone is why a single run should not promote a change. The [Pulse introduction]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) has more on what we are building.

## Related posts

- [Fine-tuning evaluation, measured: held-out perplexity, KL drift and benchmarks]({% post_url AI/2026-11-04-fine-tuning-evaluation-measured-llama-cpp %})
- [Fine-tuning data curation and eval set construction]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %})
- [Fine-tuning pipeline regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [LoRA fine-tuning: a practical guide]({% post_url AI/2026-10-30-lora-fine-tuning-practical-guide %})
- [LoRA vs full fine-tuning: cost and quality for the enterprise]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %})
