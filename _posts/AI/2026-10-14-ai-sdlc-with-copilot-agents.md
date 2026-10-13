---
layout: post
title: "AI SDLC with Copilot Agents: From Spec Issue to Agent PR to Review, End to End"
date: 2026-10-14 00:00:00 +0200
categories: ai
tags: ai sdlc ai-sdlc copilot agents dotnet code-review github devops enterprise
author: manishtiwari25
description: "One .NET issue walked through the agent-driven SDLC: spec issue, Copilot coding-agent pull request, agent self-review and human merge, with screenshots."
image:
  path: /assets/img/headers/ai/ai-sdlc-with-copilot-agents.webp
  alt: "Four-step card for the AI SDLC with Copilot agents: spec issue with acceptance criteria, agent pull request with tests and log, review where the agent self-checks and the human sees three threads, merge once scope diff, tests and scan are green; footer notes 35 agent PRs over 6 weeks, 24 merged, 8 reworked, 3 closed"
---

![Four steps of the agent-driven lifecycle: a spec issue with acceptance criteria and non-goals, a Copilot agent pull request with tests and attached log, a review stage where the agent self-checks against the spec and the human sees only open threads, and a merge stage gated on scope diff, tests and scanning](/assets/img/headers/ai/ai-sdlc-with-copilot-agents.webp){: width="1200" height="630" }

The earlier AI SDLC posts here took one stage each: [where coding agents fit and the hand-off points]({% post_url AI/2026-10-11-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %}), [the merge gates for agent pull requests]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) and [the code-review agent workflow]({% post_url AI/2026-10-13-ai-sdlc-code-review-agent-workflow %}). Readers asked for the whole thing on one issue, start to finish, with what it actually looks like on screen. This is that post: one real-shaped feature on a .NET order API, taken from the written spec to a merged pull request with GitHub Copilot's coding agent doing the typing and a human doing the deciding.

The numbers at the end are from six weeks of running this on two internal services, not a vendor demo.

## Stage 1: the spec issue is the contract

The agent gets exactly one input: a GitHub issue. If the issue is vague the PR is vague, so we spend the human minutes here. Every issue the agent is assigned has the same four blocks:

- **Acceptance criteria** as checkboxes, each testable from outside the code.
- **Non-goals**, which is where most scope creep is stopped before it starts.
- **Agent brief**: the file globs it may touch, the command it must run, and what to attach.
- The assignment line, `@copilot please implement this issue`.

Here is the issue and the pull request the agent opened from it, side by side:

![Left: GitHub issue 412 titled Add idempotency key to POST /orders with acceptance criteria checkboxes, a non-goals block and an agent brief listing allowed file globs and the dotnet test command. Right: draft pull request 418 from branch copilot/issue-412 listing four changed files, a scope check that all files are inside the allowed globs, 212 tests passed with 3 new, 94.1 percent line coverage of the Idempotency folder, agent notes including an open question about tenant scoping, and four green checks: build-and-test, scope-diff, dependency-review, codeql](/assets/img/posts/ai/ai-sdlc-with-copilot-agents-spec-to-pr.webp){: width="1400" height="900" }

Two details in the issue that pay for themselves every time:

1. **"No new NuGet dependency."** Without it, the agent's first draft on a similar issue pulled in a caching library to save forty lines. Dependencies are a decision a human owns, and a one-line non-goal keeps it that way.
2. **"Files you may touch."** The `scope-diff` check in the PR compares the changed paths against these globs and fails the PR when the agent wanders. The agent reads the same text, so it rarely does.

## Stage 2: the agent's pull request

The agent runs in a sandboxed Actions job: it clones the branch, works, runs `dotnet test`, and opens a *draft* PR. Draft matters: nothing from the agent is ever a ready-for-review PR until the review stage below has run.

What we require in the PR body, and what the right-hand side of the screenshot shows:

- The **changed files with line counts**, so the reviewer can see the shape before opening a diff. Four files and 319 added lines for an idempotency middleware is a plausible shape; forty files would be a red flag before reading a line.
- The **scope check**, the **test run** (`212 passed, 0 failed, 3 new`) and **coverage of the new folder**. These are copied from the job log, not written by the model.
- **Agent notes**, including open questions. The question in this PR ("tenant header or API key?") is the kind of thing a human would have asked in stand-up. Having it in the PR body rather than buried in a commit message is why reviewers trust the summary at all.

The four checks at the bottom are the deterministic gates from the [gating post]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}). They must be green before any human is paged; an agent PR with a red gate goes back to the agent with the log, not to a person.

## Stage 3: review, agent first, human second

This is where the time goes in a conventional team, so it is where we were most careful. The review stage has two parts and a fixed order.

**First, the review agent checks the PR against the issue**, criterion by criterion, and posts one comment. Each line names the file and line that satisfies the criterion, or marks it `BLOCKING` or `ADVISORY` when it does not. Then the human reviewer opens the PR:

![Pull request 418 conversation. Top: a review-agent comment listing the six acceptance criteria from issue 412, four ticked with the satisfying file and line, one marked BLOCKING because the Redis key uses the raw UUID while the spec says a hash, and one marked ADVISORY for a missing test when Redis is unavailable, ending with a line telling the human reviewer that two threads need a decision. Bottom: the diff of RedisIdempotencyStore.cs with the key changed to use Sha256Hex, the reviewer's comment agreeing with the blocking thread and asking copilot to apply the suggestion, and a status line that copilot pushed one commit, build-and-test passed and one of two threads is resolved](/assets/img/posts/ai/ai-sdlc-with-copilot-agents-review.webp){: width="1400" height="900" }

The human reviewer saw **three** things on this PR: the blocking thread, the advisory thread and the open question from the PR body. Not 319 lines. The ticked criteria link to the exact lines, so spot-checking any of them is one click, and reviewers do spot-check (we log it; about a third of ticked items get opened).

The reviewer's job is then to *decide*, not to type: agree with the blocking thread, tell the agent to apply it, and decide the advisory one (we took it as a follow-up issue). `@copilot apply the suggestion and re-run the tests` produced one commit and a green re-run in under four minutes, and the review agent re-checked only the two open threads, as described in the [code-review agent post]({% post_url AI/2026-10-13-ai-sdlc-code-review-agent-workflow %}).

Why the agent reviews first and not the human: on the first fifteen PRs we tried it the other way round. Humans spent their time on things the agent would have caught mechanically (a missing null check, a test that asserted the wrong status code) and ran out of attention before reaching the one design question. Reversing the order moved the human minutes to the decisions.

## Stage 4: merge

Merge is boring by design. The PR leaves draft when the review agent reports zero blocking threads, the human has approved, and the four gates are green on the final commit. Squash merge, the issue closes from the `Closes #412` line, and the deployment pipeline treats the commit exactly like a human one. There is no "agent lane" in CD: if the gates are good enough for people, they are good enough here, and if they are not, the fix is better gates for everyone.

## Six weeks, two services, 35 issues

| Measure | Value |
|---|---|
| Issues assigned to the agent | 35 |
| Merged | 24 (69 %) |
| Reworked by a human then merged | 8 (23 %) |
| Closed without merge | 3 (9 %) |
| Median spec-to-merge | 1 day 3 h (human-only on similar issues: 3 days 9 h) |
| Median human review time per PR | 14 min (human-only: 41 min) |
| Scope-diff failures | 4, all on issues whose brief had no file globs |
| Production incidents traced to agent PRs | 0 (two traced to human PRs in the same window) |

Three of the 35 were closed: two because the issue was underspecified and the agent's open questions made that obvious (we rewrote the spec and reassigned), one because the right answer was "do not build this". All three closures happened at the review stage, before any human had read the code, which is the outcome we wanted from putting the agent review first.

The 8 reworked PRs cluster around one thing: issues that touched more than one bounded context. The agent did what the spec said in both places and the result was correct but not how the team would have split it. Our fix was in the spec stage, not the agent: issues now carry a "one bounded context" check before assignment.

## What to copy

1. Put the human effort into the **issue**: acceptance criteria, non-goals, allowed files, the command to run. Everything downstream is only as good as this.
2. Make the agent open **draft** PRs with the test log, coverage and open questions in the body, copied from the job rather than written by the model.
3. Run **deterministic gates before any person is involved**, and the **review agent before the human reviewer**, so the human sees decisions, not diffs.
4. Keep merge and deploy identical for agent and human commits. Separate lanes hide weak gates.

The screenshots above are from our own repositories with names changed. The policy and workflow files behind the `scope-diff` and review-agent checks are in the two linked posts; nothing here needs anything beyond GitHub Copilot's coding agent, Actions and a Redis you already have.
