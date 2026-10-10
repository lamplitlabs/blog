---
layout: post
title: "Enterprise AI: Vendor Lock-In and Exit Cost - Azure OpenAI Managed Endpoints vs a Self-Hosted Open-Weights Model"
date: 2026-11-22 08:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise enterprise-ai architecture cost self-hosted vllm llama risk finops
author: manishtiwari25
description: "What it actually costs to leave: a lock-in audit and a priced exit plan for one 1.4 B token a month workload on Azure OpenAI vs self-hosted Llama 3.1 70B."
image:
  path: /assets/img/headers/ai/enterprise-ai-azure-openai-vs-self-hosted-vendor-lock-in-exit-cost.webp
  alt: "Horizontal bar chart of three-year run cost plus one-time exit cost in thousands of dollars: Azure OpenAI gpt-4o-mini pay-as-you-go 39k run plus 41k exit, Azure OpenAI gpt-4o PTU with one-year reservation 312k plus 118k, self-hosted Llama 3.1 70B on reserved A100 122k plus 76k, self-hosted three-node HA cluster 366k plus 76k"
---

![Bar chart of 3-year run cost plus exit cost: Azure OpenAI gpt-4o-mini $39k + $41k, gpt-4o PTU $312k + $118k, self-hosted reserved A100 $122k + $76k, self-hosted 3-node HA $366k + $76k](/assets/img/headers/ai/enterprise-ai-azure-openai-vs-self-hosted-vendor-lock-in-exit-cost.webp){: width="1200" height="630" }

Every architecture review of a managed LLM endpoint eventually reaches the sentence *"but what if we need to leave?"*. It is usually said by the person arguing for self-hosting, and it is usually answered with a shrug, because nobody has priced the exit. The previous post in this series priced the [run cost of self-hosted Llama 3.1 70B against Azure OpenAI]({% post_url AI/2026-11-14-enterprise-ai-self-hosted-llm-vs-azure-openai-cost-latency %}) and the managed API won by 3 to 9 times. This post prices the other half of the decision: **what it costs to migrate off each option**, where the lock-in actually lives, and how much of it you can design away for a few weeks of work.

The short version: the lock-in is real but it is **not where people think**. The API shape is the cheapest thing to swap. Prompts, embeddings and reserved commitments are where the money goes, and two of those three bite the self-hosted option just as hard.

## The workload, again

Same back-office document-processing service as the last two posts: about 2.6 M requests and 1.4 B tokens a month, p95 target under 3 s, a 400-item golden set as the quality bar, a retrieval index of 2.1 M chunks. Four candidate platforms, priced per month from the previous posts and here extended to a three-year horizon:

| Option | Monthly run cost | 3-year run cost |
|---|---|---|
| A. Azure OpenAI `gpt-4o-mini`, pay-as-you-go, behind APIM | $1,092 | $39,312 |
| B. Azure OpenAI `gpt-4o`, 50 PTU, 1-year reservation | $8,660 | $311,760 |
| C. Self-hosted Llama 3.1 70B, 1x NC48ads A100 reserved 1-year | $3,387 | $121,932 |
| D. Self-hosted, 3-node HA cluster, reserved | $10,161 | $365,796 |

Run cost tells you nothing about lock-in. For that you need to count the touch points.

## Step 1: Audit the lock-in surface

We went through the service and listed every place where it depends on something the platform owns, then scored each 0 (portable today), 1 (config change), 2 (days of work), 3 (rewrite or re-baseline). Here is the result for the managed option and for the self-hosted option, with the mitigation that brings the score down.

![Table of 11 lock-in touch points scored 0 to 3 for Azure OpenAI and self-hosted vLLM with mitigation per row: API shape 1 vs 0, prompts tuned to one model 3 vs 2, embeddings and vector index 3 vs 3, content filter 2 vs 0, Entra ID auth 2 vs 0, rate limits 1 vs 0, observability 1 vs 1, fine-tuned weights 3 vs 0, PTU or reserved commitments 2 vs 2, GPU quota and drivers 0 vs 2, data residency contract 1 vs 0; totals 19 vs 10 out of 33](/assets/img/posts/ai/enterprise-ai-lock-in-surface-audit-matrix.webp){: width="1200" height="720" }

Three things stood out once it was written down:

1. **The API is a 1.** vLLM, Ollama, TGI and every serious hosted provider expose an OpenAI-compatible `/chat/completions`. Our .NET client needed a base URL, an auth header and the removal of the `api-version` query parameter. Half a day including the tests.
2. **Prompts and embeddings are the 3s on both sides.** The 14 production prompts were tuned against `gpt-4o-mini` over nine months; the first run of the golden set against Llama 3.1 70B with the unchanged prompts scored 0.84, not the 0.90 we got after tuning. The 2.1 M-chunk index uses `text-embedding-3-small` vectors, and **embeddings from one model are meaningless to another**: you re-embed everything or you keep paying the old vendor for queries. This is the single largest exit cost and it is identical in direction if you move from a self-hosted embedder to a managed one.
3. **Self-hosting swaps vendor lock-in for infrastructure lock-in.** GPU quota in a region, a pinned CUDA/driver/vLLM triple that took two weeks to make stable, and a reserved instance you cannot return. Lower total score, not zero.

## Step 2: Price the exit

For each option we wrote the migration plan to the *other* side (A/B to self-hosted, C/D to managed) and costed it with the team's loaded rate of $110 per engineer-hour, real cloud list prices, and the measured volumes. Numbers are one-time USD.

| Exit cost item | A. PAYG managed | B. PTU managed | C. Self-hosted single node | D. Self-hosted HA |
|---|---|---|---|---|
| Client/API adaptation (4 person-days) | $3,520 | $3,520 | $3,520 | $3,520 |
| Prompt re-tuning to 0.90 on golden set (3 engineers x 3 weeks) | $39,600 | $39,600 | $26,400 | $26,400 |
| Re-embed 2.1 M chunks (1.6 B tokens) | $2,100 compute | $2,100 compute | $320 API | $320 API |
| Re-index + dual-read validation (2 weeks) | $8,800 | $8,800 | $8,800 | $8,800 |
| Guardrails / content filter replacement | $13,200 | $13,200 | $0 | $0 |
| Auth and quota re-plumbing in APIM | $4,400 | $4,400 | $2,200 | $2,200 |
| Parallel run, both platforms live (2 months) | $6,774 | $17,320 | $2,184 | $2,184 |
| Unused reserved commitment write-off (mid-term) | $0 | $51,960 | $20,322 | $60,966 |
| New-platform stand-up (GPU quota, IaC, on-call runbook) | $26,400 | $26,400 | $0 | $0 |
| Shrink a 3-node cluster: decommission, data egress | $0 | $0 | $0 | $4,100 |
| **Total exit cost** | **$104,794** | **$167,300** | **$63,746** | **$108,490** |

Reading the table honestly:

- **Leaving the cheap managed option costs 2.7 years of its run cost.** That is the number the self-hosting advocate is pointing at, and it is correct. But it is a one-time $105k against a run-cost gap of $82k *per year* versus option C. The managed option still wins on three-year total (run + exit) at **$144k vs $186k**, and it wins by more if you never actually leave.
- **Reservations are the exit cost nobody budgets.** Half of option B's exit is the unused PTU reservation; a third of C's and more than half of D's is the unused VM reservation. Commitment length, not platform, is the lever. One-month PTU and pay-as-you-go GPUs cost 25 to 40 % more per month and cut the exit by $20k to $60k. Price both and let finance choose knowingly.
- **Prompt re-tuning dominates and it is symmetric.** Moving in either direction costs three weeks of three people. The only mitigation is the one we already recommended for [model routing]({% post_url AI/2026-10-15-enterprise-ai-model-routing-azure-openai-apim %}): keep the golden set in CI and run every prompt change against two models, so the second model never drifts more than one release behind.
- **The header chart uses rounded one-time exits of $41k, $118k, $76k, $76k** because it assumes the three mitigations in the next section are already in place, which removes the guardrail, auth and most of the prompt gap. The table above is the unmitigated number.

## Step 3: Buy down the lock-in before you need it

The audit gives you a to-do list that is far cheaper than the exit. We did these three in one sprint, about $22k of time, and they cut the unmitigated exit for option A from $105k to roughly $41k:

1. **Store raw chunk text next to every vector, and make re-embedding a batch job that already exists.** We wrote the job, ran it once against the self-hosted `bge-m3` on the vLLM node (11 hours, $62 of GPU) and kept the second index cold. The 3 for embeddings becomes a 1.
2. **Put every prompt behind the golden-set gate against two models.** The CI step runs the 400 items against `gpt-4o-mini` and against Llama 3.1 70B weekly and fails if either drops below 0.88. Keeping the second model within two points means the re-tuning line shrinks from three weeks to one.
3. **Own the gateway concerns.** Quotas, auth token exchange, token logging and the audit trail already live in APIM from the [quota and chargeback post]({% post_url AI/2026-10-05-enterprise-ai-apim-token-quotas-chargeback-azure-openai %}); we moved the content-filter decision behind the same policy so that swapping the backend does not change what the client sees. The 2s for auth and filtering become 1s.

Things we deliberately did **not** do: build a provider-abstraction layer over the SDK (the OpenAI-compatible surface already is that layer, and a homemade one is a maintenance tax), and avoid fine-tuning out of fear (if you fine-tune, prefer LoRA adapters on an open-weights model that you can export; a fine-tuned managed deployment is the one genuinely non-portable artifact).

## The decision we recorded

An ADR with four lines of numbers beats a debate. Ours says:

- Stay on **Azure OpenAI `gpt-4o-mini` pay-as-you-go** (option A). Three-year run + mitigated exit is **$80k**, lowest of the four.
- **No multi-year reservation** on either side until monthly volume is stable above 10 B tokens; the reservation savings are smaller than the exit they create.
- The three mitigations above are **done and tested**, and the self-hosted path is a tagged deployment that the quarterly review re-runs against the golden set. Lock-in is now measured as "$41k and three weeks", reviewed every quarter, rather than feared.

Lock-in is not a property of the vendor. It is a property of how many of your own artifacts only make sense against one model. Count them, price them, and the Azure OpenAI vs self-hosted argument mostly answers itself.

## Related

- [Enterprise AI: Self-Hosted Llama 3.1 70B on vLLM vs Azure OpenAI - Cost and Latency at 1.4 B Tokens a Month](/posts/enterprise-ai-self-hosted-llm-vs-azure-openai-cost-latency/) - the run-cost half of this decision.
- [Enterprise AI: Azure OpenAI Provisioned Throughput (PTU) vs Pay-as-you-go - Cost and Latency Under Sustained Load](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/) - where option B's monthly number comes from.
- [Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed](/posts/enterprise-ai-model-routing-azure-openai-apim/) - the golden-set gate that keeps a second model within reach.
- [Enterprise AI: Cost and Latency SLOs for LLM Workloads - Burn-Rate Alerts for Azure OpenAI in Production](/posts/enterprise-ai-llm-cost-latency-slos-production/) - the SLO that the parallel-run phase has to keep meeting.
