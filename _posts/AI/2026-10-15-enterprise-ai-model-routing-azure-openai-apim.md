---
layout: post
title: "Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed"
date: 2026-10-15 00:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise apim routing finops performance governance enterprise-ai
author: manishtiwari25
description: "Route Azure OpenAI traffic to gpt-4o-mini by default and escalate to gpt-4o or o1 only when quality checks fail: APIM policy, classifier, results."
image:
  path: /assets/img/headers/ai/enterprise-ai-model-routing-azure-openai-apim.webp
  alt: "Diagram of clients calling an Azure API Management routing policy that sends about 70 percent of traffic to gpt-4o-mini, 25 percent to gpt-4o and 5 percent to a reasoning model"
---

Most enterprise LLM bills have the same shape: one expensive model deployment serving every request, because that is what the pilot used and nobody wanted to argue about quality afterwards. In the traffic we looked at for an internal copilot, roughly seven out of ten prompts were lookups, rewording or short summaries that `gpt-4o-mini` answers just as well as `gpt-4o` at a fraction of the price. **Model routing** means picking the model per request instead of per application, and escalating to a stronger model only when the cheap answer is not good enough. If you already front Azure OpenAI with Azure API Management for [quotas and chargeback](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/) or [semantic caching](/posts/enterprise-ai-apim-semantic-caching-azure-openai/), routing is the next policy in the same pipeline.

## The three tiers

| Tier | Deployment | Use for | Relative cost (input) |
|------|------------|---------|----------------------|
| 1 | `gpt-4o-mini` | lookups, rewording, classification, short summaries | 1x |
| 2 | `gpt-4o` | multi-document synthesis, code changes, anything with tables | ~15x |
| 3 | `o1` (reasoning) | multi-step planning, maths, policy reasoning with constraints | ~90x |

The point of the table is not the exact numbers, which change every quarter, but the ratio: a wrong choice at tier 1 costs almost nothing to retry, while sending a lookup to tier 3 wastes two orders of magnitude.

## Routing design

There are three places you can make the decision, and we ended up using all of them in order:

1. **Static rules**: the calling product sets `x-route-hint: fast|quality|reasoning`. Code-change tooling always asks for `quality`; the help-desk bot asks for `fast`. This handles about 40% of traffic with no model call.
2. **Classifier**: for everything else, a tiny `gpt-4o-mini` call with a fixed system prompt returns one of `simple`, `complex`, `reasoning`. It costs ~60 tokens and about 300 ms. Over 90% of requests come back `simple`.
3. **Escalation on check failure**: the tier-1 answer runs through a cheap check (structured-output schema validates, no refusal, confidence field above 0.7, citations resolve for RAG). If the check fails, the same request is replayed to tier 2. Tier 2 failures go to tier 3 only when the classifier said `reasoning`.

Escalation is what makes the cheap default safe. Without it you are betting the user experience on the classifier; with it the classifier only needs to be *mostly* right.

## The APIM policy

Each tier is a separate backend in APIM pointing at its own deployment (and, in our case, its own PTU or pay-as-you-go resource). The inbound policy picks the backend from the hint or a classifier call:

```xml
<inbound>
  <base />
  <set-variable name="hint" value="@(context.Request.Headers.GetValueOrDefault("x-route-hint", ""))" />
  <choose>
    <when condition="@(context.Variables.GetValueOrDefault<string>("hint") == "quality")">
      <set-backend-service backend-id="aoai-gpt4o" />
    </when>
    <when condition="@(context.Variables.GetValueOrDefault<string>("hint") == "reasoning")">
      <set-backend-service backend-id="aoai-o1" />
    </when>
    <otherwise>
      <!-- classifier: tiny completion against the mini deployment -->
      <send-request mode="new" response-variable-name="cls" timeout="5" ignore-error="true">
        <set-url>https://aoai-mini.openai.azure.com/openai/deployments/gpt-4o-mini/chat/completions?api-version=2024-10-21</set-url>
        <set-method>POST</set-method>
        <set-header name="Content-Type" exists-action="override"><value>application/json</value></set-header>
        <authentication-managed-identity resource="https://cognitiveservices.azure.com" />
        <set-body>@{
          var user = ((JObject)context.Request.Body.As<JObject>(preserveContent: true))["messages"].Last["content"].ToString();
          return new JObject(
            new JProperty("max_tokens", 3),
            new JProperty("messages", new JArray(
              new JObject(new JProperty("role","system"), new JProperty("content","Classify the request as simple, complex or reasoning. Reply with one word.")),
              new JObject(new JProperty("role","user"), new JProperty("content", user))))).ToString();
        }</set-body>
      </send-request>
      <set-variable name="class" value="@{
        var r = (IResponse)context.Variables["cls"];
        if (r == null || r.StatusCode != 200) return "simple";
        return r.Body.As<JObject>()["choices"][0]["message"]["content"].ToString().Trim().ToLower();
      }" />
      <choose>
        <when condition="@(context.Variables.GetValueOrDefault<string>("class") == "complex")">
          <set-backend-service backend-id="aoai-gpt4o" />
        </when>
        <when condition="@(context.Variables.GetValueOrDefault<string>("class") == "reasoning")">
          <set-backend-service backend-id="aoai-o1" />
        </when>
        <otherwise>
          <set-backend-service backend-id="aoai-mini" />
        </otherwise>
      </choose>
    </otherwise>
  </choose>
  <set-header name="x-routed-model" exists-action="override">
    <value>@(context.Variables.GetValueOrDefault<string>("class", context.Variables.GetValueOrDefault<string>("hint", "simple")))</value>
  </set-header>
</inbound>
```

Two notes on the policy. The classifier call uses `ignore-error="true"` and defaults to `simple` on any failure, so a classifier outage degrades to "everything goes to mini" rather than to 5xx. And the `x-routed-model` header is echoed back so the client (and the cost dashboard) can see which tier served the request; it is the single most useful field when a user says "the answers got worse".

## Escalation in .NET

The escalation step lives in the client, because APIM cannot evaluate the quality of a completion. The caller is a thin wrapper around the OpenAI SDK:

```csharp
public async Task<Answer> AskAsync(ChatRequest req, CancellationToken ct)
{
    var first = await _client.CompleteAsync(req with { RouteHint = null }, ct);
    if (_checks.Passes(first))
        return first;

    _metrics.Escalations.Add(1, new("from", first.RoutedModel), new("reason", _checks.LastFailure));
    var second = await _client.CompleteAsync(req with { RouteHint = "quality" }, ct);
    if (_checks.Passes(second) || first.RoutedModel != "reasoning")
        return second;

    return await _client.CompleteAsync(req with { RouteHint = "reasoning" }, ct);
}
```

`_checks.Passes` is deliberately boring: JSON schema validation for [structured outputs](/posts/structured-outputs-azure-openai-dotnet/), a `finish_reason` that is not `content_filter` or `length`, and for RAG answers a check that every cited chunk id exists in the retrieved set. We tried an LLM-as-judge check here and removed it; it doubled latency on the happy path for very little gain.

## Results after four weeks

![Table comparing four weeks of internal copilot traffic before and after tiered routing: 71 percent of requests on gpt-4o-mini, 9 percent escalation rate, daily cost down 61 percent, p50 latency down 58 percent, eval pass rate down half a point; below it a flow diagram classify, route to mini, answer check, escalate](/assets/img/posts/ai/enterprise-ai-model-routing-results.webp){: width="1200" height="760" }

- **71%** of requests were served by `gpt-4o-mini`; **9%** of those escalated to `gpt-4o`. Fewer than 1% reached `o1`.
- Daily cost dropped from about **$1,940 to $760** (-61%) at the same request volume.
- p50 latency fell from **1.9 s to 0.8 s** because the mini deployment is both faster and had PTU headroom.
- The pass rate on our [golden evaluation set](/posts/evaluating-rag-retriever-golden-set-dotnet/) moved from 94.1% to 93.6%. Half a point was within the week-to-week noise we had seen before routing, and the failures that remained were retrieval failures, not model failures.

## What went wrong

- **Classifier drift.** A product team started prefixing every prompt with a long policy preamble, and the classifier began labelling everything `complex`. Fix: classify only the last user message, truncated to 2,000 characters.
- **Double billing on escalation.** An escalated request pays for both calls. At 9% escalation this is still cheap, but we added an alert at 20% because that usually means a check is broken, not that the traffic changed.
- **Streaming.** You cannot escalate a response you have already started streaming to the user. Streaming endpoints skip the check and use the hint only; non-streaming internal calls get full escalation.
- **Chargeback confusion.** Teams saw `gpt-4o-mini` line items they had never asked for. Emitting `x-routed-model` into the [cost dashboard](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/) with the original hint next to it settled that in a week.

## Checklist

1. Separate APIM backends per tier, each with managed identity, no keys in policy.
2. Hint header for products that know what they need; classifier for the rest; default to the cheapest tier on any failure.
3. Deterministic quality checks in the client, escalation one tier at a time, metrics on every escalation.
4. Echo the routed model back to the caller and into logs.
5. Re-run your golden set before and after, and keep running it weekly; routing is a change to model behaviour even if no prompt changed.

## Related posts

- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Enterprise AI: Semantic Caching for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-semantic-caching-azure-openai/)
- [Enterprise AI: A Cost Observability Dashboard for Azure OpenAI with Log Analytics, KQL and Workbooks](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)
