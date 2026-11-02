---
title: "Enterprise AI: Audit Logging and Policy Controls for an LLM Gateway"
date: 2026-10-23 09:00:00 +0530
categories: ai enterprise-ai
tags: ai enterprise-ai llm gateway audit-logging policy opa rego compliance governance
author: manishtiwari25
description: "Every call through your LLM gateway should emit one audit line and pass six policy rules: schema, PII scan, tool allow-list, verdict codes, and 30-day results."
image:
  path: /assets/img/headers/ai/enterprise-ai-llm-gateway-audit-logging-policy-controls.webp
  alt: "Dashboard card for Enterprise AI LLM gateway audit logging showing before and after bars: decision logging, policy coverage and blocked requests all reach 100 percent after"
---

The first time security asked "who asked the model to email that spreadsheet, and why did it say yes?", the honest answer was a shrug and three days of grepping container logs. The LLM gateway was routing traffic fine, but it kept no durable record of decisions, and the handful of policy rules lived in application code where only one team enforced them. This post is about fixing that with two moves that reinforce each other: **one structured audit line per proxied call**, and **policy controls enforced at the gateway**, not inside each app.

Neither move needs a new platform. The audit record is one NDJSON line written to append-only storage; the policy layer is six OPA/Rego rules evaluated in the gateway's request path. What follows is the exact schema, the rules, the failure modes we hit, and the numbers after 30 days.

## What an LLM gateway must answer

An internal LLM gateway sits between every application and the model providers. Once all traffic funnels through one choke point, auditors, security and finance all ask variations of the same four questions:

- **Who** called which model, from which application, on whose behalf?
- **What** was the system allowed to do - which tools, which models, which data class?
- **Why** was a call allowed or blocked, and which rule made that decision?
- **How much** did it cost, and is anyone near a quota?

If the gateway cannot answer these from a queryable log, every incident review becomes an archaeology dig. If it cannot enforce the "what is allowed" part in one place, every new app re-implements (or forgets) the rules.

## The audit record: one line per call, content never

The design rule that made this shippable: **log the decision and the metadata, never the prompt or completion body**. Prompt content stays in the request path only. That one constraint removed most of the privacy review friction, because the audit store never holds user content.

Each proxied call appends exactly one line to an NDJSON stream:

```json
{
  "ts": "2026-10-23T14:02:19Z",
  "request_id": "req_9f2c7a",
  "app": "contract-review",
  "user": "u-0934",
  "model": "gpt-4o",
  "tool": "email.send",
  "decision": "block",
  "rule": "PII-004",
  "ticket": "GOV-1882",
  "reason": "SSN-like pattern in recipient field",
  "tokens_in": 2210,
  "tokens_out": 0,
  "latency_ms": 148,
  "cost_usd": 0.0
}
```

Field choices that mattered:

- **`request_id`** ties the audit line to the provider response and to any downstream trace. One line per call, keyed by this id, is what makes "replay the incident" a query instead of a project.
- **`decision` + `rule` + `ticket`** are the triplet auditors actually read. A `block` always carries the rule id that fired and a ticket id in the governance tracker, so a blocked user has a reference to appeal and the reviewer has context.
- **`tokens_in` / `tokens_out` / `cost_usd`** come from the provider response, not an estimate. Finance reconciles these against the invoice; that is what makes the log trustworthy enough to be the chargeback source.
- **`latency_ms`** is gateway-observed time. It double-serves as the health signal when a deployment degrades.

The stream lands in append-only object storage (immutability policy on the container), partitioned `yyyy/MM/dd`. A blocked call costs `$0.0` and still logs `tokens_in`, because the prompt was read and scanned - that accounting detail ends arguments about whether blocks are "free".

## The six policy rules that cover 95% of decisions

Policies are Rego, evaluated in the gateway before the provider call and again on the tool-call path. Six rules carried almost all of the first month:

```rego
package llm.gateway

# 1. MODEL-001: apps only get models on their allow-list
deny contains v if {
  not input.model in data.grants[input.app].models
  v := {"rule": "MODEL-001", "reason": sprintf("%s not on allow-list for %s", [input.model, input.app])}
}

# 2. DATA-002: data class must match the app's registered class
deny contains v if {
  input.data_class != data.grants[input.app].data_class
  v := {"rule": "DATA-002", "reason": "data class above app registration"}
}

# 3. PII-004: tool arguments get a PII scan before execution
deny contains v if {
  input.tool; pii.detect(input.tool_args)
  v := {"rule": "PII-004", "reason": "PII pattern in tool arguments"}
}

# 4. SCOPE-011: tool must be inside the app's granted scope
deny contains v if {
  input.tool; not input.tool in data.grants[input.app].tools
  v := {"rule": "SCOPE-011", "reason": "tool outside granted scope"}
}

# 5. COST-007: daily cost budget per app, evaluated on a rolling window
deny contains v if {
  data.usage[input.app].today_usd + input.est_cost_usd > data.grants[input.app].daily_budget_usd
  v := {"rule": "COST-007", "reason": "daily budget exhausted"}
}

# 6. EGRESS-009: retrieval/web tools only reach registered domains
deny contains v if {
  input.tool == "web.fetch"
  not input.tool_args.domain in data.registered_domains
  v := {"rule": "EGRESS-009", "reason": "destination domain not registered"}
}
```

The full policy set is a config file in git, reviewed like code, versioned with the gateway. New apps onboard by adding a `grants` entry - models, tools, data class, budget - which is a pull request, not a meeting.

## What the decision log looks like in practice

![Terminal tail of the LLM gateway audit log showing one NDJSON decision line per call: green allow entries for support-copilot and invoice-ocr, yellow BLOCK entries with ticket ids GOV-1882 through GOV-1885 for PII-004, COST-002 and EGRESS-007 rules, a red tool-deny for SCOPE-011, and an excerpt of the audit.rego policy below](/assets/img/posts/ai/enterprise-ai-llm-gateway-audit-logging-policy-controls-decision-log.webp)

Reading the log top to bottom tells a story an auditor can follow without help: two routine allows, then a PII-004 block on `contract-review` trying to send mail with an SSN-like string in the recipient field, a SCOPE-011 deny where `legal-assist` reached for an HR tool it was never granted, and a COST-002 block where `analytics-bot` asked for a model outside its allow-list. Every block has a ticket id, so the follow-up conversation starts from evidence instead of recollection.

## Failure modes we hit (so you do not)

- **Logging the prompt "just for debugging".** We tried a debug flag that captured prompt bodies. One privacy review killed it in an afternoon, and rightly so. Hashes (`sha256` of the prompt) give you dedup and abuse-pattern detection without content. Keep the flag; never turn it on in production.
- **Rules in application code.** The first version of the PII scan lived in one team's service. Three other apps never got it. A control that depends on every team remembering to call it is not a control; moving it into the gateway request path made coverage a property of the platform.
- **Silent policy evaluation.** An early build evaluated policies but only logged blocks, not allows. Auditors could not distinguish "rule passed" from "rule never ran". Every decision gets a line, allow or block, with the rule id that produced it.
- **Blocking without a ticket.** Blocks that just say "denied" generate support tickets with no context and get routed nowhere. Minting the governance ticket id inside the policy evaluation made every block actionable and every appeal cheap.

## Results after 30 days

| Metric | Before | After |
| --- | --- | --- |
| Calls with a durable decision record | ~26% (container logs only) | 100% |
| Policy rules enforced for every app | 2 of 6, in app code | 6 of 6, in the gateway |
| Time to answer "who asked the model to do X" | ~34 days (first audit request) | ~2 minutes (one KQL query) |
| Blocked violations in the first month | not measurable | 43, all with ticket ids |
| Disputed blocks | n/a | 0 |

The number that surprised us most was the last one. Because every block carries the rule id and a ticket, the conversation moved from "your gateway broke my app" to "here is the exact field that tripped PII-004" - and nobody disputed a single block in the first month.

## The takeaway

An LLM gateway earns its place in the architecture when it can prove what happened, not just route traffic. One NDJSON line per call - decision, rule, ticket, tokens, cost, never the content - plus six Rego rules enforced in the request path turned audit season from a scramble into a query. Start with the schema and the immutability policy; the policy rules can grow one at a time from there.

## Related

- [Enterprise AI: An Audit Trail for Every Azure OpenAI Call with APIM, Event Hubs and Immutable Storage](/posts/enterprise-ai-audit-trail-azure-openai-apim/)
- [Enterprise AI: LLM Observability with OpenTelemetry in .NET - Tracing Tokens, Cost and Quality per Request](/posts/enterprise-llm-observability-opentelemetry-dotnet/)
- [Enterprise AI: Per-Team Token Quotas and Chargeback for Azure OpenAI with Azure API Management](/posts/enterprise-ai-apim-token-quotas-chargeback-azure-openai/)
- [Enterprise AI: Governing LLM Usage - A Shadow-AI Inventory and a Usage Register in 30 Days](/posts/enterprise-ai-shadow-ai-llm-usage-register-governance/)
