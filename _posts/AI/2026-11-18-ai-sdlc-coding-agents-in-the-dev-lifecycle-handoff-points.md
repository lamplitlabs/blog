---
layout: post
title: "AI SDLC: Where Coding Agents Fit in the Development Lifecycle - Four Hand-off Points"
date: 2026-11-18 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp copilot devops testing enterprise agents
author: manishtiwari25
description: "A practical model for putting AI coding agents into a .NET delivery pipeline: task contract, sandboxed run, deterministic gates and a human review gate."
image:
  path: /assets/img/headers/ai/ai-sdlc-coding-agent-handoff-points.webp
  alt: "Four-stage diagram of coding agents in the software development lifecycle: task contract, sandboxed run, deterministic gates, human review, with a loop-back note that failures return to the task contract"
---

Copilot-style autocomplete sits inside the editor and never leaves it. A *coding agent* is different: it takes a task, works in a repository on its own for minutes or hours, runs the build and tests, and hands back a branch. That changes where it fits in the lifecycle. Autocomplete is a developer tool; an agent is a new participant in the pipeline, and it needs the same things every other participant has - a clear brief, a safe place to work, checks it cannot skip and a person who signs off.

This post describes the four hand-off points I use to place an agent in a .NET team's SDLC. It builds on the phase-by-phase overview in the earlier AI SDLC post and on the end-to-end GitHub issue walkthrough; here the focus is the *boundaries* between the agent and everything else.

![Coding agents in the SDLC: task contract, sandboxed run, deterministic gates, human review](/assets/img/headers/ai/ai-sdlc-coding-agent-handoff-points.webp){: width="1600" height="900" }

{% include feed-ads.html %}

## 1. The task contract: an issue the agent can finish

Most agent failures I have seen were briefing failures. "Fix the flaky checkout test" produces a wandering session; "Make `CheckoutTests.PlacesOrder_WhenStockAvailable` deterministic; the flake is a `DateTime.Now` comparison in `OrderService.cs`; do not change the public API of `IOrderService`" produces a small, reviewable diff.

A task contract that works has four parts:

- **Scope**: which files or projects the agent may touch, and which it must not (`Directory.Build.props`, migrations, anything under `infra/`).
- **Acceptance check**: the exact command that must pass, usually `dotnet test --filter FullyQualifiedName~Checkout` plus the solution build.
- **Non-goals**: refactors, dependency bumps and formatting changes are out unless named.
- **Stop conditions**: when to give up and report instead of trying harder - for example, a change that needs a new NuGet package or a schema change.

Keep contracts in the issue tracker, not in a chat window. An issue is reviewable, linkable from the pull request and survives the session.

## 2. The sandboxed run: a throwaway clone with a budget

The agent does its work in an environment that is cheap to throw away and impossible to abuse:

- A fresh clone or worktree, deleted when the run ends.
- No production secrets. If the build needs a feed token, it is a read-only one scoped to the package source.
- A wall-clock budget and a step budget. An agent that has not converged in 45 minutes is not going to; stop it and read the log.
- Logs kept. The transcript of commands and tool output is the evidence the reviewer reads next to the diff.

For .NET this is mostly plumbing you already own: a CI runner image with the pinned SDK (`global.json`), `dotnet restore --locked-mode` so the agent cannot drift the lockfile, and the usual `dotnet build -warnaserror` so analyzer warnings are a hard stop rather than noise.

```yaml
# Example: a run step the agent cannot shortcut
- run: dotnet restore --locked-mode
- run: dotnet build -c Release -warnaserror --no-restore
- run: dotnet test -c Release --no-build --filter "FullyQualifiedName~Checkout"
```

## 3. Deterministic gates: checks the agent cannot talk its way past

The agent is allowed to iterate against these gates on its own, and that loop is where most of the value is: compile error, fix, failing test, fix, analyzer warning, fix. What it may *not* do is change the gates. In practice that means:

- Build with warnings as errors, analyzers on (`EnableNETAnalyzers`, `AnalysisLevel` pinned).
- The named tests plus the full suite. A green targeted run and a red full run is a report, not a pull request.
- Policy checks you already run in CI: formatting (`dotnet format --verify-no-changes`), licence and vulnerability scans, forbidden-path diffs.
- A diff-shape check: files outside the contract's scope fail the run.

If a gate fails and the agent cannot fix it within scope, the correct outcome is a `blocked` report naming the gate and the attempted fixes. Treat "weakened the test to make it pass" as a defect of the setup, not of the model: the gate should not have been writable.

## 4. Human review: the only path to merge and release

The reviewer gets three things: the diff, the gate results and the run log. The review question is not "is this code good?" alone but "did the agent stay inside the contract, and does the evidence support the claim?" A short checklist:

1. Does the diff touch only in-scope files?
2. Do the test changes *add* assertions rather than delete or loosen them?
3. Is the summary in the PR consistent with the log (the tests it says it ran, it ran)?
4. Would I have accepted this diff from a new team member with the same evidence?

Merge and release approval stay human, and the agent never holds deploy credentials. Everything upstream of that gate can be automated with confidence precisely because this gate is not.

## The loop-back rule

When a run fails a gate or a reviewer rejects it, the fix goes into the **task contract**, not into a longer prompt. Tighten the scope, name the file, add the stop condition that was missing. Contracts improve over time and become reusable templates for common task types: flaky test triage, dependency upgrade within a major version, adding a missing null-check path, writing characterization tests before a refactor.

## Where this does not fit (yet)

- Changes that need a design decision - a new public API, a schema migration, a cross-service contract. Have a human write the design, then hand the agent the implementation contract.
- Work with no deterministic gate. If the only check is "looks right", the review cost eats the gain.
- Anything touching customer data without a documented data-handling review, as in the earlier team-agreement post.

## Summary

- Treat a coding agent as a pipeline participant, not an editor feature: brief it, sandbox it, gate it, review it.
- Write the task contract in the issue tracker with scope, acceptance command, non-goals and stop conditions.
- Run it in a throwaway clone with a time and step budget, read-only tokens and kept logs.
- Make build, tests, analyzers and policy non-negotiable gates the agent iterates against but cannot edit.
- Keep merge and release approval human, and feed every failure back into the contract.

## Related posts

- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase](/posts/ai-sdlc-dotnet-teams/)
- [AI SDLC in Practice: Letting a Coding Agent Triage and Fix a GitHub Issue End-to-End](/posts/ai-coding-agent-fix-github-issue-end-to-end/)
- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It](/posts/ai-sdlc-code-review-agent-metrics/)
