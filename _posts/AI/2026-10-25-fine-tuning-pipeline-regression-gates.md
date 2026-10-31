---
layout: post
title: "Model training and fine-tuning: turn the training loop into a pipeline with regression gates"
description: "Fine-tuning fails quietly through data contamination and silent regressions. A data manifest, frozen eval set and regression gates make each run reviewable."
date: 2026-10-25 14:06:00 +0000
categories: ai
tags: machine-learning fine-tuning ai sdlc python
image:
  path: /assets/img/headers/ai/fine-tuning-pipeline-regression-gates.webp
  alt: "A fine-tuning pipeline from data snapshot through training and evaluation to a canary gate, each stage emitting a hash or score"
pin: false
math: false
mermaid: false
---

A fine-tuning run is a build. It takes inputs (base weights, data, code, hyperparameters), produces an artifact (adapter or full weights), and that artifact ships to production. Yet most teams run training like a notebook experiment: data copied by hand, eval by eyeball, promotion by vibes. Then a regression ships and nobody can answer the only question that matters - *what changed?*

This is the pipeline shape we converged on for the models behind our own tooling at Lamplit Labs, including the classification and drafting loops in Pulse. None of it needs a platform team; it needs the same discipline a CI pipeline has, applied to a longer build.

![A fine-tuning pipeline with a manifest, frozen eval and regression gates](/assets/img/posts/ai/fine-tuning-pipeline-regression-gates.webp)

## Stage 1: snapshot the data, hash it, freeze it

Training data rots faster than code. Source systems change, labels get corrected, someone deletes duplicates and the row count moves. If your dataset is "whatever the query returned this morning," every run trains on a different model's worth of data and no two runs are comparable.

The fix is a data manifest: one file, checked in next to the training config, that lists the exact snapshot - query plus cut-off date, or a bucket path plus object version - and the SHA-256 of the materialised file. Training reads the snapshot the manifest names, not the live source. When someone asks why run 47 behaves differently from run 45, the answer is a `diff` of two manifests, not an archaeology project.

Contamination gets handled at this stage too: before the snapshot is written, the script removes any row whose text has a high overlap with anything in the eval set. That is not paranoia; near-duplicates are the normal state of scraped data, and a model that has memorised the test set produces a beautiful, meaningless score. Deduplication against the eval set is a *data* check, so it belongs where the data is built - not in a reviewer's head.

## Stage 2: the eval set is a secret you keep from yourself

An eval set you have ever used to pick a hyperparameter is no longer an eval set. It becomes training signal the moment you iterate against it, and each iteration overfits it a little more. The practical setup:

- **Two splits with different jobs.** A dev split for iteration - cheap, allowed to be consulted often - and a held-out split that only the pipeline touches, only at gate time. If a human has scrolled through the held-out split, it is a dev split now; make a new one.
- **Frozen and hashed.** The held-out split gets the same manifest treatment as training data. An eval score is only comparable across runs if the questions are identical; "we refreshed the benchmark" and "the model got worse" are indistinguishable without a hash.
- **Includes the failure modes you actually care about.** Aggregate accuracy hides the regressions users feel. We track per-slice scores: worst-case refusal rate, format compliance on the ten prompt shapes the product really sends, and latency at p95. A 1% aggregate win that doubles refusals on your most common slice is a regression wearing a metric's clothes.

## Stage 3: gate promotion on deltas, not absolutes

The gate question is never "is this model good?" - it is "is this model better than what is deployed, on the axes we promised, with no regression on the others?" That makes the gate a table of signed deltas with thresholds:

```text
slice                    current   candidate   delta    threshold   verdict
format-compliance        0.972     0.981       +0.009   >= -0.002   pass
refusal-rate (worst)     0.031     0.028       -0.003   <= +0.005   pass
latency p95 (ms)         412       489         +77      <= +50      FAIL
```

That run did not ship, and the aggregate quality score said it was the best model we had trained all month. The latency regression was real for users and invisible to the quality metric. A gate that cannot fail is a report, not a gate; one blocked run per month is what a working gate smells like.

The canary is the final stage because offline evals cannot see everything: route a few percent of traffic, compare the same slices live, and let the canary verdict feed back into the manifest as the run's recorded outcome. Promotion is now an event with an audit trail, not a deployment someone remembers.

## What this buys you

- **Reproducibility as a side effect.** Manifests for data and eval plus a pinned training image mean any run can be re-executed. When a model misbehaves in production, you can rebuild its exact ancestry instead of guessing.
- **Reviews that review something.** "PR for run 48: manifest diff, eval deltas, canary summary" is a five-minute review. "Here is a notebook" is not.
- **A supply chain you can defend.** Every stage emits a hash, which is exactly what the integrity checks in [the model supply chain post]({% post_url AI/2026-10-25-ai-security-model-supply-chain-attack-surface %}) verify downstream. The two pipelines are the same pipeline seen from two sides.

The meta-lesson is the one this blog keeps returning to: deterministic gates first, AI inside the fence. Training is the least deterministic thing most teams run - which is exactly why everything *around* it should be a script with a number at the end.

## Related posts

- [Fine-tuning data curation and eval-set construction for enterprise teams]({% post_url AI/2026-10-27-fine-tuning-data-curation-eval-set-construction %})
- [AI Security: the model supply chain is the attack surface you already deployed]({% post_url AI/2026-10-25-ai-security-model-supply-chain-attack-surface %})
- [Evaluating RAG retriever quality with a golden set in .NET]({% post_url AI/2026-09-30-evaluating-rag-retriever-golden-set-dotnet %})
- [AI SDLC for .NET Teams: a phase-by-phase guide]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [RAG vs fine-tuning for the enterprise internal copilot]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %})
