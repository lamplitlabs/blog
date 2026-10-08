---
title: "Enterprise AI: An Audit Trail for Every Azure OpenAI Call with APIM, Event Hubs and Immutable Storage"
date: 2026-10-26 08:00:00 +0200
categories: ai
tags: ai azure openai enterprise governance security compliance apim audit enterprise-ai
description: "How we made 99.6% of production Azure OpenAI calls traceable to user, app, prompt version and model with an APIM policy, no app code changed."
image:
  path: /assets/img/headers/ai/enterprise-ai-audit-trail-azure-openai-apim.webp
  alt: "Bar chart of Azure OpenAI audit coverage: traceable calls 31 percent before and 99.6 percent after, calls with content retained 0 before and 64 percent after under policy scope, audit requests answered within one day 100 percent"
---

![Bar chart: traceable LLM calls 31% before and 99.6% after, calls with content retained 0% before and 64% after under policy scope, audit requests answered within one day 100%](/assets/img/headers/ai/enterprise-ai-audit-trail-azure-openai-apim.webp)

The [governance controls post]({% post_url AI/2026-10-03-enterprise-ai-governance-azure-openai %}) listed "an audit trail per call" as control number four and spent two paragraphs on it. This is the long version: what we log, where it goes, who can read it, and the numbers after one quarter across 8 applications, 38 teams and 2.4 million calls.

## The question an auditor actually asks

Not "do you log?" but: *for this output that a customer complained about on 14 March, show me who asked, which application, which prompt template version, which model deployment, what the content filter said, and prove none of that was altered afterwards.*

Before this work we could answer that for 31% of calls - the ones from the two apps that had built their own logging. The other six apps had application logs with varying fields, two had none at all for LLM calls, and nothing was tamper-evident.

## Design: log at the gateway, not in the app

Every Azure OpenAI call already went through Azure API Management because of the [token quota and chargeback]({% post_url AI/2026-10-05-enterprise-ai-apim-token-quotas-chargeback-azure-openai %}) work. That made the gateway the one place where a policy could capture a complete record without asking 38 teams to change code.

![Table of audit record fields with source, store and retention: correlation id and timestamp from the APIM policy; caller app and Entra user oid from JWT claims; deployment, model and api-version from the request URL and response header; token counts from the response usage; prompt-version id from an x-prompt-version header; content filter result from the response body; all in Log Analytics for 2 years; prompt and completion text in immutable Storage with customer-managed keys for 90 days or per-app policy; SHA-256 content hash in Log Analytics](/assets/img/posts/ai/enterprise-ai-audit-log-record-fields.webp)

The APIM policy does three things on every request:

1. **Builds the metadata record** - correlation id, caller app id and Entra user `oid` from the validated JWT, deployment and `api-version` from the URL, `x-ms-model` and token usage from the response, the `prompt_filter_results` block, and an `x-prompt-version` header that apps set from their prompt registry. This goes to an Event Hub with `log-to-eventhub`.
2. **Hashes the request and response bodies** (SHA-256) and puts the hashes in the same record. Every app gets this; it costs nothing in storage and proves later that a retained body is the one that was sent.
3. **Forwards the bodies themselves** to a second Event Hub only when the calling app's product in APIM carries a `retain-content: true` tag. A Function drains that hub into a Storage account with an immutable, time-based retention policy and customer-managed keys.

Two Event Hubs rather than one because the metadata stream is small (about 1.1 KB per call) and read by everyone with Log Analytics access, while the content stream is large and read by almost nobody.

## The policy, shortened

```xml
<outbound>
  <base />
  <set-variable name="body" value="@(context.Response.Body.As<string>(preserveContent: true))" />
  <log-to-eventhub logger-id="llm-audit-meta">@{
    var jwt = context.Request.Headers.GetValueOrDefault("Authorization","").AsJwt();
    var usage = JObject.Parse((string)context.Variables["body"])["usage"];
    return new JObject(
      new JProperty("correlationId", context.RequestId),
      new JProperty("ts", DateTime.UtcNow),
      new JProperty("appId", jwt?.Claims.GetValueOrDefault("azp")),
      new JProperty("userOid", jwt?.Claims.GetValueOrDefault("oid")),
      new JProperty("deployment", context.Request.MatchedParameters["deployment-id"]),
      new JProperty("model", context.Response.Headers.GetValueOrDefault("x-ms-model")),
      new JProperty("promptVersion", context.Request.Headers.GetValueOrDefault("x-prompt-version","unset")),
      new JProperty("promptTokens", usage?["prompt_tokens"]),
      new JProperty("completionTokens", usage?["completion_tokens"]),
      new JProperty("filterResult", JObject.Parse((string)context.Variables["body"])["prompt_filter_results"]),
      new JProperty("reqSha256", Sha256(context.Request.Body.As<string>(preserveContent: true))),
      new JProperty("resSha256", Sha256((string)context.Variables["body"]))
    ).ToString();
  }</log-to-eventhub>
  <choose>
    <when condition="@(context.Product?.Tags?.Contains("retain-content") == true)">
      <log-to-eventhub logger-id="llm-audit-content">@{ /* correlationId + both bodies */ }</log-to-eventhub>
    </when>
  </choose>
</outbound>
```

Streaming responses need `preserveContent: true` and add about 4 ms p50 at the gateway; non-streaming added under 1 ms. We did not see the latency SLOs from the [SLO post]({% post_url AI/2026-10-06-enterprise-ai-llm-cost-latency-slos-production %}) move.

## What the quarter looked like

| Measure | Before | After |
|---|---|---|
| Calls traceable to user + app + prompt version + model | 31% | 99.6% |
| Calls with retained content | 0% | 64% (apps whose data classification allows it) |
| Audit requests answered | 3 of 7, median 9 days | 11 of 11, all within 1 day |
| App code changes required | - | 0 (the `x-prompt-version` header was optional; 6 of 8 apps added it) |
| Monthly cost | - | about 290 EUR: Event Hubs standard, Log Analytics ingest 70 GB, Storage 1.9 TB cool tier |

The 0.4% gap is calls that bypassed APIM: a notebook with a direct key that the Key Vault rotation in the governance post later closed, and one app's health check.

## Three things I would do differently

- **Make `x-prompt-version` mandatory from day one** with a 400 from the gateway. "Unset" is the value in 23% of our records, and it is the field auditors asked for most.
- **Put the user `oid` and a hashed version** of it in the record. Some audits want a count per user without revealing who; we had to re-derive that.
- **Decide retention per data classification before the first app**, not after the third. The `retain-content` tag is a per-product switch; the policy for *who* sets it took longer than the engineering.

## Related

- [Enterprise AI: Six Governance Controls Before Azure OpenAI Goes to Production in a Regulated Org]({% post_url AI/2026-10-03-enterprise-ai-governance-azure-openai %}) - the control list this post expands.
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management]({% post_url AI/2026-10-05-enterprise-ai-apim-token-quotas-chargeback-azure-openai %}) - the APIM setup the audit policy sits on.
- [Enterprise AI: LLM Observability with OpenTelemetry in .NET - Tracing Tokens, Cost and Quality per Request]({% post_url AI/2026-10-04-enterprise-llm-observability-opentelemetry-dotnet %}) - the in-app trace that the correlation id joins to.
- [Enterprise AI: Cost and Latency SLOs for LLM Workloads - Burn-Rate Alerts for Azure OpenAI in Production]({% post_url AI/2026-10-06-enterprise-ai-llm-cost-latency-slos-production %}) - the SLOs we checked the gateway overhead against.
- [Azure OpenAI Content Filters in .NET: Handling finish_reason content_filter Without Breaking Your App]({% post_url AI/2026-10-02-azure-openai-content-filter-dotnet %}) - what the filter result field in the record means.
- [Enterprise AI: Governance as Code for Azure OpenAI - Azure Policy Guardrails and Budget Alerts Before the First Deployment Exists]({% post_url AI/2026-10-20-enterprise-ai-azure-policy-governance-as-code-azure-openai %}) - the Azure Policy that makes diagnostic settings and the audit policy mandatory on every gateway.
- [Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed]({% post_url AI/2026-10-15-enterprise-ai-model-routing-azure-openai-apim %}) - the routing decision that the record's model field has to capture per request.
