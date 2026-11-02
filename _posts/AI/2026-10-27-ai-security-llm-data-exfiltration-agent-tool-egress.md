---
layout: post
title: "AI Security: Agent Tool-Egress and Data-Exfiltration Controls That Actually Hold"
date: 2026-10-27 19:30:00 +0100
categories: ai security
tags: ai-security agents data-exfiltration tool-egress enterprise-ai llm opa
image:
  path: assets/img/posts/ai/ai-agent-tool-egress-exfiltration.webp
  alt: "Header diagram of an agent tool-egress control plane: an AI agent box sends every tool call through an egress policy gateway, which splits traffic into allowed tools (green) and denied calls that go to a signed audit log (red), with the caption deny-by-default, per-tool allowlists, content inspection, signed audit log"
description: "Prompt injection turns agents into exfiltration channels. The fix is egress policy on tool calls: deny-by-default hosts, payload scans, budgets, audit logs."
---

Your agent reads a support ticket, decides to "help," and POSTs the customer's email thread to a pastebin clone. Nobody gave it that instruction - a poisoned web page it summarized did. In the [previous post on the model supply chain]({% post_url AI/2026-10-25-ai-security-model-supply-chain-attack-surface %}) we covered how a bad model or a tainted dataset gets *into* your pipeline. This post is about what happens when a good model is *talked into* sending your data *out*: tool egress, and how to put a policy wall in front of it.

## Why prompt injection is an egress problem

Prompt injection is usually framed as a language problem: the model read hostile text and got confused. That framing pushes you toward mitigations that never fully work - better system prompts, instruction hierarchy, "ignore the previous instructions" classifiers. The injection still lands sometimes, because the model cannot reliably tell data from instructions.

The useful reframe: the moment the model's confused output becomes a **tool call**, it stops being a language problem and becomes a network problem. Exfiltration requires the agent to *send* something somewhere. If every tool call passes through a deterministic gate that checks the destination, the payload, and the caller's budget, a successful injection degrades into a denied call and an audit entry instead of a breach.

![Screenshot-style panel of an egress gateway decision for an allowed tool call: tool github.create_issue, host api.github.com, content scan clean with no secret pattern and a 412 byte payload, caller support-triage-agent within its daily budget, verdict ALLOW in green with a signed audit-log entry appended](/assets/img/posts/ai/ai-agent-tool-egress-policy-allowed.webp)

## The four controls that hold

**1. Deny-by-default egress allowlist.** The agent process gets no direct network access to arbitrary hosts. Every tool call is routed through an egress gateway that checks the destination against a per-agent allowlist: `api.github.com` yes, `pastebin.example.com` no. DNS exfiltration is covered too, because the allowlist applies to the resolver, not just HTTP. An agent that only summarizes web pages has no business reaching 10,000 distinct hosts; an allowlist of five to twenty is normal.

**2. Content inspection on the payload.** Destination alone is not enough - `api.github.com` is on the allowlist, and it is also a perfectly good exfiltration channel if the agent can open issues containing customer data. Scan the outbound payload for secret patterns (API keys, JWTs, private key headers), for the data classes the agent was shown (customer emails, ticket IDs), and for the classic steganography-of-convenience: large base64 blobs. A 412-byte issue body passes; a 4 MB "diagnostic attachment" does not.

**3. Per-agent budgets and rate limits.** Exfiltration is either a smash-and-grab (one huge request) or a slow drip (thousands of small ones). Content inspection catches the first; budgets catch the second. Calls per day, bytes per day, distinct hosts per day - any of them crossing a threshold freezes the agent and pages a human. The agent above gets 200 calls and 100 MB a day, which is generous for triage and useless for draining a database.

**4. A signed, append-only audit log.** Every decision - allow or deny - is recorded with the caller identity, session, tool, destination, payload hash, and policy version, and the log entry is hash-chained. When something does go wrong, "what did the agent send, and when" is a query, not a forensic reconstruction. It also deters the next class of attacker: a malicious insider *adjusting* the agent's tools, because the log shows who changed what.

![Screenshot-style panel of an egress gateway decision for a denied tool call: tool http.post, host pastebin.example.com, content scan blocked because the host is not on the allowlist and the payload matches the customer e-mail corpus, caller research-agent, verdict DENY in red with a signed audit-log entry appended](/assets/img/posts/ai/ai-agent-tool-egress-policy-denied.webp)

## A minimal policy you can read in one sitting

This is the whole idea as an OPA Rego policy - small enough to audit, which is the point:

```rego
package egress

default allow := false

allow {
  input.host == data.allowlist[input.agent][_]
  not payload_suspicious
  within_budget
}

payload_suspicious {
  regex.match(`(?i)(api[_-]?key|bearer [a-z0-9._-]+|BEGIN [A-Z ]*PRIVATE KEY)`, input.body)
}

payload_suspicious {
  count(input.body) > data.budgets[input.agent].max_payload_bytes
}

within_budget {
  data.usage[input.agent].calls_today < data.budgets[input.agent].max_calls
  data.usage[input.agent].bytes_today < data.budgets[input.agent].max_bytes
}
```

And the gateway side is a thin shim between the agent framework and its tools: intercept the tool call, evaluate the policy, execute or deny, then append the signed audit entry. No model in the loop, no probabilistic judgment - the policy engine is deterministic, so the same call always gets the same verdict, which is exactly what you want from a security boundary and exactly what you can never get from a prompt.

## What to do this week

1. **Inventory the tools your agents can call.** If the honest answer is "whatever the framework defaults to," that is the finding.
2. **Put the agent runtime in a network namespace (or behind a proxy) with deny-by-default egress**, then add back the hosts it demonstrably needs. Expect the first day to surface tools you forgot existed.
3. **Add payload scanning** for the two or three data classes the agent actually touches, plus secret patterns and oversized bodies.
4. **Set budgets** an order of magnitude above observed usage, and alert on the crossing, not the breach.
5. **Log every decision** with a payload hash. Verify you can answer "show me everything agent X sent to host Y in March" before you need to.

## Where Pulse fits

We are building Pulse, Lamplit Labs' multi-project self-improving automation product, and the agents it runs operate under exactly this model: every tool call they make passes through an egress policy gate, runs inside a budget, and lands in a signed audit log. Autonomous work you cannot audit is not automation; it is delegation without supervision. Pulse is coming soon - if agent governance is on your 2027 roadmap, that is the problem we are building it to solve. We wrote about [how Pulse improves this very blog]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}) last week.

## Related posts

- [AI Security: Map Your Model Supply Chain Attack Surface Before Someone Else Does]({% post_url AI/2026-10-25-ai-security-model-supply-chain-attack-surface %})
- [Inside Pulse: The Self-Improving RSI Tool We Use to Improve This Blog]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %})
- [Fine-Tuning Pipelines Need Regression Gates, Not Just Evals]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [AI SDLC for .NET Teams: a phase-by-phase guide]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
