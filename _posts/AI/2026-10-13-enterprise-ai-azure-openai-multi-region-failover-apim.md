---
layout: post
title: "Enterprise AI: Multi-Region Failover for Azure OpenAI with APIM Backend Pools and Circuit Breakers"
date: 2026-10-13 06:30:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise enterprise-ai apim resilience failover architecture performance observability
author: manishtiwari25
description: "Fail Azure OpenAI traffic over between two regions with an APIM backend pool, circuit breaker and retries: the trace, the policy and game-day numbers."
image:
  path: /assets/img/headers/ai/enterprise-ai-azure-openai-multi-region-failover-apim.webp
  alt: "Four-step card: two Azure OpenAI deployments in two regions behind one APIM backend pool; circuit breaker trips on 429 and 5xx so the priority-2 region takes traffic; health probe closes the circuit and traffic returns; game day result of region pulled for 30 minutes with 0.3 percent errors and p95 up 410 ms"
---

![Four steps of the failover design: one APIM backend pool over two regional Azure OpenAI deployments, circuit breaker on 429 and 5xx, automatic return when the probe passes, and the game-day result](/assets/img/headers/ai/enterprise-ai-azure-openai-multi-region-failover-apim.webp){: width="1200" height="630" }

The [PTU vs pay-as-you-go post]({% post_url AI/2026-10-08-enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load %}) ended with an APIM backend pool that spills PTU overflow to a pay-as-you-go deployment in the same region. That handles *our* traffic growing. It does nothing when the *region* has a bad afternoon: a capacity incident in West Europe in September returned `429` with `Retry-After: 60` for eleven minutes to every deployment there, and our [retry-with-backoff client]({% post_url AI/2026-09-29-azure-openai-429-rate-limit-retry-dotnet %}) did exactly what it was told, which was to wait. Users saw a spinner for a minute and then an error.

This post is the design we run now: two deployments in two regions, one APIM backend pool, a circuit breaker that stops sending traffic to a region that is failing, and a game day that proved it. All numbers are from our gateway (about 6 700 requests in the 30-minute window), not a vendor slide.

## The design in one paragraph

Clients call one hostname, `llm-gateway.contoso.com/openai/...`, with the same request body they would send to Azure OpenAI. APIM owns the backend choice. A backend pool holds `aoai-westeurope` (priority 1, the PTU deployment we pay for anyway) and `aoai-swedencentral` (priority 2, pay-as-you-go, same model version). Each backend has a circuit breaker: five `429` or `5xx` responses in a 30-second window open the circuit for 60 seconds, during which the pool does not pick that backend at all. A `retry` policy re-selects from the pool when the first attempt returns `429` or `503`, so the request that *trips* the breaker still succeeds on the other region. When the circuit's trip period ends APIM lets a single request through; if it passes, the circuit closes and priority 1 takes traffic again.

Nothing in the client changes. The `x-aoai-region` response header tells it which region answered, which is the only thing the application team asked for.

## What a failover looks like in the trace

This is the APIM request trace from the game day, captured as the first region started returning `429`:

![APIM request trace: backend pool selects aoai-westeurope, gets 429 with Retry-After 12, circuit breaker records failure 5 of 5 and opens for 60 seconds, retry re-selects aoai-swedencentral which returns 200 in 1 218 ms, response headers mark x-aoai-failover true and a failover metric is emitted; pool state panel shows West Europe open and Sweden Central healthy serving 100 percent](/assets/img/posts/ai/enterprise-ai-azure-openai-multi-region-failover-apim-trace.webp){: width="1400" height="900" }

Four things to read off it:

1. The first attempt fails in **605 ms** (the `429` comes back fast; the region is refusing, not slow). The retry succeeds in 1 218 ms, so the user paid 1.8 s total instead of waiting out `Retry-After: 12`.
2. The breaker opens on **this** request (`failure 5/5`). The next requests do not even try West Europe, so they pay no failure latency.
3. The response carries `x-aoai-failover: true`. Our client logs it; the dashboard counts it. Silent failover is how you discover you have been paying pay-as-you-go prices for a week.
4. `emit-metric llm_failover_total` goes to Application Insights, which drives the alert in the next section.

## The policy

The backend pool and circuit breaker are defined on the backends, not in the API policy. Bicep for one regional backend:

```bicep
resource beWest 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = {
  parent: apim
  name: 'aoai-westeurope'
  properties: {
    url: 'https://aoai-weu-prod.openai.azure.com/openai'
    protocol: 'http'
    circuitBreaker: {
      rules: [
        {
          name: 'aoai-rate-or-server-errors'
          failureCondition: {
            count: 5
            interval: 'PT30S'
            statusCodeRanges: [
              { min: 429, max: 429 }
              { min: 500, max: 599 }
            ]
          }
          tripDuration: 'PT1M'
          acceptRetryAfter: true
        }
      ]
    }
  }
}

resource pool 'Microsoft.ApiManagement/service/backends@2023-09-01-preview' = {
  parent: apim
  name: 'aoai-pool'
  properties: {
    type: 'Pool'
    pool: {
      services: [
        { id: beWest.id,  priority: 1, weight: 100 }
        { id: beSweden.id, priority: 2, weight: 100 }
      ]
    }
  }
}
```

`acceptRetryAfter: true` matters: when Azure OpenAI says `Retry-After: 60`, the breaker stays open for 60 seconds rather than our 1-minute default being the only clock, so we do not probe a region that told us not to.

The API policy is short. The retry re-selects a backend from the pool; the circuit breaker makes sure the re-selection cannot land on the one that just failed:

```xml
<policies>
  <inbound>
    <base />
    <set-backend-service backend-id="aoai-pool" />
    <authentication-managed-identity resource="https://cognitiveservices.azure.com" />
  </inbound>
  <backend>
    <retry condition="@(context.Response.StatusCode == 429 || context.Response.StatusCode == 503)"
           count="2" interval="0" first-fast-retry="true">
      <forward-request buffer-request-body="true" timeout="120" />
    </retry>
  </backend>
  <outbound>
    <base />
    <set-header name="x-aoai-region" exists-action="override">
      <value>@(context.Request.Url.Host.Contains("-weu-") ? "westeurope" : "swedencentral")</value>
    </set-header>
    <set-header name="x-aoai-failover" exists-action="override">
      <value>@((context.Request.Url.Host.Contains("-weu-") ? "false" : "true"))</value>
    </set-header>
    <emit-metric name="llm_failover_total" value="1" namespace="llm-gateway">
      <dimension name="region" value="@(context.Request.Url.Host)" />
    </emit-metric>
  </outbound>
</policies>
```

`buffer-request-body="true"` is the line people forget. Without it the second attempt has no body to send, and the retry fails with a `400` that looks like a model error. We also keep `interval="0"`: the pool has already moved us to a healthy backend, so there is nothing to wait for.

## What the game day measured

We disabled the West Europe deployment at 14:00 UTC for 30 minutes on a Thursday with normal traffic, told nobody on the application teams, and watched:

![Game-day chart: p95 latency in blue and error rate in red across 14:00 to 15:00, the region pulled between 14:00 and 14:30; one short error spike to 5 percent in the first seconds, then 0.3 percent, p95 rising from 790 ms to about 1 200 ms and dropping back at 14:31; outcome bullets with 21 of 6 710 failed requests, p95 plus 410 ms and automatic recovery](/assets/img/posts/ai/enterprise-ai-azure-openai-multi-region-failover-game-day.webp){: width="1400" height="700" }

| Metric | Steady state (West Europe PTU) | During failover (Sweden Central PAYG) |
|---|---|---|
| Requests | - | 6 710 in 30 min |
| Failed requests | 0.08% | **0.31%** (21), all in the first 36 s |
| p50 latency | 520 ms | 700 ms (+180 ms) |
| p95 latency | 790 ms | 1 200 ms (+410 ms) |
| Recovery | - | circuit closed 14:31:04, 100% back on PTU by 14:31:10 |
| Human actions | - | **0** |

The 21 failures were requests already in flight to West Europe when it stopped answering, which hit the 120-second forward timeout before the retry could help; a shorter timeout for the first attempt is on the list. The +410 ms on p95 is the honest cost of running on pay-as-you-go in a region 1 200 km away with no reserved capacity; it is well inside the [latency SLO]({% post_url AI/2026-10-06-enterprise-ai-llm-cost-latency-slos-production %}) and nobody filed a ticket.

## Three things the design does not do, on purpose

- **It does not split traffic across regions in steady state.** Priority 1 takes everything while healthy. Splitting would spend pay-as-you-go money every day to save a few hundred milliseconds twice a year, and it would make the [cost dashboard]({% post_url AI/2026-10-01-enterprise-ai-azure-openai-cost-observability-dashboard %}) harder to read.
- **It does not fail over for the data-residency-sensitive APIs.** Both regions are in the EU, so chat completions can move. Fine-tuning and Assistants files stay pinned to one region under the [compliance checklist]({% post_url AI/2026-10-12-enterprise-ai-azure-openai-data-residency-compliance-checklist %}); those routes use a single backend, not the pool.
- **It does not retry on `400` or `content_filter`.** Those are the request's fault; another region gives the same answer and bills you again.

## The alert that goes with it

Failover is only safe if someone knows it happened. One Kusto rule on the emitted metric:

```kusto
customMetrics
| where name == "llm_failover_total"
| summarize failovers = sum(valueSum) by bin(timestamp, 5m)
| where failovers > 50
```

Fifty failovers in five minutes pages the platform on-call, not the application teams. Below that it is a dashboard line. Above it someone checks the Azure status page and decides whether to reprioritise the pool while the incident lasts.

## Checklist

- [ ] Two deployments, same model version, in two regions that satisfy your residency rules
- [ ] APIM backend pool with priorities; circuit breaker on `429` and `5xx` with `acceptRetryAfter`
- [ ] `retry` on `429`/`503` with `buffer-request-body="true"`
- [ ] `x-aoai-region` and `x-aoai-failover` response headers so clients and dashboards can see it
- [ ] Metric and alert on failover count
- [ ] A game day on the calendar, with the application teams not told in advance

The whole thing is about 80 lines of Bicep and 30 lines of policy. It turned an eleven-minute outage into a +410 ms p95 blip nobody noticed, which is the only argument an enterprise AI platform needs.
