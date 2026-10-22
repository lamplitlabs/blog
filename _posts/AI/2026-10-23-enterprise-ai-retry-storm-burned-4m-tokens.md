---
layout: post
title: "Enterprise AI: The Retry Storm That Burned 4.1M Tokens in 40 Minutes"
date: 2026-10-23 09:00:00 +0200
categories: ai enterprise-ai
tags: ai enterprise-ai azure-openai reliability rate-limiting sre dotnet
author: manishtiwari25
description: "A batch job retried a 429 in a tight loop and took down our shared Azure OpenAI gateway. The dashboard that caught it and the retry budget that stops it."
image:
  path: /assets/img/headers/ai/enterprise-ai-retry-storm-429.webp
  alt: "Header card for the Enterprise AI retry storm post titled One Missing Retry Budget Burned 4.1 Million Tokens in 40 Minutes, with badges reading 429 spike eleven thousand two hundred per minute, retry budget three per client, and storm over in fifty five seconds, above a red sparkline of throttled requests"
---

Every team sharing one Azure OpenAI quota is one badly written retry loop away from a collective outage. We lived that sentence on a Tuesday afternoon: a batch scoring job hit a single `429 Too Many Requests`, retried immediately in a tight `while` loop, and within ten minutes was firing eleven thousand requests per minute at a gateway that serves four product teams. Every other team's traffic collapsed into the same 429 wall. The dashboard below is what our on-call engineer saw at 17:04.

![Operations dashboard screenshot for the contoso-llm-gateway showing a six hour line chart where red 429 throttled requests spike sharply to eleven thousand two hundred per minute around 16:50 while blue successful requests stay flat near eight thousand, a side table naming batch-scorer as the top throttled client with eight thousand four hundred twelve rejected calls, and counters reading thirty eight percent throttled and four point one million billed-but-rejected tokens](/assets/img/posts/ai/enterprise-ai-retry-storm-429-dashboard.webp){: width="1100" height="760" }

*The retry-storm dashboard: red 429s spike at 16:50 while successful calls stay flat. The right-hand table identifies `batch-scorer` as the source - 8,412 throttled calls in one hour, with no retry budget and no `Retry-After` handling.*

## What actually happened

The timeline, reconstructed from gateway logs:

- **16:47** - the nightly `batch-scorer` job starts early (a scheduler change had shipped that morning) and begins scoring 40,000 support tickets against `gpt-4o`.
- **16:49** - the deployment hits its tokens-per-minute ceiling. Azure OpenAI returns `429` with `Retry-After: 22` and a `x-ratelimit-remaining-tokens` header of zero.
- **16:50** - the client code, which predates our SDK guidelines, treats 429 like any other `HttpRequestException`: catch, wait zero milliseconds, retry, forever. Each retry consumes gateway capacity to receive and reject, and - the part finance cared about - each rejected request's prompt tokens are still counted by the gateway's metering pipeline before the rejection, because metering ran upstream of the throttle decision.
- **16:50-17:05** - red line on the dashboard. `teams-copilot`, `support-bot` and the evaluation harness all share the same gateway subscription; their legitimate traffic is now throttled at 38 percent. Users see "the assistant is busy" spinners.
- **17:04** - the alert in the screenshot fires: `429 rate (5 min) > 2%`, paging whoever holds the pager. In this case, 38.4 percent.
- **17:06** - on-call kills the `batch-scorer` pod. The red line collapses within one scrape interval.

Total damage: **4.1 million prompt tokens billed against requests that were never served**, 15 minutes of degraded service for three product surfaces, and one very sheepish data team.

## Why the existing guardrails did not catch it

We were not naive going in. The gateway already had [client-side rate limiting with polite retry handling](/posts/enterprise-ai-client-side-rate-limiting-azure-openai-429-storms/) in the shared .NET client, [per-team token quotas at APIM](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/), and [audit logging on every call](/posts/enterprise-ai-llm-gateway-audit-logging-policy-controls/). All three worked exactly as designed - and none of them fired:

- The shared client was bypassed. `batch-scorer` is a Python job written before the .NET client existed, calling the REST endpoint with `httpx` and a hand-rolled retry.
- APIM quotas are per **team**, and `batch-scorer` was inside its team's quota - the team quota was large, and the job simply consumed all of it in the tightest possible loop, starving the shared *deployment-level* TPM that Azure OpenAI enforces below APIM.
- Audit logging recorded everything, faithfully, after the fact. Logs describe the fire; they do not put it out.

The gap was not any of those controls. The gap was that **nothing limited how fast a single client was allowed to fail**. Success is rate-limited everywhere; failure was free.

## The fix: a retry budget per client

The control we added is a **retry budget**, borrowed from the gRPC and service-mesh world and applied at the gateway: each client may retry a failed request at most **3 times**, and no more than **20 percent of its requests in a 5-minute window may be retries**. Cross either line and the gateway returns `429` with `Retry-After: 60` *before* forwarding, plus a `x-retry-budget-exceeded: true` header so the client can tell "the model is busy" apart from "you are the problem".

Our gateway is a YARP-based .NET service, so the budget is a middleware that sits in front of the rate limiter:

```csharp
public sealed class RetryBudgetMiddleware
{
    private static readonly TimeSpan Window = TimeSpan.FromMinutes(5);
    private const double MaxRetryFraction = 0.20;
    private const int MaxRetriesPerRequest = 3;

    public async Task InvokeAsync(HttpContext ctx, IRetryBudgetStore store, RequestDelegate next)
    {
        var client = ctx.Request.Headers["x-client-id"].ToString();
        var attempt = int.TryParse(ctx.Request.Headers["x-retry-attempt"], out var a) ? a : 0;

        var stats = await store.GetAsync(client, Window);
        if (attempt > MaxRetriesPerRequest ||
            (stats.Total > 50 && (double)stats.Retries / stats.Total > MaxRetryFraction))
        {
            ctx.Response.StatusCode = StatusCodes.Status429TooManyRequests;
            ctx.Response.Headers.RetryAfter = "60";
            ctx.Response.Headers["x-retry-budget-exceeded"] = "true";
            return; // never reaches Azure OpenAI, never bills a token
        }

        await store.RecordAsync(client, isRetry: attempt > 0, Window);
        await next(ctx);
    }
}
```

The `x-retry-attempt` header is set by every client wrapper we ship (the .NET Polly policy, the Python `tenacity` decorator, and the APIM inbound policy for clients that go through neither). A client that omits the header gets `attempt = 0` - which is why the budget alone is not enough; see the enforcement note below.

Three properties make this work where quotas did not:

1. **It is cheap to reject.** The budget check is a Redis lookup and a counter increment, single-digit microseconds. Rejecting a storm costs nothing and bills nothing, because the request never leaves the gateway.
2. **It punishes failure, not success.** A healthy client doing 10,000 successful requests is untouched. A client whose requests all fail gets throttled after roughly its first 50, regardless of how big its team's quota is.
3. **It degrades gracefully.** Redis down = budget check open-circuits to *allow*, because a broken guardrail must not become the outage. We alert on the open circuit instead.

## What the dashboard does differently now

The screenshot's bottom-right counter - `retry-budget alerts: 1 firing` - did not exist before this incident. The dashboard now shows, per client: retry fraction, budget burn-down, and a red row the moment a client crosses 20 percent. The alert that pages is no longer the global 429 rate (too late - users already feel it) but **any single client exceeding 10 percent retry fraction for two minutes** (early - the storm is still one client's problem). The night after we deployed, the same `batch-scorer` job - now wrapped in the Python client with proper `Retry-After` handling - crossed 10 percent for 90 seconds while the deployment warmed up, the budget capped it at 3 attempts, and the storm the screenshot shows simply never formed. Fifty-five seconds from threshold to quiet.

## The enforcement note

A header a client can omit is a suggestion. Two weeks after the middleware went live we made `x-client-id` mandatory at the gateway (requests without it get `401`) and added the retry-attempt header to all three sanctioned client paths, so "forgetting" the header means "your request does not run". The one-off scripts that used to call the endpoint directly now fail closed in staging, which is exactly where that lesson should be learned.

## Takeaways

- **Rate-limit failure, not just success.** Every mature system we audited limited throughput; none limited how fast a client was allowed to be wrong.
- **Metering order matters.** We moved token metering downstream of the throttle decision, so rejected requests no longer bill. Check where your provider counts.
- **Shared quota is a shared fate.** Per-team quotas did not protect the deployment-level TPM. Budgets enforce blast radius; quotas only enforce bill size.
- **Alerts should point at a client, not a symptom.** "Global 429 rate high" started a hunt; "batch-scorer retry fraction 92%" ended it.

## Related reading

- [Enterprise AI: Client-Side Rate Limiting for Azure OpenAI - Surviving 429 Storms in .NET](/posts/enterprise-ai-client-side-rate-limiting-azure-openai-429-storms/)
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Enterprise AI: Audit Logging and Policy Controls for an LLM Gateway](/posts/enterprise-ai-llm-gateway-audit-logging-policy-controls/)
- [Azure OpenAI Token Counting and Cost Control in .NET](/posts/azure-openai-token-counting-cost-dotnet/)
