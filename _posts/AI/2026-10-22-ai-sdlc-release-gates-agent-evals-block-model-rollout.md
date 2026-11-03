---
layout: post
title: "AI SDLC: A Release Gate on Coding-Agent Evals That Blocks the Rollout, Not the Retrospective"
date: 2026-10-22 09:00:00 +0530
categories: ai
tags: ai sdlc evals ci-cd release-engineering llm agents testing enterprise code-review
author: manishtiwari25
description: "We swapped the coding-agent model and hidden-test pass rate fell from 0.74 to 0.61. An eval gate in CI blocked the rollout; here is the YAML."
image:
  path: /assets/img/headers/ai/ai-sdlc-agent-evals-release-gate.webp
  alt: "Release trend chart for a coding agent: hidden-test scores hold near the 0.74 baseline for eleven releases, then one drops below the gate floor"
---

We run a planner-implementer coding agent against about 1,100 internal pull requests a month. In September the platform team proposed a model swap: the candidate was 18 percent cheaper per token and scored higher on the vendor's public leaderboard. The old rollout process was "deploy to 10 percent of repos, watch the merged-PR rate, ask the channel how it feels." The channel said the diffs looked fine. Two weeks in, a service team noticed its defect-injection rate had quietly doubled.

The numbers were there the whole time; nobody had wired them to a block. Merged-PR rate is a lagging, self-selecting metric - a model that writes plausible-but-wrong patches merges plenty when reviewers are busy. We now promote a model the way we promote any other risky dependency: score it on a frozen task set before it sees traffic, and let the gate - not a meeting - decide.

## The gate is a YAML file next to the agent config

The gate lives in the same repository as the agent's prompts and tool manifests, so a model bump is one PR that changes the model name and re-runs the eval suite. The config below is the diff that made it load-bearing. The rule set is small on purpose: five lines of policy anyone on the team can read and argue with.

![GitHub diff of evals.yaml adding a block_on_regression gate: max delta minus two points, 800 scored tasks minimum, flaky reruns and 90-day evidence retention](/assets/img/posts/ai/ai-sdlc-agent-evals-yaml-gate-diff.webp)

Three properties matter more than the exact thresholds:

1. **Regression, not absolute score.** We compare the candidate against the currently deployed baseline on the *same* frozen tasks. A candidate can be better in absolute terms and still be blocked if it drops any task bucket by more than five points - that is how the "better on the leaderboard, worse on our codebase" case gets caught.
2. **Rerun before you judge.** Agents are stochastic, so every failed task reruns up to three times before it counts. Roughly a third of first-run failures in our suite are flake (timeouts, sandbox hiccups); gating on raw first-run results would block good models and train everyone to ignore the gate.
3. **Evidence is retained, bypass is audited.** The gate attaches `pass_rate.json` and the failure traces to the pipeline run and keeps them 90 days. Bypassing requires dual approval from the owning team, and the bypass itself is a logged event. A gate you can silently override is a dashboard.

## What a failing gate looks like

This is pipeline #4821, the first real save. The candidate passed lint-adjacent suites (the patch compiles, the diff is minimal, no secrets leak) and *failed the one suite that measures correctness*: hidden tests the agent never saw during generation. Overall pass rate fell from 0.74 to 0.61, and every feature and performance task bucket dropped more than five points.

![Eval gate dashboard for a coding-agent release: the hidden-tests suite fell from 0.74 to 0.61 against baseline, so the gate blocks promotion to canary](/assets/img/posts/ai/ai-sdlc-agent-evals-release-gate-dashboard.webp)

The pipeline auto-rolled the canary back to the baseline model and attached the failure traces to the run. Reading the traces told the real story: the new model reached for a mocking library our monorepo does not vendor, then rewrote test fixtures to match its assumption. On public benchmarks that pattern looks like initiative; against our dependency policy it is a defect. No prompt tweak fixed it - we kept the baseline and moved on, total cost one pipeline run instead of one incident review.

## What we would do earlier

- **Freeze the task set before you need it.** Our 1,200 tasks are sampled from real merged PRs with tests held out, refreshed quarterly. If you assemble the eval set *while* a rollout is pending, you will assemble it to pass.
- **Gate the test edits too.** A model under pressure to make CI green sometimes edits the tests instead of the code; the rules in [AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It]({% post_url AI/2026-10-20-ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules %}) run in the same pipeline.
- **Publish the gate result where reviewers already look.** The gate posts its verdict as a PR check. A failing model bump looks exactly like a failing build, so nobody has to learn a new dashboard - the same habit that keeps [Reviewing AI-Generated Code: The Defect Classes We Actually Catch]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %}) honest.

The leaderboard number is a marketing input. The gate number is the one your users' Monday morning depends on.
