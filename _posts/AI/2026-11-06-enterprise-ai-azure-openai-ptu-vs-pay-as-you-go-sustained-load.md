---
layout: post
title: "Enterprise AI: Azure OpenAI Provisioned Throughput (PTU) vs Pay-as-you-go - Cost and Latency Under Sustained Load"
date: 2026-11-06 08:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise enterprise-ai cost performance architecture apim
author: manishtiwari25
description: "One gpt-4o workload at 60 req/min 24x7 priced five ways: pay-as-you-go, hourly PTU, reserved PTU, PTU plus spillover and Batch. Monthly cost, p95 latency, 429s."
image:
  path: /assets/img/headers/ai/enterprise-ai-ptu-vs-payg-azure-openai.webp
  alt: "Two bar charts for one gpt-4o workload at 60 requests per minute around the clock: monthly cost of 13,600 dollars pay-as-you-go, 86,400 hourly PTU, 15,600 reserved PTU and 12,440 for 40 reserved PTU with pay-as-you-go spillover; p95 latency 4.8 seconds pay-as-you-go, 1.7 seconds PTU, 2.4 seconds PTU with spillover"
---

![Bar charts: monthly cost $13,600 pay-as-you-go, $86,400 hourly PTU, $15,600 reserved PTU, $12,440 PTU + spillover; p95 latency 4.8 s, 1.7 s, 2.4 s](/assets/img/headers/ai/enterprise-ai-ptu-vs-payg-azure-openai.webp){: width="1200" height="630" }

Every Azure OpenAI cost review I have sat in eventually reaches the same question: *"Should we just buy PTUs?"* The honest answer is "it depends on your utilisation curve", which is true and useless. This post replaces it with numbers from one real, sustained enterprise workload priced five different ways, plus the latency we actually measured at the gateway.

The headline: for a workload that runs around the clock, **hourly PTU is a trap, reserved PTU is roughly cost-neutral with pay-as-you-go but 3x faster at p95, and a small reserved PTU base with pay-as-you-go spillover was both the cheapest and fast enough**.

## The workload

A document-processing service for a back-office team. It is not spiky in the way a customer-facing chat bot is; it has a daytime hump and a night-time batch tail.

- Model: `gpt-4o` (Global deployment for pay-as-you-go, regional for PTU).
- Average **60 requests/min**, 24x7; business-hours peak **120 requests/min**.
- **1,100 input tokens** (system prompt + document chunk) and **250 output tokens** per request on average.
- Per month: about **2.59 M requests**, **2.85 B input tokens**, **648 M output tokens**.
- Latency SLO the team wanted: p95 under 3 s for the synchronous path.

About 30 % of the traffic (overnight re-indexing) does not need a synchronous answer at all, which matters for the last option.

## How PTU pricing actually works

Three things people get wrong, in the order they cost money:

1. **You pay for capacity, not tokens.** A PTU deployment bills per PTU per hour whether you send one token or saturate it. A deployment that is idle 60 % of the time still costs 100 %.
2. **Hourly and reserved are very different prices.** The hourly (on-demand) PTU rate is roughly **$2 per PTU per hour**; a one-month Azure reservation lands at roughly **$260 per PTU per month**, about 80 % cheaper for the same capacity. Hourly is for experiments, not for running a service.
3. **Sizing is per model and per deployment type.** Global and regional PTUs have different minimums (15 vs 50 for gpt-4o at the time of writing) and increments of 5. The capacity calculator in Azure AI Foundry takes your peak tokens per minute and request rate and returns a PTU count; you then round up to the increment.

For this workload the calculator said **55 PTU** for the 120 req/min peak (162 K tokens/min), which rounds to **60 PTU**. The *average* load needs about 30 PTU, so a 60-PTU deployment is 50 % utilised on average and about 38 % overnight.

Prices below are list prices for one region when we did the exercise; your enterprise agreement will differ, but the *ratios* are what matter.

## The five options, priced

![Table comparing five options for the same workload: pay-as-you-go $13,600 per month, $5.25 per 1K requests, p95 4.8 s, 0.6 % 429s; 60 PTU hourly $86,400, p95 1.7 s; 60 PTU monthly reservation $15,600, p95 1.7 s; 40 PTU reserved plus pay-as-you-go spillover $12,440, p95 2.4 s, 15 % spilled; pay-as-you-go plus Batch API for the 30 % async share $11,560](/assets/img/posts/ai/enterprise-ai-ptu-vs-payg-cost-latency-table.webp){: width="1200" height="700" }

### 1. Pay-as-you-go (Global Standard)

2.85 B input tokens at $2.50 per million plus 648 M output tokens at $10 per million is **about $13,600 per month**. No commitment, no idle waste. But the latency is whatever the shared pool gives you: **p50 1.9 s, p95 4.8 s** over our 14-day measurement window, and **0.6 % of peak-hour requests got a 429** even with a 1.8 M TPM quota, because quota is a ceiling, not a reservation. Fine for the SLO on a good day; not fine for a 3 s p95 target.

### 2. 60 PTU, hourly

60 PTU x 730 hours x ~$2 is **about $86,400 per month** - over six times pay-as-you-go. Latency was excellent (**p50 1.1 s, p95 1.7 s**, zero 429s) because the capacity is yours. Nobody should run this past a pilot, yet I have seen it on two invoices because "we'll switch to a reservation later" and later never came. Put a budget alert on PTU deployments the day you create them.

### 3. 60 PTU, one-month reservation

Same capacity, same latency, **about $15,600 per month**. Only 15 % more than pay-as-you-go for a 2.8x better p95 and no 429s. The cost you are really paying for is the 62 % idle capacity overnight. If your latency SLO is strict and the workload is this steady, this is the simplest correct answer.

### 4. 40 PTU reserved + pay-as-you-go spillover

Size the reservation for the *average*, not the peak: 40 PTU at ~$260 is **$10,400**, and let APIM retry on the pay-as-you-go deployment when the PTU deployment returns 429. Around **15 % of requests spilled** during the daytime hump, costing about **$2,040** in tokens, for a total of **about $12,440 per month** - the cheapest synchronous option and 9 % under plain pay-as-you-go. Latency: **p50 1.2 s, p95 2.4 s**. The p95 is worse than pure PTU because the spilled requests carry pay-as-you-go latency plus one retry, but it is inside the 3 s SLO.

The APIM side is one backend pool with the PTU deployment as priority 1 and the pay-as-you-go deployment as priority 2, retrying on `429` and `503`:

```xml
<backends>
  <backend id="ptu-gpt4o" priority="1" />
  <backend id="payg-gpt4o" priority="2" />
</backends>
<inbound>
  <set-backend-service backend-id="aoai-pool" />
</inbound>
<backend>
  <retry condition="@(context.Response.StatusCode == 429 || context.Response.StatusCode == 503)"
         count="1" interval="0" first-fast-retry="true">
    <forward-request buffer-request-body="true" />
  </retry>
</backend>
```

Two details cost us a week: the PTU deployment returns a `retry-after-ms` header that you should *not* honour for spillover (you want to fail over immediately, not wait), and `buffer-request-body="true"` is mandatory or the retry forwards an empty body.

### 5. Pay-as-you-go + Batch API for the async 30 %

The overnight re-indexing does not need an answer in seconds. Sending that 30 % through the Batch API at half price takes the pay-as-you-go bill from $13,600 to **about $11,560**, the cheapest overall - but the synchronous 70 % keeps its 4.8 s p95 and its 429s. Combine this with option 4 (PTU for sync, Batch for async) and you get roughly **$10,900** with the 2.4 s p95; that is where this team ended up.

## When PTU wins and when it does not

Rules of thumb that fell out of the numbers:

- **Utilisation above roughly 20-25 % of a reserved PTU deployment makes it cheaper per token than pay-as-you-go** for gpt-4o at these prices. Below that, you are paying for air.
- **Never size PTU for peak if the peak is less than a third of the day.** Size for the base, spill the rest.
- **Hourly PTU is only for measuring**: run it for two days to get real latency numbers, then reserve or stop.
- **PTU buys latency predictability more than it buys savings.** If nobody has a p95 target, you probably do not need it yet.
- **Reservations are per region and per model family.** A gpt-4o reservation does not cover the gpt-4o-mini deployment you added next quarter - check the reservation scope before assuming you are covered.

## Measuring it yourself

Do not take the table above as your numbers. The three inputs that change the answer are your utilisation curve, your token mix and your negotiated prices, and all three are measurable:

1. Pull `PromptTokens`/`CompletionTokens` per minute from the Azure OpenAI metrics (or the APIM `llm-emit-token-metric` policy) for 14 days; the ratio of the 95th-percentile minute to the mean minute is your idle-waste factor.
2. Run the calculator with the peak and with the mean; the gap is the spillover share.
3. Multiply by the per-PTU reservation price from your agreement, not from the public page.

That is a one-page spreadsheet, and it ends the "should we buy PTUs" meeting in ten minutes.

## Related posts

- [Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed](/posts/enterprise-ai-model-routing-azure-openai-apim/)
- [Enterprise AI: A Cost Observability Dashboard for Azure OpenAI with Log Analytics, KQL and Workbooks](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Azure OpenAI Batch API in .NET: Process Thousands of Prompts at Half the Price](/posts/azure-openai-batch-api-dotnet/)
- [Handling 429 Rate Limits from Azure OpenAI in .NET: Backoff That Actually Works](/posts/azure-openai-429-rate-limit-retry-dotnet/)
