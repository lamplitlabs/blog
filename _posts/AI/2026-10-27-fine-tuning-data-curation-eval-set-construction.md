---
title: "Fine-tuning data curation and eval-set construction for enterprise teams"
description: "The regression-gates post assumes a gate suite exists; this one builds it: PII scrub, MinHash dedup, risk-tier labels, and a frozen 400-prompt golden set."
date: 2026-10-27 21:40:00 +0530
categories: ai
tags: fine-tuning model-training evals data-quality enterprise-ai llm
image:
  path: /assets/img/headers/ai/fine-tuning-data-curation-eval-set-construction.webp
  alt: "Pipeline diagram of fine-tuning data curation: raw exports flow through PII scrub, dedup, and task labeling into a curated pool, then a stratified split carves off a frozen golden eval set."
---

The [regression-gates post]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) opens with a quiet assumption: that you already have a gate suite - a golden set of prompts with expected behaviors, scored on every candidate adapter. Most teams do not. They have a pile of exported tickets, a fine-tuning budget, and a vague plan to "eyeball a few outputs" after training. That is how a model that got worse ships to production: there was nothing standing between the trainer and the deploy button.

This post is the missing prequel: how to curate the training corpus and build the frozen eval set that the gates run against. It is the pipeline we run before any adapter training starts, and it feeds both the gates post and the [LoRA vs full fine-tuning comparison]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %}) - every eval score in that post came from a golden set built exactly this way.

## The pipeline at a glance

The curation pipeline has three stages between raw exports and anything a trainer touches: scrub, dedup, and label. Only after those does the split happen, and the split is the part everyone gets wrong.

![Pipeline diagram showing raw exports flowing through PII scrub, dedup, and task labeling into a curated training pool, then a stratified split carving off a frozen golden eval set that trainers never see](/assets/img/posts/ai/fine-tuning-data-curation-eval-set-construction.webp)

The ordering matters. Scrub before dedup, because PII-normalized records dedup better (two tickets that differ only in a customer name collapse into one). Label before split, because the split is stratified on the labels. And the split is last, because everything upstream of it is allowed to touch every record, while everything downstream is not.

## Stage 1: scrub - PII, secrets, and license screening

Enterprise exports are full of things that must never enter a training corpus: customer names, email addresses, API keys pasted into tickets, and - our favorite - a production connection string someone included "for context." We run three scrub passes:

1. **Pattern rules** for the mechanical cases: emails, phone numbers, IPv4/IPv6 addresses, AWS-style key IDs, JWTs, and `-----BEGIN ... PRIVATE KEY-----` blocks. These are replaced with typed placeholders (`<EMAIL>`, `<API_KEY>`), not deleted - the model should learn that a key belongs in that slot, just not a real one.
2. **An NER pass** for names and organizations that patterns miss. Every entity is checked against an allowlist of public names (product names, our own company) before replacement; anything not allowlisted becomes `<PERSON>` or `<ORG>`.
3. **A secrets scanner** (we use gitleaks with a custom ruleset) run over the full text as a backstop. In our last curation round it caught 41 records the first two passes missed - mostly Slack tokens with nonstandard prefixes.

Records that fail scrubbing hard (a full customer database dump pasted into a ticket, yes, really) are dropped entirely, not redacted. Roughly 2.3% of our raw exports die at this stage.

## Stage 2: dedup - near-duplicates are worse than exact ones

Exact duplicates are trivial (`sha256` of the normalized text). Near-duplicates are where corpora rot: the same ticket template filled in forty times with only the timestamps different teaches the model to parrot the template, and each copy counts as another "example" in your eval set if one leaks in.

We dedup with MinHash over 5-gram shingles at a Jaccard threshold of 0.85, tuned down from 0.9 after we found near-misses at 0.87 that were clearly the same conversation re-exported after an edit. One knob worth stating plainly: **dedup across train and eval together, not within each separately.** If two records are 0.9-similar and one lands in train while the other lands in eval, your eval is measuring memorization. Dedup the union, then split.

The numbers from our most recent round: 18,412 raw records in, 11,206 after scrub and dedup. A 39% reduction, and the corpus is strictly better for it - dedup deleted volume, not information.

## Stage 3: label - task, tenant, risk tier

Every surviving record gets three labels, because the split and the gates both consume them:

- **Task**: what the model is being asked to do. Ours are `summarize`, `classify`, `extract`, `draft-reply`, `code-explain`, and `policy-qa`. This is labeled by a strong frontier model with a constrained prompt, then spot-checked by a human on a 2% sample (our human-agreement rate with the labeler is 94%, good enough for stratification).
- **Tenant**: which product surface the record came from. You need this to detect "the adapter got better for tenant A's tickets and worse for tenant B's" before your customers do.
- **Risk tier**: `low` (formatting, summaries), `medium` (customer-facing drafts), `high` (policy answers, anything with numbers a customer will rely on). The high tier is where the gates post's strictest thresholds apply.

## The split: stratified, frozen, and hash-pinned

Now the part the gates depend on: carving the golden eval set out of the curated pool.

We take 400 records - 11,206 in the pool this round - stratified to roughly match the pool's distribution with deliberate overweighting of the high risk tier:

| Task | Low | Medium | High | Total |
| --- | ---: | ---: | ---: | ---: |
| summarize | 22 | 18 | 8 | 48 |
| classify | 30 | 16 | 6 | 52 |
| extract | 24 | 22 | 14 | 60 |
| draft-reply | 18 | 34 | 22 | 74 |
| code-explain | 26 | 20 | 10 | 56 |
| policy-qa | 12 | 38 | 60 | 110 |
| **Total** | **132** | **148** | **120** | **400** |

`policy-qa` is 18% of the pool but 27.5% of the golden set, because a policy hallucination costs us a customer escalation while a mediocre summary costs a shrug. Stratify by pain, not just frequency.

Three rules make the set a gate instead of a vibe:

1. **Frozen.** The golden set lives in its own repo directory with its own review process. Adding or editing a prompt requires a PR with two approvals, same as code. The set is versioned (`golden-v3`, currently) and every eval report names the version it ran against.
2. **Hash-pinned.** The training pipeline refuses to start if any training record has a normalized-text hash within the golden set's MinHash neighborhood. This is the mechanical enforcement of the leakage rule - not a policy document, a hard error in the trainer's preflight.
3. **Never shown to the trainer.** Not for few-shot examples, not for "just checking the format," not for a quick manual probe. The moment a golden prompt influences training, it stops measuring generalization. If you need a dev set for iteration, carve a third split - we keep a 200-prompt dev set for exactly this, drawn from the pool with the same stratification.

## What the golden set is not

A few traps we fell into so you do not have to:

- **It is not your production traffic replayed.** A raw replay is unstratified (90% low-risk volume), full of near-duplicates, and biased toward whatever your current model already handles. Curate, then sample.
- **It is not static.** `golden-v3` replaced `golden-v2` when we shipped a new task type; the version bumped, the changelog explained why, and historical scores against `v2` stay labeled `v2` forever. Never silently edit a set that old scores were measured against.
- **It is not a training-data reject pile.** Every golden prompt is a record that *passed* curation and could have trained the model. Eval sets built from "the weird leftovers" measure weirdness, not quality.

## Handing off to the gates

With the golden set frozen, the rest of the loop is exactly what the sister posts describe. The [regression-gates post]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) covers the CI workflow that scores every candidate adapter against this 400-prompt set and blocks deploys on a tier-aware threshold - the risk-tier labels above are the same tiers those gates use. And when you are choosing *how* to train the adapter that will face these gates, the [LoRA vs QLoRA vs full fine-tuning comparison]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %}) runs the cost, memory, and eval-score tradeoffs - on this very golden set, so the numbers are comparable.

The short version of the whole cluster: curate the corpus, freeze the eval set, gate every candidate, and only then argue about rank and learning rate. Teams that do it in the other order get a fast model that fails in ways nobody measured.

Related:
- [Model training and fine-tuning: turn the training loop into a pipeline with regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [LoRA vs QLoRA vs full fine-tuning: the GPU memory, cost, and eval-score tradeoffs]({% post_url AI/2026-10-27-lora-vs-full-fine-tuning-cost-quality-enterprise %})
- [RAG vs fine-tuning for the enterprise internal copilot]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %})
