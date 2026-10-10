---
layout: post
title: "Enterprise AI: Semantic Caching for Azure OpenAI with Azure API Management"
date: 2026-10-14 00:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise apim caching performance finops governance enterprise-ai
author: manishtiwari25
description: "Cut Azure OpenAI latency and token spend with APIM semantic cache policies: setup, threshold tuning on real traffic, and the gotchas."
image:
  path: /assets/img/headers/ai/enterprise-ai-apim-semantic-caching-azure-openai.webp
  alt: "Diagram of clients calling Azure API Management with a semantic cache backed by Redis Enterprise in front of an Azure OpenAI gpt-4o deployment"
---

Most enterprise chat workloads are repetitive. The help-desk bot answers "how do I reset my VPN token" a few hundred times a day, phrased a few hundred different ways. Every one of those calls goes to `gpt-4o`, waits almost two seconds and bills the same ~1,200 tokens. **Semantic caching** stores the answer the first time and serves it for every later question that *means* the same thing, without a model call. Azure API Management ships this as two policies, and if you already run [APIM in front of Azure OpenAI for quotas and chargeback](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/) it is a half-day change. This post walks through the setup, how to pick the similarity threshold, and what went wrong on the way.

{% include feed-ads.html %}

## How it works

1. APIM takes the incoming chat request and sends the prompt to a small **embeddings** deployment (`text-embedding-3-small`).
2. It looks the vector up in an **Azure Cache for Redis Enterprise** instance with the RediSearch module.
3. If a stored vector is closer than a configured **score threshold**, the cached completion is returned immediately. Otherwise the request goes to the chat deployment and the response is stored with the vector.

The model never sees a cache hit, so hits cost one embedding call (a fraction of a cent) instead of a full completion. Exact-match caching would catch almost nothing here; the point is that "VPN token reset" and "my RSA thing stopped working, how do I get a new one" land on the same answer.

## Prerequisites

- APIM in a tier that supports the Redis Enterprise external cache (Developer, Basic v2, Standard v2, Premium).
- An Azure Cache for Redis **Enterprise** instance with the **RediSearch** module enabled. Basic and Standard Redis do not have vector search; this is the step people miss.
- An Azure OpenAI embeddings deployment, imported into APIM as its own backend.
- The chat deployments imported as an API, ideally with the Azure OpenAI import wizard so the operations have proper schemas.

Wire the cache up in **APIM → External cache → Add**, choose the Redis Enterprise instance and the connection string from its Access keys. It takes a couple of minutes to show as *Connected*.

## The policies

Inbound, before the request reaches the backend:

```xml
<inbound>
  <base />
  <azure-openai-semantic-cache-lookup
      score-threshold="0.85"
      embeddings-backend-id="embeddings-backend"
      embeddings-backend-auth="system-assigned"
      ignore-system-messages="true"
      max-message-count="10">
    <vary-by>@(context.Subscription.Id)</vary-by>
  </azure-openai-semantic-cache-lookup>
</inbound>
```

Outbound, after the model answers:

```xml
<outbound>
  <base />
  <azure-openai-semantic-cache-store duration="3600" />
</outbound>
```

Three decisions are hiding in that snippet:

- **`vary-by` on the subscription.** Teams using the same gateway must not see each other's cached answers. HR's bot and Engineering's bot both get asked "what is our leave policy" and need different answers. Partitioning by subscription (or by a tenant header) is non-negotiable in a shared gateway.
- **`ignore-system-messages`.** The system prompt is the same for every call to a given bot, so including it in the embedding only pulls all vectors closer together and inflates hit rates. Turn it off when the system prompt is per-user (it carries retrieved documents, for example).
- **`max-message-count`.** Only the last N messages are embedded. For long conversations the early turns are rarely what decides the answer, and embedding a 20-turn history slows the lookup more than it helps.

The chat model deployment itself needs no change. Streaming responses are cached too, as of the 2024-05 APIM release, which was the blocker that stopped us the first time we tried this.

## Picking the threshold

`score-threshold` is cosine similarity. Too low and the cache answers the wrong question; too high and nothing hits. We replayed one week of the help-desk bot's logs (48,210 requests, exported from the [cost dashboard](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)) against four thresholds and had two support engineers review a 500-request sample of hits at each level for wrong answers.

![Table comparing one week of help-desk bot traffic before and after APIM semantic caching: model requests down 59 percent, p50 latency down 89 percent to 210 milliseconds, daily cost down 58 percent, plus a bar chart of cache hit ratio by score threshold with 0.85 chosen](/assets/img/posts/ai/enterprise-ai-apim-semantic-cache-results.webp){: width="1100" height="560" }

- **0.95**: 31% hits, zero wrong answers. Safe but leaves money on the table.
- **0.90**: 47% hits, zero wrong answers.
- **0.85**: 59% hits, zero wrong answers in the 500-sample review. This is where we landed.
- **0.80**: 66% hits, 7 wrong answers, including "reset my VPN token" served for "my VPN *certificate* expired". Not acceptable.

The right number is workload-specific. A bot answering from a narrow FAQ tolerates a lower threshold than a general assistant, because its questions genuinely cluster. Do the replay; do not copy 0.85.

## What moved

After a week in production at 0.85 against the week before:

| Metric | Before | After |
|---|---|---|
| Requests reaching `gpt-4o` | 48,210 | 19,850 |
| p50 latency | 1,840 ms | 210 ms |
| Tokens billed per day | 9.4M | 3.9M |
| Daily cost | $118 | $49 |

A cache hit costs one embedding call and a Redis lookup, about 40 ms of the 210 ms p50; the rest is APIM and network. The per-team cost rows in the Workbook dropped the same day, which is how Finance noticed before we told them.

## Gotchas

- **Cache invalidation is time-based only.** `duration="3600"` means a policy change in the knowledge base can be served stale for up to an hour. For FAQ content that changes weekly, an hour is fine. For anything regulatory, set it short or flush the Redis database when the source changes.
- **Temperature and tools are not part of the key.** Two requests with the same text but different `temperature` or `tools` share a cache entry. If the same subscription uses both, add those to `vary-by`.
- **RAG prompts hit far less.** When the user message carries retrieved chunks, two similar questions produce different embeddings because the chunks differ. Embed only the question (put the chunks in the system message and keep `ignore-system-messages`), or accept a lower hit rate.
- **Redis Enterprise is not free.** The smallest E10 SKU costs more than the embeddings calls. For a bot below roughly 5,000 requests a day the savings do not cover it; the latency win may still justify it.
- **Token quotas see fewer tokens.** The [token-limit policy](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/) only counts calls that reach the model, so cached answers are effectively free against a team's quota. That is what you want, but tell the teams, or they will not understand why their usage graph fell off a cliff.

## Where this fits

Semantic caching is the third layer in the gateway story: quotas keep one team from starving the others, the dashboard shows who spent what, and the cache makes the repetitive 60% of traffic nearly free and five times faster. For calls that do reach the model, [prompt caching](/posts/azure-openai-prompt-caching-dotnet/) trims the long static prefix. Together they turned a $118-a-day bot into a $49-a-day bot that answers faster, with no change to the application code.

## Related posts

- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Azure OpenAI Prompt Caching in .NET: Cut Latency and Input Cost by Ordering Your Prompt Right](/posts/azure-openai-prompt-caching-dotnet/)
- [Enterprise AI: A Cost Observability Dashboard for Azure OpenAI with Log Analytics, KQL and Workbooks](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)
