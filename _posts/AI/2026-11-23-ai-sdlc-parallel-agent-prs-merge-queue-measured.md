---
layout: post
title: "AI SDLC: 12 Parallel Agent PRs, Each Green Alone - Merge Queue vs \"Require Up to Date\", Measured"
date: 2026-11-23 12:00:00 +0000
categories: ai
tags: [ai, ai-sdlc, sdlc, agents, go, ci, git, merge-queue, code-review, benchmark]
author: manishtiwari25
description: "12 agent PRs on one Go service, each green alone: 7-14 of 66 pairs merged cleanly and broke the build or tests. A merge queue kept main green on half the CI."
image:
  path: /assets/img/headers/ai/ai-sdlc-parallel-agent-prs-merge-queue.webp
  alt: "Header graphic for the parallel agent PR post: 7 of 66 PR pairs merge cleanly but break the build with default agent rules, 14 with merge-friendly rules; git conflicts fall from 40 to 13 pairs; 62% of main commits are red with no up-to-date rule; 0 red commits on main with a merge queue, which lands 4.1 PRs per pass."
---

Twelve coding agents work on the same repository at the same time. Each one gets a ticket, writes the change and its tests, runs `gofmt`, `go vet` and `go test -race`, and opens a PR that is green. The question this post measures is what happens next. If each PR's CI ran only against the base it branched from, is it safe to press merge?

The usual answer is "turn on *require branches to be up to date*" or "use a merge queue". Both cost CI time, and agents make the problem bigger in two ways: they open many PRs at once, and they change more of the code around a feature than a person would. So I measured it. I ran twelve real agent PRs on one small Go service and merged every pair in both orders. Then I replayed four merge policies over 100 random arrival orders, with a real `git merge` and a real CI run on every merged tree.

Short version: a clean `git merge` of two green PRs did not compile in **7 of 66 pairs**. When I told the agents to keep their changes "merge-friendly", git conflicts fell from **40 to 13 pairs**, but clean-merge breakages doubled to **14**. Four of those 14 were pairs that compiled and then failed each other's tests. Without an up-to-date rule, **40-62% of the commits on main were red**. A one-at-a-time merge queue landed exactly the same PRs as "require up to date", with **0 red commits**, and needed about half the CI runs.

## The setup

Everything ran locally on an Apple M2 Pro with Go 1.27.4 and git 2.54. The scripts, the 24 agent patches and the raw results are in the repository under `scripts/agent-pr-merge-queue/` and `scripts/data/agent-pr-merge-queue.json`.

**The service.** It is the 282-line token-budget service from the [AI code review gates post](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/): a ledger with `Spend` and `Remaining`, an HTTP spend handler, a pager, config loading and an upstream client, with 18 tests.

**Twelve tickets that touch the same code**, the way a sprint backlog for one service does. Each is a few lines of Markdown in `scripts/agent-pr-merge-queue/tickets/`:

| Ticket | What it asks for |
|---|---|
| T01 | `Spend` returns the remaining balance (signature change) |
| T02 | `Refund` method and `POST /v1/refund` |
| T03 | replace the `ErrOverBudget` sentinel with a `*BudgetError` type |
| T04 | enforce `MaxTokens` per request with 413 |
| T05 | `POST /v1/spend/batch` |
| T06 | unknown tenant answers 404 (`ErrUnknownTenant`) |
| T07 | `Usage()` and a paged `GET /v1/usage` |
| T08 | `Page` returns `ErrPageOutOfRange` past the end |
| T09 | `Remaining` returns `(int, error)` (signature change) |
| T10 | `SetLimit` at runtime, `Remaining` never negative |
| T11 | a 0-token spend is a no-op instead of a 400 |
| T12 | one structured audit log line per spend |

**The agents.** Each ticket went to a fresh coding agent in its own git workspace. The agent got the same fixed prompt (`agent_prompt.txt`), the ticket as `TICKET.md`, and an `AGENTS.md` with the repository rules. It could see only its own workspace. All 12 agents finished in 3-7 tool steps and 20-54 seconds, and all 12 PRs were green on their own base: gofmt clean, vet clean, `go test -race` passing. I then saved each workspace's `git diff` as a patch.

**Two arms.** Arm A used a plain `AGENTS.md` ("every behaviour change needs a test in the matching `*_test.go` file"). For arm B I gave 12 fresh agents the same tickets with "merge-friendly" rules. Many teams write these rules after their first week of agent PR conflicts. Put new code and its tests in a new file named after the feature. Keep edits to existing files small. Add exported names instead of changing them, unless the ticket says to. Touch `ServeHTTP` only to add a one-line dispatch. Arm B's agents followed the rules: they created 22 new files, where arm A's created none, and edited 21 existing files instead of 39.

**The CI gate** is the one every PR already passed: `gofmt -l .` must print nothing, then `go vet ./...` and `go test -race -count=1 ./...` must pass. A type error that `go vet` reports counts as "does not compile". Results are cached by git tree hash, so each distinct tree is tested once. One run took 2 seconds at the 90th percentile.

## Every pair, both orders

`matrix.py` builds a scratch repository with one branch per PR. For every ordered pair it merges PR *a* into main, merges PR *b* on top, and runs CI on the result: 132 merges per arm.

![Two 12 by 12 grids of the agent PRs merged in pairs, colour coded. Arm A with default AGENTS.md: 40 pairs conflict in git, 7 merge cleanly but do not compile, 19 are green. Arm B with merge-friendly rules: 13 conflict, 10 do not compile, 4 compile but fail tests, 39 are green. T08 is green with 10 of 11 PRs; T01, T03 and T09 cause most breakages](/assets/img/posts/ai/ai-sdlc-parallel-agent-prs-merge-queue-pair-matrix.webp)

Every pair gave the same result in both orders, so there are 66 distinct pairs per arm:

| Pair result | Arm A: default rules | Arm B: merge-friendly rules |
|---|---|---|
| git conflict, author must rebase | 40 | 13 |
| clean merge, **does not compile** | 7 | 10 |
| clean merge, compiles, **tests fail** | 0 | 4 |
| clean merge, CI green | 19 | 39 |

Three things stand out.

**1. A green PR plus a green PR is not a green main.** In 7 pairs in arm A, git merged both PRs without a conflict and the result did not build. Most of them come from the two tickets that changed a signature. Here is T01 (`Spend` now returns `(int, error)`) merged with T02 (a new `Refund` test that calls `err := l.Spend(...)`):

![Terminal recording of two clean merges that break main. Arm A: merging T01 then T02 auto-merges four files with no conflict, gofmt is clean, then go vet fails with ledger_test.go:126: assignment mismatch: 1 variable but l.Spend returns 2 values. Arm B: merging T11 then T06 is clean and vets clean, then go test -race fails TestHandlerInvalidSpendStays400 (got 200, want 400) and TestHandlerZeroSpendUnknownTenant (got 404, want 400)](/assets/img/posts/ai/ai-sdlc-parallel-agent-prs-merge-queue-terminal.webp)

T03 caused a quieter one. It removed `ErrOverBudget`, which made the `errors` import in `ledger.go` unused, so the agent deleted the import. T02, T06 and T09 each added a new `errors.New` sentinel to `ledger.go`, below the import block. Git merged the hunks cleanly, and the result fails with `undefined: errors`. Neither diff is wrong on its own. Only the merged tree is.

**2. Merge-friendly rules swap conflicts for silent breakage.** New files and small edits cut git conflicts from 40 to 13 pairs. Conflicts in `handler_test.go` alone went from 60 merges to 0. But a conflict is the safe kind of failure: git stops and nothing lands. With the code spread across `refund.go`, `usage.go` and `set_limit_test.go`, the overlap moved where git cannot see it. Clean-merge breakages went from 7 to 14 pairs. Four of them compile and fail tests, which arm A never did. When T11 (0 tokens is a no-op) meets T06 (unknown tenant is 404), each agent's new test asserts the old behaviour of the other ticket. Both PRs did what their tickets said. The tickets contradict each other, and nobody sees it until the two are tested together.

**3. Which tickets break things is predictable.** Every one of the 7 arm-A breakages involves T01 or T03. Every one of the 14 arm-B breakages involves T01, T03, T08, T09 or T11. Those five tickets change an existing contract: a signature (T01, T09), an exported name (T03), or what an input means (a page past the end in T08, 0 tokens in T11). The other seven tickets only add things, and they never broke each other.

## Four merge policies, 100 arrival orders

The pair matrix shows what can break. Whether it reaches main depends on the merge policy. `simulate.py` shuffles the 12 PRs into 100 seeded arrival orders and replays each order through four policies:

- **Checks on the PR base only, no up-to-date rule.** A PR merges if git can merge it, and CI runs on main afterwards. This is GitHub's default with required checks but without "require branches to be up to date".
- **Require up to date.** After each landing, every open PR merges main in and re-runs CI. That is what agents that auto-update their branch do. The first green PR in arrival order lands.
- **Merge queue, one entry at a time.** Each PR is tested as main plus that PR, and lands only if green.
- **Merge queue building 4 entries at once.** Each entry is tested on main plus the entries ahead of it. If an entry fails, the entries built on top of it are rebuilt.

A PR that conflicts, or whose merged tree is red where the policy tests it, goes back to its agent. I count how many PRs land in one pass, how many red commits reach main, and how many CI runs it took.

![Table of four merge policies over 100 orders, for both arms. No up-to-date rule: 3.41 and 5.97 PRs landed, 138 and 372 red commits on main (40% and 62% of commits). Require up to date: 2.66 and 4.14 landed, 0 red, 29.7 and 39.6 CI runs per order. Merge queue one at a time: 2.66 and 4.14 landed, 0 red, 15.7 and 19.1 CI runs. Merge queue four at once: 2.60 and 4.03 landed, 0 red, 16.1 and 20.9 CI runs in about half the rounds](/assets/img/posts/ai/ai-sdlc-parallel-agent-prs-merge-queue-policies.webp)

| Policy (mean per order) | PRs landed A / B | red commits on main A / B | CI runs A / B | CI rounds A / B |
|---|---|---|---|---|
| No up-to-date rule | 3.41 / 5.97 | **138 / 372** (in 80 / 100 orders) | 15.4 / 18.0 | 4.4 / 7.0 |
| Require up to date | 2.66 / 4.14 | 0 / 0 | **29.7 / 39.6** | 3.9 / 5.4 |
| Merge queue, 1 at a time | 2.66 / 4.14 | 0 / 0 | 15.7 / 19.1 | 4.7 / 8.1 |
| Merge queue, 4 at once | 2.60 / 4.03 | 0 / 0 | 16.1 / 20.9 | **2.5 / 4.0** |

CI runs include the 12 runs on the PR branches. A round is one wait for CI; the runs inside a round go in parallel.

**No up-to-date rule lands the most because it lands broken code.** In arm A, main went red in 80 of 100 orders, after 2 good merges on average. In arm B it went red in every order, and 62% of all commits on main were red. Once main is red, every later PR's CI on main fails for a reason that is not its own. An agent asked to "fix CI" then patches the wrong thing.

**"Require up to date" and the merge queue land exactly the same PRs.** That held in all 100 orders of both arms, because both test the same tree, main plus the PR, before merging. The difference is cost. Re-running every open PR after each landing took 29.7 CI runs per order in arm A and 39.6 in arm B. The queue took 15.7 and 19.1, barely more than the 12 runs the PRs needed anyway. With 12 agents this is the difference between a CI bill that grows with the number of open PRs and one that grows with the number of merges.

**Building 4 entries at once cuts the wait, not the bill.** The batched queue needed about half the rounds (2.5 vs 4.7 in arm A). It paid for that with rebuilds: 62 runs in arm A and 246 in arm B were built on top of an entry that then failed. It also landed slightly fewer PRs (2.60 vs 2.66). A PR that conflicts with an entry ahead of it is removed at once, even if that entry later fails and never lands. The busier the breakage, the less parallel building pays. Arm B, which broke more often, wasted more runs.

**Merge-friendly rules still landed more.** Arm B landed 4.1 PRs per pass instead of 2.7, because 26 more pairs merged green. The rules are worth keeping. They are not a replacement for testing the merged tree.

## What I would do with this

- **Never merge an agent PR on a check that ran against an old base.** Either require branches to be up to date or use a merge queue. Here the PR-base check let a broken tree into main in 80-100% of orders.
- **Prefer the merge queue to "require up to date" when agents open PRs in parallel.** It lands the same PRs, and here needed 47-52% fewer CI runs. Don't let agents auto-update their branches in a loop after every landing; that is the expensive policy.
- **Build several entries at once only if breakage is rare.** Batching halved the rounds, but every failure throws away the runs built on top of it.
- **Keep the "new file, small edit" rules, and add a contract rule.** They cut conflicts by two thirds. But they also hid overlaps from git, so the tickets that change a contract need their own handling: a changed signature, a removed export, a new meaning for an input. Here that was 5 tickets out of 12. Land those first and alone, or let one agent own them, before the parallel work starts.
- **Look for contradictions between tickets before agents run.** Three of the four test failures in arm B were T11's new meaning of a 0-token spend against tests in T05, T06 and T12 that pinned the old one. The fourth was T07 promising 200 and `[]` for a page past the end while T08 made that an error. That is a planning bug, and a merge queue only catches it after both agents have done the work.

## Limits

- **One small service, one sprint.** It is 282 lines and 12 tickets chosen to overlap, the way a backlog for one service does. A larger codebase with more independent tickets would show fewer breakages per pair. A busier one would show more.
- **One agent family, one run per ticket and arm.** Another agent would produce different diffs. The direction of finding 2 (fewer conflicts, more silent breakage) follows from where the rules moved the code, but the exact counts would move.
- **The replay is one pass.** A PR that bounced goes back to its agent, which would rebase or fix it and try again. I did not run those second rounds, so "PRs landed" is per pass, not per sprint.
- **CI is gofmt, vet and `go test -race` only.** A real pipeline with integration tests or a slower build changes the cost columns, not the red-commit columns.
- **The merge queue is modelled, not GitHub's.** It follows the documented behaviour (test main plus the entries ahead, remove a failed entry, rebuild the ones behind it). Its timing and retry details are not reproduced.

[Hive](https://hivefleet.dev/), Lamplit Labs' open-source, self-improving (RSI) agent harness ([introduction](/posts/hive-self-improving-rsi-agent-harness/)), runs many agents against the same repositories. It stacks its pull requests for the reason this post gives: the next one is built on the open one, so two open pull requests never hold changes to the same lines that meet for the first time at merge time. The check on the merged result itself is left to the repository's own pipeline.

## Reproduce it

```bash
python3 scripts/agent-pr-merge-queue/setup_runs.py .tmp/merge-queue-runs default.md
python3 scripts/agent-pr-merge-queue/setup_runs.py .tmp/merge-queue-runs-split split.md
# run one coding agent per workspace with agent_prompt.txt ({WS} = the workspace name)
python3 scripts/agent-pr-merge-queue/collect.py .tmp/merge-queue-runs patches
python3 scripts/agent-pr-merge-queue/collect.py .tmp/merge-queue-runs-split patches-split
python3 scripts/agent-pr-merge-queue/matrix.py .tmp/merge-queue                 # ~2 min, 132 merges + CI
MQ_PATCHES=patches-split python3 scripts/agent-pr-merge-queue/matrix.py .tmp/merge-queue-split
python3 scripts/agent-pr-merge-queue/simulate.py .tmp/merge-queue 100           # ~2 min (CI cached by tree)
MQ_PATCHES=patches-split python3 scripts/agent-pr-merge-queue/simulate.py .tmp/merge-queue-split 100   # ~7 min
python3 scripts/agent-pr-merge-queue/summarise.py   # -> scripts/data/agent-pr-merge-queue.json
python3 scripts/agent-pr-merge-queue/transcript.py  # -> scripts/data/agent-pr-merge-queue-transcript.json
python3 scripts/agent-pr-merge-queue/gen_images.py
```

The recorded patches are committed, so you can skip the agent step and start at `matrix.py`. It needs Go and git, nothing else. The agents' tool steps and wall time are in `agent_runs.tsv` and `agent_runs_split.tsv`.

## Related

- [AI Code Review Gates in CI, Measured: 26 Seeded Agent Defects Against a Go Pipeline](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/): the service and the gates each PR passed here.
- [AI SDLC: Flaky Agent PRs vs "Re-run Failed Jobs", Measured on 10,233 Go Test Runs](/posts/ai-sdlc-flaky-agent-prs-ci-retries-measured/): the other way a green check can lie.
- [AI SDLC: Spec to PR With Coding Agents, Measured - What to Gate Before and After the Agent](/posts/ai-sdlc-spec-to-pr-agents-what-to-gate/): how thin tickets turn into wrong assumptions.
- [AI SDLC: Agent-Written Go Tests vs Mutation Testing, Measured - Same 97.3% Score, 15 or 19 Bugs Caught](/posts/ai-sdlc-agent-written-tests-mutation-testing-go-measured/): what the tests that guard these merges actually catch.
- [Hive: Lamplit Labs' open-source, self-improving (RSI) agent harness](/posts/hive-self-improving-rsi-agent-harness/)
