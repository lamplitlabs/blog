---
layout: post
title: "AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase"
date: 2026-10-03 09:00:00 -0500
categories: ai
tags: ai sdlc dotnet csharp copilot devops testing enterprise
author: manishtiwari25
description: "Phase-by-phase AI-assisted SDLC for .NET teams: what to delegate to AI in plan, design, code, test, release and operate, and which gate stays human."
image:
  path: /assets/img/headers/ai/ai-sdlc-dotnet-teams.webp
  alt: "Six-phase diagram of an AI-assisted software development lifecycle (plan, design, code, test, release, operate) listing what AI drafts in each phase and the human gate that stays in place"
---

"We use AI in our SDLC" usually means one thing: developers have Copilot turned on in Visual Studio. That is a fine start, but it leaves most of the lifecycle untouched and gives the team no shared rule about what the AI may do on its own. This post walks the six phases of a typical .NET delivery pipeline and, for each one, lists what I have found worth delegating to an LLM, what has burned us, and the one gate I keep firmly human.

![AI-assisted SDLC: six phases, what AI drafts and which gate stays human](/assets/img/headers/ai/ai-sdlc-dotnet-teams.webp)

{% include feed-ads.html %}

## The rule that makes everything else work

**AI drafts, humans decide, and something deterministic checks.** Every suggestion below follows that shape. The model produces a first version; a person owns the decision to accept it; and wherever possible a compiler, a test suite, an analyzer or a policy check verifies the output before a human even looks at it. If a step has no deterministic check, keep the human review heavier, not lighter.

## 1. Plan

**Delegate:** turning a vague feature request into a first draft of user stories and acceptance criteria, splitting an epic into vertical slices, and listing risks you might not have thought of ("what breaks if this runs in two regions?").

**What burned us:** estimates. Models are confidently wrong about effort because they do not know your codebase's debt. Use them to enumerate work, never to size it.

**Human gate:** the product owner signs off scope. A story that only an LLM has read is not a story yet.

## 2. Design

**Delegate:** drafting an Architecture Decision Record from a bullet list of options, producing a first threat model ("list STRIDE threats for an Azure Function that writes to Cosmos DB from a public HTTP trigger"), and generating sequence diagrams in Mermaid or Draw.io XML that you then fix by hand.

**What burned us:** hallucinated SDK capabilities. A design that leans on a `CosmosClient` option that does not exist costs a sprint. Verify every API claim against the actual NuGet package before the design is accepted.

**Human gate:** an architect reviews the ADR and owns the decision.

## 3. Code

**Delegate:** completions, boilerplate (DTOs, mapping, `IOptions` binding), explaining a legacy method before you touch it, and the first pass of a refactor you then read line by line.

**What burned us:** quiet behaviour changes inside "equivalent" refactors, and `using` directives for packages the project does not reference. Both are caught deterministically: the build fails, or an analyzer such as `Microsoft.CodeAnalysis.NetAnalyzers` flags the change.

A cheap, high-value habit is to make the AI explain the diff it produced in the PR description, then check that explanation against the code. When the two disagree, the code is usually wrong.

**Human gate:** pull request review by someone who did not author the prompt.

## 4. Test

**Delegate:** generating xUnit cases for a pure function, proposing edge cases you did not list (empty collections, time zones, Unicode), and writing the regression suite for your own prompts, as covered in [Testing LLM Prompts in .NET]({% post_url AI/2026-10-02-testing-llm-prompts-dotnet %}).

**What burned us:** tests that assert what the code currently does rather than what it should do. Generated tests cement bugs if nobody reads the expected values. Treat generated tests as a draft that needs the same review as production code.

**Human gate:** CI must stay green, and coverage thresholds are enforced by the pipeline, not by a reviewer remembering to check.

## 5. Release

**Delegate:** release notes from merged PR titles, a changelog summary for non-technical stakeholders, and a rollout checklist based on the services the diff touched.

**What burned us:** release notes that mention features that were reverted. Generate from the final merged commit list, not from the sprint board.

**Human gate:** a person approves the deployment. In Azure DevOps or GitHub Actions this is an environment approval, and it is the one step I would never automate with an LLM in the loop.

## 6. Operate

**Delegate:** first-pass log triage ("group these 400 Application Insights exceptions by probable root cause"), incident timeline summaries for the post-mortem, and runbook lookup in natural language.

**What burned us:** an LLM that confidently names the wrong root cause anchors the whole on-call team on it. Present AI triage as a hypothesis with the evidence it used, never as a conclusion.

**Human gate:** the on-call engineer decides what action to take.

## Putting it in a team agreement

A one-page working agreement is enough. Ours has four lines:

1. AI output is a draft. The person who accepts it owns it.
2. Every AI-touched artefact passes a deterministic check before human review: build, tests, analyzers, policy.
3. No AI in the deploy approval or in anything that handles customer data without a documented data-handling review.
4. Prompts that ship to production are code: versioned, tested and reviewed.

Start with code and test, where the deterministic checks already exist, and extend outward only once the team trusts the pattern.

## Summary

- Map each SDLC phase to what AI drafts and which gate a human owns.
- Pair every AI step with a compiler, test or policy check; keep review heavier where no such check exists.
- Keep deploy approval and customer-data handling human and documented.
- Write the agreement down so "we use AI" means the same thing to everyone on the team.
