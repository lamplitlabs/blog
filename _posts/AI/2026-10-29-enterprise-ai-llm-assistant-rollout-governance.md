---
layout: post
title: "Rolling out LLM assistants in a large organisation: governance that ships"
date: 2026-10-29 09:00:00 +0000
categories: ai
tags: enterprise-ai governance llm-assistants rollout evals llm-security policy change-management
description: "A governance model for rolling out LLM assistants in a large org: a four-stage rollout pipeline, one control plane, and an eval gate for model changes."
image:
  path: /assets/img/headers/ai/enterprise-ai-llm-assistant-rollout.webp
  alt: "Diagram of a four-stage LLM assistant rollout pipeline - sandbox, pilot, scale and fleet - where each stage shows its scope, its data boundary and its exit gate, with one shared control plane for identity, policy, budgets, audit log and eval gates underneath"
---

The pattern repeats in every large organisation. A team wires an LLM assistant into their workflow, the demo is good, and within a quarter there are five more assistants nobody can quite enumerate. Each has its own API key, its own prompt, its own idea of which data it may touch. Procurement finds out from the invoice. Security finds out from an incident. Legal finds out from a discovery request.

The assistants are not the problem. The missing rollout discipline is. An LLM assistant in an enterprise is a production system that reads internal data and acts on it, and it deserves the same rigour as any other system that does that: staged rollout, explicit data boundaries, a control plane, and a measurable promotion gate.

This post lays out the governance model that works in practice: a four-stage rollout pipeline and the controls that sit underneath it.

## The rollout pipeline

![Diagram of a four-stage LLM assistant rollout pipeline - sandbox, pilot, scale and fleet - where each stage shows its scope, its data boundary and its exit gate, with one shared control plane for identity, policy, budgets, audit log and eval gates underneath](/assets/img/headers/ai/enterprise-ai-llm-assistant-rollout.webp)

Each stage has an owner, a data boundary and an exit gate. Nothing moves to the next stage on enthusiasm; it moves on evidence.

**1. Sandbox.** One team, no real data. The assistant runs against synthetic cases or public documents. The point of this stage is not to prove value - it is to find out what the team actually wants the assistant to do, in writing, before real data is involved. Exit gate: a written use-case definition and a first eval set, even a small one.

**2. Pilot.** 50 to 100 seats against a redacted or low-sensitivity corpus. This is where you learn the failure modes: which prompts produce confident nonsense, which documents the retrieval layer should never return, where users blindly trust the output. A weekly quality review - humans reading real transcripts - is non-negotiable here. Exit gate: measured task success above your agreed floor, and every serious failure mode either fixed or explicitly accepted in writing.

**3. Scale.** Department-wide, with the approval workflow live. New data sources, new tools and prompt changes now go through review, because at this size a bad prompt is an incident, not an experiment. The regression gate on prompt and model changes becomes mandatory. Exit gate: the assistant behaves like boring infrastructure - predictable cost, predictable latency, predictable failure handling.

**4. Fleet.** Whole organisation, full telemetry, quarterly model review. The assistant is now a platform service with a budget line, an on-call story and an audit trail. New teams onboard by declaring their use case and data classes, not by standing up their own stack.

## One control plane, not five stacks

The mistake that kills most enterprise AI programmes is letting every team build its own plumbing. Five assistants means five identity integrations, five interpretations of "sensitive", five cost surprises.

Instead, every assistant request travels one path, and the controls sit on that path:

![Architecture diagram of an enterprise LLM assistant request path - user, gateway, assistant, LLM provider and internal tools - with numbered control points for identity, policy and budget checks, response re-scanning and egress-controlled tool calls, all tapped into a signed audit log and a shared control plane](/assets/img/posts/ai/enterprise-ai-assistant-request-path.webp)

- **Identity first.** The user's SSO identity is attached before any data moves. Every decision downstream - what the assistant may retrieve, which tools it may call, which models it may use - is a function of who asked and what they are allowed to see. An anonymous assistant is an unauditable assistant.
- **A gateway that decides, not forwards.** Every call passes a policy check (is this tool allowed for this data class? is this host on the allowlist?) and a budget check (has this team burned its allocation?). Denied calls are logged with the reason, which is how you discover that the legal team's assistant is trying to read the HR corpus.
- **Tool calls are egress.** When the assistant calls Jira, the CRM or the docs platform, that call is data leaving your trust boundary. It goes through the same egress policy as any outbound traffic - the [egress gateway model for agent tool calls]({% post_url AI/2026-10-27-ai-security-llm-data-exfiltration-agent-tool-egress %}) applies here unchanged.
- **Everything is logged, signed.** Who asked, what left, what it cost, which model version answered. When compliance or a regulator asks "what did the AI tell this customer in March", you answer from the audit log, not from memory.

## The eval gate decides promotions

The control plane keeps the fleet safe day to day. The eval gate decides when anything underneath it is allowed to change - a new model version, a rewritten system prompt, a new tool. The rule is simple: no promotion on vibes.

![Screenshot-style panel of an eval gate decision for a held model promotion: candidate model-v5 against baseline model-v4 on 1,842 curated eval cases, accuracy up 0.4 percent within the noise band but the billing domain regressed 3.1 percent on refund intents and cost is up 18 percent, verdict HOLD in red with a signed eval report logged](/assets/img/posts/ai/enterprise-ai-assistant-eval-gate.webp)

The picture shows a real-shaped decision: a candidate model that looks fine in aggregate (+0.4% accuracy, inside the noise band) but regresses 3.1% on refund intents in the billing domain and costs 18% more per token. The aggregate number would have waved it through. The per-domain breakdown holds it, and the fleet stays on the old version until the refund-intent regression is fixed and re-run.

Three properties make this gate work:

1. **The eval set is curated and versioned.** It grows every time a real user finds a failure the set missed - the [regression-gate pattern for fine-tuning pipelines]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) is the same discipline applied to prompts and hosted models.
2. **Thresholds are written down before the run.** Promote only when overall accuracy clears a margin, no domain regresses beyond its limit, and the cost delta fits the budget. Deciding the bar after seeing the results is not a gate.
3. **The decision is signed and logged.** Six months later, when someone asks why the fleet is still on v4, the answer is one lookup away.

## What to do on Monday

If you have assistants in production without this scaffolding, start with the two cheapest controls: put a gateway in front of every LLM call so identity, policy and budgets apply uniformly, and stand up a small curated eval set so the next model or prompt change is a measured decision instead of a hope. The rollout stages and the audit trail can follow once those two are load-bearing.

We are building Pulse, Lamplit Labs' multi-project self-improving automation product, and its agents operate under exactly this discipline: staged rollout, an eval gate before any change lands, and a signed audit log of every action - the same rigour we described when writing about [how Pulse improves this very blog]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}). Pulse is coming soon - if governing autonomous agents is on your roadmap, that is the problem we are building it to solve.

The organisations that get real value from LLM assistants will not be the ones that adopted fastest. They will be the ones that can prove, from a log and a gate, what their assistants did and why.
