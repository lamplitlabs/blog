---
layout: post
title: "Enterprise AI: Governing LLM Usage - A Shadow-AI Inventory and a Usage Register in 30 Days"
date: 2026-10-18 18:00:00 +0530
categories: ai enterprise-ai
tags: ai enterprise-ai governance shadow-ai llm apim kql azure-openai compliance
description: "Find every LLM endpoint staff already use from egress logs, register each with an owner and data class, route via one gateway: 47 found, 44 governed."
image:
  path: /assets/img/headers/ai/enterprise-ai-shadow-ai-llm-usage-register-governance.webp
  alt: "Header card reading Enterprise AI: Governing LLM Usage - a shadow-AI inventory and a usage register in 30 days"
---

Every governance document we had written for Azure OpenAI assumed one thing: that LLM traffic went through our gateway. The [six controls post](/posts/enterprise-ai-governance-azure-openai/) covered the gateway, the [audit trail post](/posts/enterprise-ai-audit-trail-azure-openai-apim/) logged every call through it, and the [data residency checklist](/posts/enterprise-ai-azure-openai-data-residency-compliance-checklist/) pinned its regions. None of it applied to the forty-odd LLM endpoints staff were calling directly from laptops, CI runners and a surprising number of Power Automate flows.

This post is the 30-day programme we ran to find that traffic, register it, and bring the approved part of it under the same gateway. It is deliberately boring: a KQL query, a YAML register, a review meeting and a firewall rule. The result is in the chart below.

## Why "just block it" fails

The first proposal was a single egress rule blocking `api.openai.com`, `api.anthropic.com` and friends. It would have broken three production integrations nobody in the platform team knew about, and it would have pushed the remaining usage to endpoints we had not listed yet. Blocking is step four, not step one. You cannot govern usage you have not seen.

So the sequence is: **discover, register, route, then block**.

## Week 0: discover from the logs you already have

We did not buy a tool. Two log sources were already in Log Analytics: the web proxy (Zscaler, forwarded as `CommonSecurityLog`) and Azure Firewall DNS logs for the Azure estate. The query below is the whole discovery step.

```kql
let llm_hosts = dynamic([
  "api.openai.com", "api.anthropic.com", "generativelanguage.googleapis.com",
  "api.mistral.ai", "api.cohere.ai", "api.groq.com", "openrouter.ai",
  "api.together.xyz", "api.perplexity.ai", "huggingface.co"
]);
union
  (CommonSecurityLog
    | where TimeGenerated > ago(14d)
    | where DestinationHostName has_any (llm_hosts) or DestinationHostName endswith ".openai.azure.com"
    | project TimeGenerated, Host = DestinationHostName, Source = SourceUserName, Bytes = SentBytes),
  (AZFWDnsQuery
    | where TimeGenerated > ago(14d)
    | where QueryName has_any (llm_hosts) or QueryName endswith ".openai.azure.com"
    | project TimeGenerated, Host = QueryName, Source = SourceIp, Bytes = 0)
| summarize Requests = count(), Callers = dcount(Source), FirstSeen = min(TimeGenerated),
            LastSeen = max(TimeGenerated), SentMB = sum(Bytes) / 1e6 by Host
| order by Requests desc
```

Two details matter here. The `.openai.azure.com` suffix catches **our own** Azure OpenAI resources being called directly, bypassing APIM - that was 9 of the 47 endpoints and the most awkward conversation, because they were ours. And `SentBytes` is the proxy for *how much data is leaving*: an endpoint with 30 requests and 400 MB sent is a document-upload workflow, not someone asking for a regex.

The first run returned 47 distinct hosts. We had expected about ten.

## Week 1: the usage register

Each endpoint gets one entry in a YAML file in the platform repo. The schema is small on purpose; every field we added beyond these was never filled in.

```yaml
# governance/llm-usage-register.yaml
- id: LLM-0007
  endpoint: api.openai.com
  discovered: 2026-09-15
  owner: finance-automation@contoso.example   # a team alias, never a person
  purpose: "Invoice line-item extraction in Power Automate flow 'AP-Intake'"
  data_class: confidential          # public | internal | confidential | restricted
  personal_data: true
  status: migrate                   # registered | migrate | block | exempt
  target: apim://aoai-gateway/products/finance
  review_by: 2026-10-15
```

The `data_class` and `personal_data` fields drive the decision mechanically:

| data_class | personal_data | Default status |
|---|---|---|
| public / internal | no | `registered` - allowed, logged at the proxy |
| confidential | any | `migrate` - must move behind APIM within 30 days |
| restricted | any | `block` - egress rule added the same week |
| any | yes, outside approved region | `block` |

`exempt` exists for exactly two cases: a vendor SaaS product that calls an LLM on its own backend (our logs see the vendor, not the model), and a security-team sandbox. Both have a `review_by` date; nothing is exempt forever.

A GitHub Action validates the file on every pull request: unique ids, a resolvable owner alias, `review_by` no more than 90 days out, and no `status: registered` where `data_class` is `confidential` or above. The register being wrong fails CI, which turned out to be the only way to keep it current.

## Week 2: one owner meeting per endpoint, 15 minutes each

Discovery gives you a host and a source IP or user; it does not give you a purpose. We booked 47 fifteen-minute calls. Three findings from them that changed the plan:

- **Eleven endpoints were the same thing.** One internal tool round-robined across OpenAI, Anthropic and Groq for cost. It became a single register entry with three hosts and one `migrate` status.
- **Six were dead.** CI jobs still carrying an API key for a prototype that shipped on Azure OpenAI months ago. Deleted, keys revoked, entries closed.
- **Four were calling our own Azure OpenAI with a shared key** copied from a wiki page in 2025. That key had no per-product quota and no audit attribution. It was rotated and the callers moved to APIM subscriptions, which is where the [audit trail](/posts/enterprise-ai-audit-trail-azure-openai-apim/) finally covered them.

## Week 3: route through the gateway

For `migrate` entries, the move is mechanical because APIM already fronts Azure OpenAI. The caller changes a base URL and swaps a vendor key for an APIM subscription key:

```diff
- OPENAI_BASE_URL=https://api.openai.com/v1
- OPENAI_API_KEY=sk-...
+ OPENAI_BASE_URL=https://aoai-gateway.azure-api.net/finance/openai/v1
+ OPENAI_API_KEY=<apim-subscription-key>
```

The APIM product then applies the policies that the rest of the estate already has - the token quota, the content-safety call, the audit logging, and a header stamp so the register id shows up in every log line:

```xml
<inbound>
  <base />
  <set-header name="x-llm-register-id" exists-action="override">
    <value>@(context.Product.Name == "finance" ? "LLM-0007" : "unregistered")</value>
  </set-header>
  <azure-openai-token-limit tokens-per-minute="60000" counter-key="@(context.Subscription.Id)"
                            estimate-prompt-tokens="true" />
</inbound>
```

That header is what makes the register pay for itself: once it is on every log line, the cost dashboard can group spend by it. The query is in [Step 6 of the cost observability post - spend per registered use case](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/#step-6-spend-per-registered-use-case); see the cost per register entry there before the invoice arrives.

Twelve of the fourteen `migrate` entries moved in week 3. The two that did not were third-party-model workloads with no Azure OpenAI equivalent; they stayed `registered` with a direct-egress allow rule scoped to a single service account, and a 90-day review.

## Week 4: block, and keep discovering

Only now does the egress rule go in. It denies the LLM host list for everything except the APIM gateway's outbound IPs and the two scoped allow rules. The discovery query from week 0 is scheduled daily and alerts when a host appears that is not in the register - which happened twice in the first month (a new coding assistant, and an employee's personal ChatGPT Plus account, which is a HR conversation, not a firewall one).

## What four weeks measured

![Bar chart of shadow LLM endpoints found in egress logs by week: unregistered endpoints fall from 47 at week 0 to 39, 24, 11 and 3 by week 4, while registered endpoints routed through APIM rise from 0 to 8, 21, 32 and 41](/assets/img/posts/ai/shadow-ai-llm-endpoints-registered-by-week.webp)
_Unregistered versus registered LLM endpoints per week, from the daily discovery query. 2,300 staff, Zscaler and Azure Firewall logs._

- **47 endpoints discovered**, against an expected ten. Nine were our own Azure OpenAI resources called around the gateway.
- **44 registered, migrated or blocked by week 4.** The remaining three are the exempt vendor SaaS cases with a review date.
- **Audited share of LLM traffic** went from about 60% (gateway only) to 97% of observed requests, measured as gateway request count over proxy-plus-gateway request count.
- **Three production integrations** that the original "just block it" plan would have broken were migrated with zero downtime because the register found them first.

## What we would do differently

1. **Start with our own `.openai.azure.com` resources.** The bypass of our own gateway was the biggest audit gap and the easiest to fix. We should have looked there before anyone else's API.
2. **Put the register in CI from day one.** The first week's spreadsheet drifted within days; the YAML file with validation did not.
3. **Keep the schema to eight fields.** Every attempt to add risk scores or model names went unfilled. Owner, purpose, data class, status and a review date are what decisions actually need.

The register now feeds the quarterly compliance report directly, and the discovery alert is the control that keeps it honest. The next step is wiring the `x-llm-register-id` header into the [cost dashboard](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/) so each register entry shows its own monthly spend.

## Related

- [Enterprise AI: Six Governance Controls Before Azure OpenAI Goes to Production in a Regulated Org](/posts/enterprise-ai-governance-azure-openai/)
- [Enterprise AI: Governance as Code for Azure OpenAI - Azure Policy Guardrails and Budget Alerts Before the First Deployment Exists](/posts/enterprise-ai-azure-policy-governance-as-code-azure-openai/)
- [Enterprise AI: An Audit Trail for Every Azure OpenAI Call with APIM, Event Hubs and Immutable Storage](/posts/enterprise-ai-audit-trail-azure-openai-apim/)
- [Enterprise AI: A Cost Observability Dashboard for Azure OpenAI with Log Analytics, KQL and Workbooks](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)
