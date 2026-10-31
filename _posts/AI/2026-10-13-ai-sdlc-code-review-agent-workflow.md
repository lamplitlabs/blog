---
layout: post
title: "AI SDLC: A Code-Review Agent Workflow That Reviewers Actually Trust"
date: 2026-10-13 00:00:00 +0200
categories: ai
tags: ai sdlc ai-sdlc dotnet code-review devops github enterprise
author: manishtiwari25
description: "The four-stage AI code-review agent workflow we run on .NET repos: triage, one review with blocking vs advisory comments, agent re-check, then human review."
image:
  path: /assets/img/headers/ai/ai-sdlc-code-review-agent-workflow.webp
  alt: "Header card for the AI SDLC code-review agent workflow listing four stages: triage the diff, blocking versus advisory comments in one review, agent re-checks after the author pushes, human reviewer sees only unresolved threads"
---

We have written about [how to measure a code-review agent]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %}) and about [gating agent-written pull requests]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}). This post is about the piece in between: the workflow the review agent itself follows on a human-written PR, and why the shape of that workflow matters more than the model behind it. Our first attempt - "comment on everything you notice" - was switched off by two teams within a month. The version below has run on three .NET repositories for a full quarter and nobody has asked to turn it off.

## Why the first version failed

The first agent posted comments as it found them: twenty-two on a 400-line PR, style nits next to a genuine race condition, no indication of which ones mattered. Authors learned to scroll past the agent, reviewers learned to ignore it, and the one real finding per PR was lost in the noise. The ignored-comment rate from the [metrics post]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %}) hit 64%.

The fix was not a better prompt for finding bugs. It was a workflow that separates *what the agent found* from *what the human needs to decide*.

## The four stages

![Screenshot of the code-review agent's single review on an orders-api pull request moving invoice PDF generation to a background worker: a triage line reporting 14 files, medium risk and scope contract OK, two BLOCKING comments about a missing CancellationToken and an unbounded retry loop, two ADVISORY comments about a missing Location header and a weak test assertion, one RESOLVED thread closed by the agent, and a summary requesting human review after blocking items close](/assets/img/posts/ai/ai-sdlc-code-review-agent-workflow-pr-review.webp){: width="1400" height="900" }

**1. Triage before reading.** The agent first classifies the diff: files touched, lines, whether it crosses into risky directories (`Infrastructure/Queue`, `Migrations`, anything under `Auth`), and whether it respects the task's scope contract. The result is one line at the top of the review. This takes about forty seconds and does two things: it picks the review depth (a docs-only PR gets a skim, a queue change gets the full checklist) and it tells the human reviewer at a glance what kind of PR this is.

**2. One review, two severities.** Everything the agent has to say lands as a single GitHub review, not a trickle of comments. Each comment carries a `BLOCKING` or `ADVISORY` tag. Blocking means "I believe this is a defect and here is the concrete fix"; advisory means "worth a look, merge without it if you disagree". The agent is prompted to cap blocking comments at five and to drop anything it cannot phrase as a specific change. Style, naming and formatting are not allowed at all - the formatter owns those.

**3. The agent re-checks its own threads.** When the author pushes, the agent re-runs only against the threads it opened. If the fix landed, it resolves the thread itself with a one-line note. If the author replied with a reason instead of a change, the agent either accepts the reason (and says why) or restates the concern once. It never argues a third time; the thread stays open for the human. In Q3, 71% of agent threads were closed by the agent without a human touching them.

**4. The human sees what is left.** Only after blocking threads are closed does the agent request review from the team's reviewer group. The reviewer opens a PR with the triage line, the resolved threads collapsed, and the unresolved ones at the top. That is the whole point: the human reviews the disagreement, not the diff from scratch.

## What moved

![Diagram of the four workflow stages - triage, review, re-check, human - with time per stage, followed by a before-and-after table across 1,106 pull requests in Q3: median human review time 31 to 14 minutes, review rounds 2.3 to 1.5, 83 percent of blocking comments accepted, staging defects 17 to 9 per quarter, cost 0.41 dollars per PR](/assets/img/posts/ai/ai-sdlc-code-review-agent-workflow-stages-metrics.webp){: width="1400" height="700" }

Across 1,106 PRs on three repositories in Q3:

| Metric | Before | After |
| --- | --- | --- |
| Median human review time per PR | 31 min | 14 min |
| Review rounds per merged PR | 2.3 | 1.5 |
| Blocking comments accepted by the author | - | 83% (9% ignored, 8% disputed) |
| Defects found in staging after merge | 17 / quarter | 9 / quarter |
| Model cost per PR | - | $0.41 |

The number we watch most closely is the ignored rate on blocking comments. At 64% the agent was noise; at 9% it is a colleague. When it creeps above 15% for a repo, we read the ignored comments at the weekly agent retro and usually find one checklist item that is wrong for that codebase.

## Implementation notes

- The agent runs as a GitHub App on `pull_request` and `pull_request_review_comment` events, with a scoped token that can post reviews and resolve its own threads and nothing else.
- Review depth is chosen from the triage result, not from the PR size alone. A 30-line change to a retry policy gets the full queue checklist.
- The blocking/advisory split is enforced in the output schema (a structured-output call), not by asking nicely. A comment without a severity and a suggested change is dropped before posting.
- Every review carries a provenance footer: model version, prompt template hash, triage classification. When a reviewer disagrees with the agent, that footer is what the retro uses to find the template to fix.
- The agent is advisory to the merge gate, never the gate itself. A human can merge over an open blocking thread; the gate only requires that a human did so explicitly.

## Related

- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %})
- [AI SDLC: How We Evaluate and Gate AI Coding-Agent Pull Requests Before Merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: Human vs Agent PR Review - Measuring Test Coverage Quality With Defect Escape Rate and Mutation Score]({% post_url AI/2026-10-08-ai-sdlc-human-vs-agent-pr-review-test-coverage-quality %})
- [AI SDLC: AGENTS.md Files Coding Agents Actually Follow - Five Rules and One Rework Metric](/posts/ai-sdlc-agents-md-instruction-files-coding-agents-actually-follow/)
