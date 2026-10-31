---
layout: post
title: "AI SDLC: Seven Practices That Held Up After a Year of Coding Agents in .NET Teams"
date: 2026-10-13 00:00:00 +0200
categories: ai
tags: ai sdlc ai-sdlc dotnet csharp devops testing enterprise
author: manishtiwari25
description: "Twelve months of coding agents on nine .NET services: the seven AI SDLC practices we kept, the three we dropped, and the before-and-after numbers."
image:
  path: /assets/img/headers/ai/ai-sdlc-practices.webp
  alt: "Header card for AI SDLC practices listing scope contracts on every task, mutation score instead of line coverage, agent PRs earning a human review and a weekly 20-minute agent retro"
---

Most of the AI SDLC posts on this blog are about one mechanism: a [merge gate]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}), a [hand-off point]({% post_url AI/2026-10-11-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %}), a [flaky-test triage loop]({% post_url AI/2026-10-03-ai-sdlc-flaky-test-triage %}). This one zooms out. After twelve months of coding agents working alongside four teams on nine .NET services, we sat down with the retro notes and the CI data and asked a blunt question: which practices are still enforced, and which did we quietly stop doing? Seven survived, three did not. Here is the list, the reasoning, and the numbers that changed.

![Table of ten AI SDLC practices after twelve months on nine .NET services: scope contract per task, mutation score gate, four machine gates before human review, weekly agent retro and provenance trailers marked Kept with the evidence for each; agent-written ticket descriptions, autonomous dependency bumps to main and agent-generated architecture docs marked Dropped](/assets/img/posts/ai/ai-sdlc-practices-kept-dropped-table.webp){: width="1400" height="820" }

## The seven we kept

**1. A scope contract on every agent task.** Each task the agent picks up carries a small YAML block: allowed paths, forbidden directories, and whether public API changes are permitted. The scope-diff gate compares the PR against it. This was the single most frequent blocker (61 of 412 agent PRs in one quarter) and the one engineers least wanted to remove, because every block was a change nobody had asked for.

**2. Mutation score, not line coverage, as the test gate.** Agent-written tests reach high line coverage trivially and assert very little. On the first batch we measured 91% coverage against a 58% mutation score. We set the gate on the mutation score of the files touched and the agent's test prompts changed within two weeks to add real assertions. The [mutation testing post]({% post_url AI/2026-10-01-llm-test-generation-mutation-testing-dotnet %}) has the setup.

**3. Agent PRs earn a human review.** Four machine gates run first; the human sees the PR only after it passes them. The point is not distrust of the agent but respect for reviewer attention. Review rounds per merged PR dropped from 2.1 to 1.4 because reviewers stopped discovering that the build was red.

**4. A weekly, time-boxed agent retro.** Twenty minutes per team, Monday morning, from a fixed template: PRs opened/merged/blocked, the top blocking gate, mutation failures, injection alerts, and one open question - "did an agent do anything that surprised you?". The action items become issues automatically. This is what turned prompt-template fixes from a quarterly chore into a weekly habit.

![Filled-in weekly agent retro checklist for the payments-api team: 23 agent PRs opened, 14 merged, 9 blocked; top blocking gate scope diff with an action to add Migrations to forbidden dirs; two mutation gate failures with an action to update the test prompt template; zero prompt-injection alerts; human review time 3.1 hours against a 4-hour target](/assets/img/posts/ai/ai-sdlc-practices-weekly-agent-retro.webp){: width="1400" height="760" }

**5. Provenance trailers on every agent commit.** Which agent, which model version, which task id, which prompt template hash. Boring until an auditor asks "who wrote this and why", which happened three times this year and was answered in minutes each time. It plugs into the same [audit trail]({% post_url AI/2026-10-07-enterprise-ai-audit-trail-azure-openai-apim %}) we keep for production LLM calls.

**6. Sandboxed build and test runs.** The agent's branch builds in an isolated runner with no production secrets and an egress allow-list. We added this after the [prompt-injection work]({% post_url AI/2026-10-11-ai-sdlc-prompt-injection-defences-for-coding-agents %}) showed how easily a dependency README could steer an agent; the sandbox means a steered agent still cannot reach anything that matters.

**7. The agent fixes its own red build before a human looks.** If the machine gates fail, the failure log is fed back to the agent for up to two attempts before the PR is parked. Roughly 40% of initially-red agent PRs went green on the first retry, almost all of them compile errors from a stale branch.

## The three we dropped

**Agent-written ticket descriptions.** It sounded like a free win. In practice engineers rewrote about 70% of them, usually because the agent described what the code did rather than what the user needed. Now the engineer writes two sentences and the agent expands them into the scope contract instead.

**Fully autonomous dependency bumps to main.** We let minor and patch bumps merge without review for a quarter. Two behaviour regressions later (one serializer default, one logging sink), they go through the normal gates, as described in the [dependency upgrades post]({% post_url AI/2026-10-05-ai-sdlc-llm-assisted-dependency-upgrades-dotnet %}).

**Agent-generated architecture docs.** Stale within a sprint, read by nobody, and a source of confident wrong answers for the next agent that consumed them. We deleted them and kept a hand-written one-pager per service.

## What moved

![Horizontal bar chart comparing Q4 2025 before and Q3 2026 after across nine .NET services: median PR cycle time 38 to 19 hours, review rounds per merged PR 2.1 to 1.4, change-failure rate 14 to 9 percent, escaped defects per sprint 6 to 4, mutation score on new tests 58 to 79 percent](/assets/img/posts/ai/ai-sdlc-practices-before-after-metrics.webp){: width="1400" height="700" }

Same nine services, same four teams, Q4 2025 against Q3 2026. Median PR cycle time halved, which is mostly the agent fixing its own red builds and reviewers seeing fewer broken PRs. Change-failure rate and escaped defects both fell, though not dramatically, and we attribute that to the mutation gate more than to anything else. The honest caveat: the teams also got a year better at their own jobs in that time, and we have no control group. Take the direction and the ordering, not the decimals, and compare with [what the published evidence says]({% post_url AI/2026-10-09-ai-sdlc-what-published-evidence-says-cycle-time-stability-defects %}) before quoting any of it to your management.

## If you are starting now

Start with practices 1, 2 and 3 - they are all CI configuration and need no process change. Add the weekly retro the moment more than one team is using agents, because that is when prompt templates start to drift apart. Leave provenance until your first audit question if you must, but you will wish you had it earlier.

## Related

- [AI SDLC: How We Evaluate and Gate AI Coding-Agent Pull Requests Before Merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: Where Coding Agents Fit in the Development Lifecycle - Four Hand-off Points]({% post_url AI/2026-10-11-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %})
- [AI SDLC: What the Published Evidence Actually Says About Cycle Time, Delivery Stability and Defect Rate]({% post_url AI/2026-10-09-ai-sdlc-what-published-evidence-says-cycle-time-stability-defects %})
- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest]({% post_url AI/2026-10-01-llm-test-generation-mutation-testing-dotnet %})
