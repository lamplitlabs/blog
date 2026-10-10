---
layout: post
title: "Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management"
date: 2026-10-05 00:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise apim governance dotnet performance enterprise-ai
author: manishtiwari25
description: "Put Azure API Management in front of Azure OpenAI to give every team its own token quota, a 429 instead of a starved deployment, and a chargeback report."
image:
  path: /assets/img/headers/ai/enterprise-ai-apim-token-quotas-chargeback.webp
  alt: "Diagram of several teams calling Azure OpenAI through an Azure API Management gateway that enforces per-team token limits and emits token metrics"
---

The second month an enterprise shares one Azure OpenAI deployment across teams, the same two tickets arrive. Finance: "the AI bill is one line item, who do I charge?" Engineering: "our copilot gets 429s every afternoon because another team's batch job eats the whole tokens-per-minute (TPM) budget." Both have the same fix: stop letting applications talk to the deployment directly and put **Azure API Management (APIM)** in front of it with its GenAI gateway policies. Each team gets a subscription key, a token quota and a line in a usage report. This post shows the configuration, the client change (almost none) and the report that ends the chargeback argument.

## Why not just one deployment per team?

You can create a `gpt-4o` deployment per team, each with its own TPM allocation. It works until you have eleven teams and the regional quota is split into eleven slices that are each too small for anyone's peak, while the sum sits idle most of the day. A gateway lets you keep **one or two large deployments** (pooled capacity, better utilisation) and apply the fairness rules in software:

| Concern | Deployment-per-team | APIM gateway |
|---|---|---|
| Fair share of TPM | Fixed slices, idle most of the day | Per-team limit, pooled capacity |
| Who pays | Infer from resource tags | Tokens per subscription, exact |
| Key rotation | Every team holds an Azure OpenAI key | Teams hold APIM keys; the model key never leaves the gateway |
| Add a team | New deployment, quota request | New APIM subscription, five minutes |
| Failover across regions | In every client | One `backend` pool policy |

The governance checklist from the [Enterprise AI governance post](/posts/enterprise-ai-governance-azure-openai/) already asked for "identity, not API keys" and "logging you own". The gateway is where both become enforceable rather than aspirational.

## Step 1: Import Azure OpenAI as an APIM API

In the APIM portal choose **APIs → Add API → Azure OpenAI Service**, pick the resource and the `2024-10-21` API version. APIM creates the operations (`chat/completions`, `embeddings`, ...) and, if you tick *Managed identity*, configures the backend to authenticate with the gateway's identity. Grant that identity `Cognitive Services OpenAI User` on the Azure OpenAI resource and then set `disableLocalAuth: true` on the resource: from now on the only path to the model is through the gateway.

Then create one **product** ("LLM access") and one **subscription per team**: `hr-copilot`, `support-assistant`, `eng-runbooks`, and so on. The subscription key is what the team puts in Key Vault.

## Step 2: Token limit per subscription

The `llm-token-limit` policy counts tokens, not requests. Requests are the wrong unit for LLM traffic: a 200-token FAQ answer and a 30,000-token document summary are the same "request". Put this in the API's inbound policy:

```xml
<policies>
  <inbound>
    <base />
    <llm-token-limit
        counter-key="@(context.Subscription.Id)"
        tokens-per-minute="2000000"
        estimate-prompt-tokens="true"
        remaining-tokens-header-name="x-llm-remaining-tokens"
        tokens-consumed-header-name="x-llm-consumed-tokens"
        retry-after-header-name="Retry-After" />
    <llm-emit-token-metric namespace="llm-usage">
      <dimension name="Subscription" value="@(context.Subscription.Name)" />
      <dimension name="Deployment"   value="@(context.Request.MatchedParameters["deployment-id"])" />
      <dimension name="Operation"    value="@(context.Operation.Id)" />
    </llm-emit-token-metric>
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
</policies>
```

Three things to note:

- `counter-key="@(context.Subscription.Id)"` makes the limit **per team**, not per gateway. One team exhausting its 2M TPM gets a `429` with `Retry-After`; the other teams do not notice.
- `estimate-prompt-tokens="true"` rejects a request *before* forwarding it when the estimated prompt alone would exceed the remaining budget, so a runaway batch job never reaches the deployment.
- `llm-emit-token-metric` writes prompt, completion and total tokens to Application Insights with the dimensions you choose. `Subscription` is the chargeback key.

If one team needs a different limit, override the policy at the **product** or **subscription** level, or compute it: `tokens-per-minute="@(context.Subscription.Name == "eng-runbooks" ? 4000000 : 1000000)"` works, though a named policy fragment per tier is easier to review.

## Step 3: Client change in .NET

The clients change exactly two settings: the endpoint becomes the gateway URL and the credential becomes the APIM subscription key. The SDK does not know or care that a gateway is in the middle.

```csharp
var client = new AzureOpenAIClient(
    new Uri("https://llm-gateway.contoso.com/openai"),
    new ApiKeyCredential(config["Llm:ApimSubscriptionKey"]!));

var chat = client.GetChatClient("gpt-4o");
```

Because the gateway can now return `429` with `Retry-After` on *your* quota (not the deployment's), keep the retry pattern from the [429 retry post](/posts/azure-openai-429-rate-limit-retry-dotnet/): honour the header, cap attempts, and surface "team quota exhausted" to the user differently from "model unavailable". The two response bodies are distinguishable: APIM's limit returns `"code": "TokenLimitExceeded"`.

A cheap addition that makes the feature self-service: log `x-llm-remaining-tokens` from each response. Teams see their own burn rate without asking the platform team for a dashboard.

## Step 4: The chargeback report

With `llm-emit-token-metric` running, the report finance wanted is one KQL query against the gateway's Application Insights:

```kusto
customMetrics
| where name in ("Prompt Tokens", "Completion Tokens")
| where timestamp > ago(30d)
| extend Team = tostring(customDimensions["Subscription"])
| summarize Tokens = sum(valueSum) by Team, name
| evaluate pivot(name, sum(Tokens))
| extend CostUsd = round(["Prompt Tokens"] / 1e6 * 2.50 + ["Completion Tokens"] / 1e6 * 10.00, 2)
| order by CostUsd desc
```

The prices are the `gpt-4o` global-standard list prices at the time of writing; keep them in a lookup table rather than the query if you run several models. Join on the `tokens-per-minute` you configured and you also get "percent of quota used", which is what the eng-runbooks team sees when they ask why they were throttled:

![Azure Monitor table of prompt tokens, completion tokens, cost and quota used per team subscription, with eng-runbooks at 99 percent and throttled three times](/assets/img/posts/ai/enterprise-ai-apim-token-usage-per-team.webp){: width="1100" height="520" }

Pin this to a workbook, export it monthly, and the "one line item" ticket is closed for good. Cost per team also becomes a quality signal: if one team's completion tokens double without more users, a prompt changed, and the [observability traces](/posts/enterprise-llm-observability-opentelemetry-dotnet/) tell you which one.

## What the gateway buys you beyond quotas

Once every call passes through APIM the following are each a single policy, not eleven client changes:

- **Semantic caching** (`azure-openai-semantic-cache-lookup`) so repeated questions never reach the model; pairs well with prompt caching for the ones that do.
- **Load balancing and failover** across deployments in two regions with a weighted backend pool and circuit breaker, so a regional `429` storm degrades to higher latency instead of errors.
- **Prompt and response logging** to your own store with your redaction rule, satisfying the governance "logging you own" item without touching application code.
- **Content safety** via `llm-content-safety`, applied uniformly even to the team that forgot.

## Checklist

- [ ] One APIM API in front of Azure OpenAI; gateway authenticates with managed identity; `disableLocalAuth` on the model resource.
- [ ] One APIM subscription per team; subscription keys in each team's Key Vault.
- [ ] `llm-token-limit` keyed on `context.Subscription.Id` with `estimate-prompt-tokens="true"`.
- [ ] `llm-emit-token-metric` with a `Subscription` dimension; KQL chargeback query pinned to a workbook.
- [ ] Clients honour `Retry-After` and show "team quota exhausted" distinctly from model errors.
- [ ] Monthly review: quota per team vs. usage; raise limits for teams that are consistently throttled, lower for idle ones.

The hard part of enterprise AI is rarely the model call. It is making a shared, expensive, rate-limited resource behave fairly for a dozen teams while being able to say who used what. A gateway with token-aware policies is the smallest piece of infrastructure that answers both questions.

## Related posts

- [Enterprise AI governance checklist for Azure OpenAI](/posts/enterprise-ai-governance-azure-openai/)
- [LLM observability with OpenTelemetry in .NET](/posts/enterprise-llm-observability-opentelemetry-dotnet/)
- [Handling Azure OpenAI 429s with retry in .NET](/posts/azure-openai-429-rate-limit-retry-dotnet/)
- [Azure OpenAI token cost: counting before you spend](/posts/azure-openai-token-counting-cost-dotnet/)
