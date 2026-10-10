---
layout: post
title: "AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines"
date: 2026-10-16 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp testing xunit devops enterprise ci
author: manishtiwari25
description: "How we let an LLM cluster flaky .NET test failures by root cause, auto-quarantine with an expiry and route real bugs to humans, with one sprint of numbers."
image:
  path: /assets/img/headers/ai/ai-sdlc-flaky-test-triage.webp
  alt: "Header card for AI-assisted flaky test triage showing 412 failures per week, 9 root-cause clusters, 83% auto-classified and 31 quarantined tests"
---

In the [phase-by-phase AI SDLC post]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}) the test phase got one line: "AI writes tests, humans decide what they assert". That leaves out the ugliest part of a mature .NET test suite, which is not writing tests but keeping a red pipeline honest. On a repo with ~6,000 xUnit tests we were seeing about 400 non-deterministic failures a week. Nobody triaged them; people hit **Re-run failed jobs** and moved on. This post is about the triage agent we put in front of that button, what it is allowed to do on its own, and what it is not.

![Bar chart of one sprint of flaky test failures grouped by AI-assigned root cause: shared test DB state 118, async timing 96, port collision 61, time zone 44, real network dependency 38, order-dependent fixtures 27, genuine product bug 17, unclassified 11](/assets/img/posts/ai/ai-flaky-test-triage-clusters.webp){: width="1400" height="820" }

## The problem with "re-run failed jobs"

A retry hides two different things behind one green check mark:

1. A test that is genuinely non-deterministic (shared state, timing, a port already in use). Retrying fixes the symptom and the test stays flaky forever.
2. A product bug that only shows up under load or on a particular ordering. Retrying makes it disappear until it ships.

Telling them apart needs someone to read the stack trace, the test body and the last few failures of the same test. That is boring, repetitive and text heavy, which is exactly the shape of work an LLM is good at, as long as the decision it produces is checked by something deterministic.

## What the agent does

The pipeline runs on GitHub Actions. On a failed `dotnet test` run the workflow uploads the `.trx` file and a small .NET worker (a hosted service reusing the Azure OpenAI client setup from the [structured outputs post]({% post_url AI/2026-09-29-structured-outputs-azure-openai-dotnet %})) does four steps.

### 1. Collect evidence, not just the message

For each failed test the worker builds a compact evidence bundle:

- the test name, failure message and the first 40 lines of the stack trace from the `.trx`;
- the test method body and its fixture class, pulled with Roslyn so the model sees `[Collection]`, `IClassFixture<>` and any `static` fields;
- the last 20 outcomes of the same test from the Actions API, with timestamps and runner labels;
- whether the test passed on the retry that the developer already triggered.

Everything is truncated to a budget of about 3,000 tokens per test. Without the fixture class the model guesses; with it, "this fixture shares a `static HttpClient` and a port number" is usually visible in the first screen.

### 2. Classify with a fixed label set

The prompt asks for a JSON object validated against a schema, never free text:

```csharp
public sealed record TriageVerdict(
    string TestId,
    RootCause Cause,          // enum below
    double Confidence,        // 0..1
    string Evidence,          // one sentence quoting the trace or code
    string SuggestedFix);     // one sentence, may be empty

public enum RootCause
{
    SharedTestState, AsyncTiming, ResourceCollision, TimeZoneOrClock,
    RealNetworkDependency, OrderDependentFixture, ProductBug, Unknown
}
```

The label set is deliberately small and stable. Every label maps to a known fix pattern on our wiki (`SharedTestState` → use a per-test database name via `Respawn`; `TimeZoneOrClock` → inject `TimeProvider`), so the verdict is actionable without anyone re-reading the trace. `Unknown` is a legitimate answer and the prompt says so; a model forced to pick always picks something.

### 3. Decide with code, not with the model

The agent's verdict is advice. A plain C# policy decides what happens:

```csharp
static TriageAction Decide(TriageVerdict v, TestHistory h) => v switch
{
    { Cause: RootCause.ProductBug } => TriageAction.OpenBugAndBlockMerge,
    { Confidence: < 0.7 } => TriageAction.AskHuman,
    _ when h.FailureRate(days: 14) < 0.02 => TriageAction.Ignore, // one-off
    _ when h.FailureRate(days: 14) < 0.20 => TriageAction.QuarantineWithExpiry(days: 14),
    _ => TriageAction.AskHuman // too flaky to hide, needs a fix now
};
```

Two rules were non-negotiable from the start:

- **`ProductBug` always blocks.** A false positive costs a human ten minutes. A false negative ships a bug. The policy is asymmetric on purpose.
- **Quarantine always expires.** A quarantined test gets `[Trait("Quarantine", "2026-10-30")]` and a GitHub issue assigned to the code owner. A separate deterministic check fails the build when a quarantine date is in the past. Without the expiry, quarantine is deletion with extra steps.

### 4. Open the fix PR for the boring clusters

For `SharedTestState`, `TimeZoneOrClock` and `ResourceCollision` with confidence above 0.9, the worker hands the evidence bundle and the wiki fix pattern to a coding agent, the same loop described in the [end-to-end GitHub issue post]({% post_url AI/2026-10-04-ai-coding-agent-fix-github-issue-end-to-end %}), with one difference: the PR is only opened if the previously flaky test passes 25 times in a row in a tight loop (`dotnet test --filter FullyQualifiedName=... ` repeated via a small script). The agent proves the fix statistically; a reviewer only checks it did not just delete the assertion.

## The numbers from one sprint

The chart at the top is the first sprint with the policy switched on:

| Cluster | Failures | Action taken |
|---|---|---|
| Shared test DB state | 118 (28%) | 14 tests quarantined, 9 fix PRs opened, 7 merged |
| Async timing / `Task.Delay` | 96 (23%) | Quarantined; fix PRs mostly rejected (see below) |
| Port / resource collision | 61 (15%) | One fix PR (dynamic ports in the fixture) removed the whole cluster |
| Time zone / `DateTime.Now` | 44 (11%) | 6 fix PRs, all merged (`TimeProvider` injection) |
| Real network dependency | 38 (9%) | Quarantined, routed to the team owning the integration |
| Order-dependent fixtures | 27 (7%) | Asked human; 2 real design problems |
| Genuine product bug | 17 (4%) | Merge blocked; 3 confirmed bugs, 14 false alarms |
| Unclassified | 11 (3%) | Human triage |

What moved for users of the pipeline:

- **Retries dropped from ~400 to ~90 a week** after three sprints, mostly from the port collision and time zone clusters, which were a handful of root causes behind hundreds of failures.
- **Median time-to-green on a red PR went from 41 to 12 minutes**, because the comment on the PR now says "known flaky, quarantined until 30 Oct, not your change" instead of nothing.
- **Three real bugs** that had been retried past for months were found in the `ProductBug` cluster. The 14 false alarms cost about two engineer-hours in total. We kept the asymmetric rule.

## Where it was wrong

**Async timing fixes were bad.** The coding agent's favourite fix for a timing issue was a bigger `Task.Delay`. The 25-run proof passed; reviewers rejected nearly all of them. We now exclude `AsyncTiming` from auto-fix and only let the agent propose a diagnosis. Timing bugs need a human to decide what the test is actually waiting for.

**Confidence is not calibrated.** The model's 0.9 and 0.7 are not probabilities. We tuned the thresholds against a hand-labelled set of 200 historic failures (the same golden-set idea from the [RAG retriever evaluation post]({% post_url AI/2026-10-11-evaluating-rag-retriever-golden-set-dotnet %})), and re-check them every time the model deployment changes.

**It needs history to be useful.** On a brand-new repo with no failure history the policy falls through to `AskHuman` for almost everything, which is correct but not helpful. Give it two weeks of `.trx` files before judging it.

## Checklist if you want to try this

1. Start by storing `.trx` files and test outcomes for every run. Without history there is nothing to triage.
2. Pick a label set of under ten root causes and write the fix pattern for each one before writing the prompt.
3. Make the decision a `switch` in code with the asymmetric rule for product bugs.
4. Make quarantine expire and make a deterministic check enforce the expiry.
5. Require a statistical proof (N consecutive passes) before any auto-generated fix PR is opened.
6. Measure retries per week and time-to-green, not "number of tests the AI fixed".

## Related

- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %})
- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %})
