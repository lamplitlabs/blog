---
layout: post
title: "Enterprise AI: Self-Hosted Llama 3.1 70B on vLLM vs Azure OpenAI - Cost and Latency at 1.4 B Tokens a Month"
date: 2026-11-14 08:00:00 +0200
categories: ai
tags: ai azure openai enterprise enterprise-ai cost performance architecture vllm llama self-hosted gpu
author: manishtiwari25
description: "A 1.4 B token a month enterprise workload priced as Azure OpenAI gpt-4o-mini and as self-hosted Llama 3.1 70B on vLLM: cost, p95 per GPU load, break-even."
image:
  path: /assets/img/headers/ai/enterprise-ai-self-hosted-llm-vs-azure-openai-cost-latency.webp
  alt: "Two bar charts for one 1.4 billion token per month workload: monthly cost of 1,092 dollars for Azure OpenAI gpt-4o-mini, 5,376 for two pay-as-you-go A100 VMs, 3,387 reserved, 10,161 for a three-node HA cluster; p95 latency 2.9 seconds Azure OpenAI, 1.6 seconds self-hosted at 40 percent GPU utilisation, 4.7 seconds at 85 percent, 11.2 seconds at 95 percent"
---

![Bar charts: monthly cost $1,092 Azure OpenAI gpt-4o-mini, $5,376 self-hosted pay-as-you-go VMs, $3,387 reserved, $10,161 three-node HA; p95 latency 2.9 s, 1.6 s, 4.7 s, 11.2 s](/assets/img/headers/ai/enterprise-ai-self-hosted-llm-vs-azure-openai-cost-latency.webp){: width="1200" height="630" }

The second most common question in an enterprise AI architecture review, right after [PTU or pay-as-you-go]({% post_url AI/2026-11-06-enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load %}), is *"why don't we just run an open model ourselves?"* The pitch is usually data residency, no per-token bill, and no dependency on a vendor's rate limits. The counter is usually "GPUs are expensive". Both sides tend to argue without a spreadsheet.

This post is the spreadsheet, plus a load test. One real internal workload, priced as a managed API and as a self-hosted deployment, with the latency we measured at each GPU utilisation level. The headline: **at 1.4 B tokens a month the managed API is 3 to 9 times cheaper, and the self-hosted option only wins on latency while the GPUs sit mostly idle.** Self-hosting becomes rational for a different reason than cost, and the break-even is far higher than most teams guess.

## The workload

The same back-office document-processing service from the PTU post, one quarter later, after the team moved the bulk of the traffic from `gpt-4o` to `gpt-4o-mini` with the [cheap-model-first routing]({% post_url AI/2026-10-15-enterprise-ai-model-routing-azure-openai-apim %}).

- Average **60 requests/min**, 24x7; business-hours peak **9 req/s** (540/min).
- **800 input tokens** and **200 output tokens** per request on average, measured with the token counter from the [token counting post]({% post_url AI/2026-09-29-azure-openai-token-counting-cost-dotnet %}).
- Per month: about **2.6 M requests**, **1.12 B input tokens**, **0.28 B output tokens**, 1.4 B total.
- Latency SLO: **p95 under 3 s** for the synchronous path.
- Quality bar: the team's 400-item golden set; `gpt-4o-mini` scores 0.91 on it, `Llama-3.1-70B-Instruct` 0.90, `Llama-3.1-8B-Instruct` 0.79. The 8B model fails the bar, so the realistic self-hosted candidate is the 70B.

## Option A: Azure OpenAI gpt-4o-mini, pay-as-you-go

Global Standard list price at the time of writing: **$0.15 per 1 M input tokens, $0.60 per 1 M output tokens**.

- Input: 1,120 M x $0.15 / 1 M = **$168**
- Output: 280 M x $0.60 / 1 M = **$168**
- APIM Standard v2 gateway in front (quotas, audit, chargeback): **$756**

Total: **$1,092 per month**, of which 69 % is the gateway and not the model. Measured over five minutes at 32 and 64 concurrent clients through the gateway: **p50 1.9 s, p95 2.9 s, p99 3.8 s**, zero 429s at this deployment's 2 M TPM quota.

## Option B: Llama 3.1 70B on vLLM, self-hosted in Azure

The smallest configuration that fits a 70B model with a usable context is two 80 GB A100s with FP8 weights. In Azure that is one `Standard_NC48ads_A100_v4` (2x A100 80 GB, 48 vCPU, 440 GB RAM), or two `NC24ads` nodes; we used the single 2-GPU VM so tensor parallelism stays on NVLink.

```bash
python -m vllm.entrypoints.openai.api_server \
  --model meta-llama/Llama-3.1-70B-Instruct \
  --tensor-parallel-size 2 \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.92 \
  --max-num-seqs 256 \
  --enable-prefix-caching \
  --quantization fp8
```

vLLM 0.6.3, CUDA 12.4, Ubuntu 22.04 HPC image. The `--enable-prefix-caching` flag matters: the 800-token prompt shares a ~350-token system prefix across all requests, and prefix caching took prefill time for that part to near zero.

Pricing (East US 2, Linux, at the time of writing):

| Configuration | Hourly | Monthly (730 h) |
|---|---|---|
| 1x NC48ads A100 v4, pay-as-you-go | $7.35 | **$5,366** + $10 disk = $5,376 |
| 1x NC48ads A100 v4, 1-year reserved | $4.63 | **$3,380** + $7 = $3,387 |
| 3x NC48ads A100 v4, 1-year reserved (HA across zones, N+1) | $13.89 | **$10,139** + $22 = $10,161 |

No gateway cost is added here because the same APIM instance would sit in front of both; add the $756 back if you want like-for-like totals, which only widens the gap.

The three-node row is the one that reflects what "production" means in an enterprise. One VM is one availability zone, one driver update, one `nvidia-smi` hang away from an outage. A rolling model upgrade needs a spare node. Two nodes plus one spare is the minimum an SRE team will sign.

## Latency: it depends entirely on how busy the GPUs are

This is the part the spreadsheet cannot tell you. A managed API gives you roughly flat latency regardless of your load because you are a small fraction of a huge pool. A self-hosted node gives you excellent latency when idle and terrible latency as it saturates, with a cliff instead of a slope.

![Terminal output of llmbench against the vLLM node: at 8 concurrent clients 3.9 req/s, 38 % GPU, p95 1.58 s; at 16 clients 7.1 req/s, 61 %, p95 2.33 s; at 32 clients 10.4 req/s, 85 %, p95 4.68 s; at 48 clients 11.2 req/s, 95 %, p95 11.2 s; at 64 clients 11.3 req/s, p95 19.6 s with 41 timeouts; then Azure OpenAI gpt-4o-mini at 32 and 64 clients with p95 2.9 and 3.1 s](/assets/img/posts/ai/enterprise-ai-self-hosted-vllm-llmbench-output.webp){: width="1200" height="720" }

| Concurrency | req/s | Output tok/s | GPU util | p50 | p95 | p99 |
|---|---|---|---|---|---|---|
| 8 | 3.9 | 782 | 38 % | 1.21 s | **1.58 s** | 1.84 s |
| 16 | 7.1 | 1,418 | 61 % | 1.62 s | 2.33 s | 2.71 s |
| 32 | 10.4 | 2,088 | 85 % | 3.05 s | **4.68 s** | 5.52 s |
| 48 | 11.2 | 2,236 | 95 % | 7.40 s | **11.2 s** | 14.9 s |
| 64 | 11.3 | 2,260 | 96 % | 12.8 s | 19.6 s | 26.1 s (41 timeouts) |

Three things to read off that table:

1. **One 2x A100 node saturates at about 11 req/s, or 2,200 output tokens per second.** That is roughly 5.7 B output tokens a month at 100 % utilisation, 20x our 0.28 B output tokens. The workload needs about **17 % of one node on average**.
2. **The business-hours peak of 9 req/s puts the node at ~80 % utilisation, where p95 is 4.1 s, over the 3 s SLO.** To hold the SLO at peak, the node has to stay under ~65 %, which means the "one node" option is really "one node that is 83 % idle on average".
3. **Past 90 % vLLM queues rather than fails**, so latency balloons instead of returning 429s. If the client does not set its own timeout, requests pile up. Azure OpenAI's behaviour at quota is the opposite: a fast 429 you can [back off from]({% post_url AI/2026-09-29-azure-openai-429-rate-limit-retry-dotnet %}).

## Where the break-even actually is

Per-token cost on the self-hosted side is simply the monthly bill divided by the tokens you push through it, so the honest comparison is at the volume where a node is well used but still inside the SLO. Taking **65 % average utilisation** as the ceiling that keeps p95 under 3 s:

| | Azure OpenAI gpt-4o-mini | 1 node reserved @ 65 % | 3 nodes reserved @ 65 % |
|---|---|---|---|
| Tokens/month it can serve | unbounded (quota) | ~18.5 B total (3.7 B out) | ~55 B total (11 B out) |
| Cost at our 1.4 B tokens | **$336** (model only) | $3,387 | $10,161 |
| Blended cost per 1 M tokens at capacity | $0.24 | **$0.18** | $0.18 |
| Break-even volume vs gpt-4o-mini | - | **~14 B tokens/month** | ~42 B tokens/month |

So the single-node self-hosted deployment breaks even with `gpt-4o-mini` at about **14 B tokens a month, ten times this workload**, and only if you actually run the node at 65 % around the clock, which a daytime-heavy workload does not. The three-node HA cluster breaks even at ~42 B tokens a month, 30x. Against `gpt-4o` ($2.50 / $10 per 1 M) the break-even drops to roughly 1.1 B tokens a month, which is why the 70B self-hosted option looks attractive in decks that compare it to the flagship model and not to the model the workload actually needs.

Two costs are deliberately left out of the self-hosted column, and both push it further up:

- **People.** Someone owns the CUDA driver, the vLLM upgrade, the model weights, the GPU quota request, and the 3 a.m. page. Half an engineer at a loaded cost of $90k is $3,750 a month, more than the node.
- **Evaluation and safety.** The managed service ships content filtering, abuse monitoring and a model that is already evaluated. On the self-hosted side the [content filter]({% post_url AI/2026-10-02-azure-openai-content-filter-dotnet %}) is yours to build or buy.

## When self-hosting is still the right call

The numbers above make self-hosting look like a mistake for this workload, and for this workload it is. It is the right call when one of these is true, and cost is not on the list:

- **Hard data-residency or air-gap requirements** that the managed service's region list or data-handling terms cannot meet. This is the single most common legitimate reason, and it is a compliance decision, not a finance one.
- **Volume above the break-even**, roughly 15 B tokens a month per node pair with a flat 24x7 profile. A handful of enterprise workloads (log summarisation, document classification over a data lake) genuinely look like this.
- **A fine-tuned model the managed service does not host**, or a latency floor the managed service cannot hit. At 38 % utilisation the node's p95 of 1.58 s is nearly half of gpt-4o-mini's 2.9 s, and some interactive products need that.
- **Predictable spend in a fixed budget line.** Some finance teams prefer $3,387 every month to a $300 to $900 bill that moves with usage, even when the moving one is smaller.

## What we recommended

Stay on Azure OpenAI `gpt-4o-mini` behind APIM for this service, keep the cost dashboard from the [cost observability post]({% post_url AI/2026-10-13-enterprise-ai-azure-openai-cost-observability-dashboard %}) on the team's wall, and revisit when monthly volume crosses 10 B tokens or a residency requirement arrives. Keep the `vllm` deployment script in the repo; the load test cost $62 of GPU time and that is a cheap way to make the next review a measurement instead of a debate.

## Related

- [Enterprise AI: Azure OpenAI Provisioned Throughput (PTU) vs Pay-as-you-go - Cost and Latency Under Sustained Load](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/) - the same workload a quarter earlier, priced across the managed-service options.
- [Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed](/posts/enterprise-ai-model-routing-azure-openai-apim/) - how the workload got from gpt-4o to gpt-4o-mini in the first place.
- [Enterprise AI: Cost and Latency SLOs for LLM Workloads - Burn-Rate Alerts for Azure OpenAI in Production](/posts/enterprise-ai-llm-cost-latency-slos-production/) - where the 3 s p95 target came from.
- [Counting Tokens and Controlling Azure OpenAI Cost in .NET](/posts/azure-openai-token-counting-cost-dotnet/) - how the 800/200 token averages were measured.
