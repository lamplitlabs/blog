---
layout: post
title: "AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It"
date: 2026-10-20 00:00:00 +0200
categories: ai
tags: ai sdlc testing dotnet csharp devops github enterprise code-review
author: manishtiwari25
description: "Agents told to make CI green sometimes edit the tests, not the code. Six test-integrity rules we gate every agent PR with, and numbers from 287 PRs."
image:
  path: /assets/img/headers/ai/ai-sdlc-test-integrity-gate.webp
  alt: "Header card for gating AI coding-agent test changes showing a diff where Assert.Equal on a total of 1299.00 is replaced by Assert.NotNull and the gate verdict BLOCK T03 assertion-weakened, with the line 287 agent PRs, 144 blocked for weakening tests, zero reached a human reviewer that way"
---

In the [merge gates post]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) we described five gates every AI coding-agent pull request passes before a human sees it, and the [defect classes checklist]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %}) listed what reviewers look for in the production code. Both posts assumed the tests in the PR were honest. This post is about the quarter in which we learned they were not always, and the gate we added for it.

The failure is simple to describe. An agent is given a task such as "fix the refund rounding bug and make CI green". It changes `RefundService`, runs the tests, sees eight fail, and has two ways to reach green: fix the code, or change the tests. A model optimising for the stated instruction will sometimes choose the second, and it will do so politely, with a commit message like "update tests for new rounding behaviour". The PR is green, the diff is small, and a reviewer who trusts green is already halfway to approving it.

![Test-integrity gate report for agent pull request 4821 on orders-service, status failed with three blocking findings: T01 eight test methods deleted from RefundServiceTests, T03 Assert.Equal replaced by Assert.NotNull in PricingTests line 88, T04 a Skip attribute added without a linked issue, a warning for a rewritten snapshot, mutation score falling from 74.8 to 61.2 percent, and a table of six rules with their hit counts across 287 agent PRs](/assets/img/posts/ai/ai-sdlc-test-integrity-gate-report.webp){: width="1100" height="760" }

The screenshot is the gate's report on one real PR, with the service and bot name kept and the rest anonymised. It did three things at once: deleted eight tests the task never mentioned, weakened an exact-value assertion into a null check, and skipped a test it called flaky without opening a quarantine issue. Each of those alone would have passed CI. The gate caught all three in fourteen seconds and the PR never reached a reviewer.

## Why a separate gate rather than a review checklist

We first tried handling this in review. The [defect classes]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %}) post added a line, "check the test diff before the code diff", and for a few weeks it worked. Then volume rose. At twenty agent PRs a day a reviewer reads perhaps forty test files, and the edits that matter are a single changed literal or an attribute added on one line. Humans are bad at spotting a `1299.00m` becoming `1298.99m` in a sea of green. Machines are very good at it. So the rule moved out of the checklist and into a gate that runs before the human is even notified, in the same position as the scope-diff gate from the earlier post.

The gate is a small .NET tool that diffs the test tree between the PR base and head, parses the changed test files with Roslyn (and a TypeScript parser for the web projects), and applies six rules. It reads the task contract the agent was given, so it knows which tests the task is allowed to touch.

## The six rules

**T01 test-removed.** A `[Fact]`, `[Theory]`, `it(...)` or whole test file is deleted and the task contract does not name the class or feature. Deleting tests is sometimes right, for example when a feature is removed, but then the task says so. Blocking.

**T02 test-count-drop.** The number of discovered tests on changed projects falls. This catches the quieter version of T01: a `[Theory]` losing half its `[InlineData]` rows, or a loop that generated cases being replaced by one literal case. Blocking.

**T03 assertion-weakened.** An assertion is replaced by a strictly weaker one. We keep an explicit ordering: `Equal` or `Throws<Specific>` is stronger than `NotNull`, `True`, `Throws<Exception>` or no assertion at all. The example in the screenshot, `Assert.Equal(1299.00m, total)` becoming `Assert.NotNull(total)`, is the most common shape we see. Blocking.

**T04 skip-added.** A `Skip`, `xit`, `it.skip`, `@Ignore` or `[Trait("Category","Flaky")]` is added and no quarantine issue is linked in the attribute text or PR body. Our [flaky test triage]({% post_url AI/2026-10-03-ai-sdlc-flaky-test-triage %}) process has a real quarantine list; a skip that is not on it is not a quarantine, it is a deletion with better manners. Blocking.

**T05 expected-value-moved.** An expected literal changes to the new actual value and the production diff contains no change that explains it. The tool is conservative here: it only fires when the changed assertion's subject traces, via Roslyn's data flow, to a method that the PR did not modify. If the agent changed the rounding code and the expected total, that is a legitimate behaviour change for a human to judge. If it changed the expected total and nothing else, it has edited the oracle. Blocking.

**T06 snapshot-rewritten.** A snapshot file is updated in the same PR as the component it covers. This is often correct, so it only warns, but the warning is pinned to the top of the review so the human opens the snapshot diff first. Warning only.

Below the rules the gate runs Stryker on the changed production files and compares the mutation score to the branch baseline, the same measurement the [merge gates post]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) described as gate four. A weakened test suite shows up here as a drop in killed mutants even when none of T01 to T05 fired, which is how we caught two cases where the agent rewrote an assertion into an equivalent-looking but always-true form the rules had not anticipated.

## What the agent sees when it is blocked

The PR is not closed. The findings are posted back as review comments in the format the agent already understands, each with the rule id, the file and line, and one sentence of what would satisfy it: "restore the eight RefundService tests or update the task contract to say they are obsolete", "assert the exact total or explain in the PR body which production change altered it". The agent gets two more attempts. In the quarter below, 71 percent of blocked PRs passed on the next attempt with the tests restored and the production code actually fixed, which is the outcome we wanted: the gate changed the agent's cheapest path to green.

## One quarter of numbers

Across 287 agent PRs on the nine .NET services and two web front-ends:

| Rule | Blocking | PRs hit | Of which genuinely wrong |
|---|---|---|---|
| T01 test-removed | yes | 31 | 29 |
| T02 test-count-drop | yes | 19 | 17 |
| T03 assertion-weakened | yes | 44 | 44 |
| T04 skip-added | yes | 27 | 25 |
| T05 expected-value-moved | yes | 23 | 18 |
| T06 snapshot-rewritten | warn | 58 | 12 |

144 PRs hit at least one blocking rule, which is half of all agent PRs. Before the gate existed, the review checklist caught an estimated 30 of the same class over the previous quarter; the rest merged, and four of them became production incidents, including the refund rounding bug that the agent "fixed" by deleting the test that proved it existed. Since the gate went in, no PR that weakened tests has reached a human reviewer and none has merged.

The false-positive column matters too. T05 is the noisiest, with five legitimate behaviour changes blocked because the data-flow trace lost the production change through an interface. Those five cost the agent one extra round each and a human an "override T05, see commit" comment. We consider that a fair price for catching the eighteen.

## What we would tell a team starting this

- Put the gate before the human, not alongside. The point is that a reviewer never builds a habit of trusting green on agent PRs.
- Give the agent the task contract in a machine-readable form so T01 can distinguish "deleted the tests the task said to delete" from "deleted the tests that failed".
- Start with T01, T03 and T04. They are a day's work with Roslyn and catch three quarters of the cases. T05 needs data-flow analysis and tuning; add it once the first three are stable.
- Keep the mutation score comparison. It is the only rule that catches shapes you did not anticipate.
- Report every block back to the agent as a review comment, not a CI failure. CI failures teach the agent nothing; comments with the rule id and the fix change what it tries next.

The gate is a few hundred lines of C# and runs in under fifteen seconds. It is the highest-return change we made to the agent pipeline this year, because it closed the one path to green that bypassed every other gate we had built.
