---
layout: post
title: "AI SDLC: How We Evaluate and Gate AI Coding-Agent Pull Requests Before Merge"
date: 2026-11-20 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp devops testing github enterprise
author: manishtiwari25
description: "The five merge gates we run on every AI coding-agent pull request for .NET services: provenance, scope diff, sandboxed tests, mutation score and human review."
image:
  path: /assets/img/headers/ai/ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge.webp
  alt: "Header card for gating AI coding-agent pull requests showing five gates every agent PR must pass, 11% blocked by the mutation gate and zero agent PRs merged without a human"
---

The [hand-off points post]({% post_url AI/2026-11-18-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %}) placed a coding agent in the lifecycle and said its branch must go through "checks it cannot skip". This post is those checks. Once an agent can open twenty pull requests a day, the review queue becomes the bottleneck, and the temptation is to read agent PRs less carefully because "the tests are green". We went the other way: an agent PR has to earn its way to a human with more machine evidence than a human PR, and the human only sees it once it has. Below is the gate pipeline we run on nine .NET services, what each gate blocks, and the numbers from one quarter.

![Pipeline of five merge gates for AI coding-agent pull requests, provenance, scope diff, sandboxed build and tests, mutation score plus SAST and human review, followed by a table of 412 agent PRs in one quarter: 61 blocked by scope diff, 48 by build and tests, 45 by mutation and SAST, 37 by human review and 221 merged](/assets/img/posts/ai/ai-sdlc-agent-pr-merge-gates-results.webp){: width="1400" height="820" }

## Why agent PRs need their own gate

A human PR carries implicit evidence: the author ran it, the author understood the ticket, the author knows which files are off limits. An agent PR carries none of that unless you record it. The failure modes are also different. Humans ship bugs; agents ship *plausible* bugs - tests that assert nothing, a retry loop added to make a flaky test pass, a public method renamed because the compiler suggested it. Classic CI catches none of those because the build is green. So the question we asked was not "is this PR correct?" but "what evidence would make a reviewer trust it in ten minutes?", and we turned each answer into a gate.

## Gate 1: provenance

Every agent PR must carry a machine-readable trailer: which agent, which model and version, the task id, and a hash of the prompt and tool configuration. A GitHub Action rejects the PR if the trailer is missing or if the task id does not resolve to an open issue. This costs nothing and pays twice: a reviewer can see at a glance that this came from an agent, and when a merged agent change later misbehaves we can find every PR produced with the same prompt version.

```yaml
# .github/workflows/agent-pr-gate.yml (excerpt)
- name: Require agent provenance trailer
  if: contains(github.event.pull_request.labels.*.name, 'agent')
  run: |
    body="${{ github.event.pull_request.body }}"
    for key in Agent Model Task-Id Prompt-Hash; do
      echo "$body" | grep -q "^$key:" || { echo "missing $key trailer"; exit 1; }
    done
```

## Gate 2: scope diff against the task contract

The task contract from the hand-off post lists which projects and folders the agent may touch. Gate 2 diffs the PR file list against that allow-list. Anything outside it - `Directory.Packages.props`, a shared `Infrastructure` project, a CI workflow, a test it was not asked to change - fails the gate with the offending paths in the check output. This was the single largest blocker in the quarter (61 of 412 PRs). Nearly all were honest: the agent fixed a bug and "tidied" a neighbour, or bumped a package to make something compile. Both are exactly the changes a tired reviewer waves through, and exactly the ones that break another team.

```bash
# scope-check.sh: fail if the PR touches files outside the task's allow-list
allow="$(yq '.scope[]' task.yml)"
changed="$(git diff --name-only origin/main...HEAD)"
bad="$(printf '%s\n' "$changed" | grep -v -F -f <(printf '%s\n' "$allow") || true)"
[ -z "$bad" ] || { echo "out of scope:"; echo "$bad"; exit 1; }
```

Deleted or weakened tests are treated as out of scope by default, regardless of path. An agent that needs to delete a test has to say so in the PR body, and the reviewer has to agree.

## Gate 3: build and tests in a clean sandbox

Agents run tests while they work, but they run them in their own working environment, which usually has network access, cached packages and whatever state the previous attempt left behind. Gate 3 re-runs `dotnet build` and `dotnet test` in a fresh container with no outbound network and a restored, locked package graph. Forty-eight PRs that were green in the agent's own run went red here. The common cause was a test that quietly hit a real HTTP endpoint or a local SQL instance the agent had started. This gate reuses the same sandbox image as the [flaky test triage]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %}) work, so a failure here is also fed back into that classifier.

## Gate 4: mutation score and static analysis

A green test suite from an agent is only meaningful if the tests can fail. We run Stryker.NET on the projects the PR touched and require the mutation score on *changed files* to be at or above the branch baseline; the approach is the one from the [LLM test generation post]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %}). In parallel, the standard SAST and secret scan runs with "no new findings" rather than "zero findings", so legacy debt does not block the agent but the agent cannot add to it. Forty-five PRs failed this gate; two thirds were assertion-free or snapshot-only tests, the rest were a hard-coded connection string or a string-concatenated SQL query copied from an older part of the codebase.

```ini
# stryker-config.json (relevant part)
{
  "stryker-config": {
    "mutate": [ "**/*.cs", "!**/Migrations/**" ],
    "since": { "target": "origin/main" },
    "thresholds": { "break": 0 }
  }
}
```

The `break: 0` is deliberate: Stryker itself never fails the build. A small script compares the changed-file score with the baseline stored from `main` and fails only on regression, which keeps the gate stable when the overall score drifts.

## Gate 5: a human who owns the code

Only after gates 1-4 pass does the PR get a reviewer, assigned from `CODEOWNERS` as usual. Two rules differ from human PRs. First, the agent cannot request its own review or re-request after pushing; a new push resets gates 2-4 and the reviewer is notified only when they are green again. Second, the review checklist is short and specific to agents: does the change do what the task asked and nothing more, is any public API surface changed, would you have written it this way. Thirty-seven PRs were rejected here, almost all of them correct code at the wrong level of abstraction. That is the category no automated gate catches, and it is why the human stays.

## What the quarter looked like

Across 412 agent PRs on nine services, 221 merged (54%). The rest were blocked roughly evenly across the four machine gates, with scope diff the largest. Two numbers mattered more to the team than the merge rate. Median review rounds for merged agent PRs were 1.4 against 2.1 for human PRs over the same period, because the reviewer rarely saw a PR that was still broken. And the number of agent PRs merged without a human approval was zero, which is the number we have to be able to show an auditor, and which ties directly into the [audit trail]({% post_url AI/2026-10-26-enterprise-ai-audit-trail-azure-openai-apim %}) work.

These numbers come from one internal programme on one kind of codebase, so take the shape rather than the percentages. What generalised in conversations with other teams was the ordering: cheap deterministic gates first, the expensive mutation run only for PRs that survive them, and the human last so that their attention is spent on judgement rather than on finding out that the build is red.

## Where we are going next

Two gates are still manual that should not be. Scope contracts are written by hand per task; we are generating a default from the issue's linked files and letting the engineer widen it. And the mutation baseline is per branch, not per file, which lets a PR that touches a well-tested file and a badly-tested file average its way through. If you run a similar gate and have solved either, I would like to hear how.

## Related

- [AI SDLC: Where Coding Agents Fit in the Development Lifecycle - Four Hand-off Points]({% post_url AI/2026-11-18-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %})
- [AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %})
- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %})
