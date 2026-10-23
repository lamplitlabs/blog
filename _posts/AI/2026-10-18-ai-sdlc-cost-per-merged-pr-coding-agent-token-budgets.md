---
layout: post
title: "AI SDLC: Cost per Merged PR - Token Budgets for Coding Agents and the Four Numbers We Track"
date: 2026-10-18 09:30:00 +0530
categories: ai ai-sdlc
tags: ai ai-sdlc coding-agents cost token-budget llm-ops github-actions
description: "How we cut coding-agent spend per merged PR from $31 to $9 with a per-task token budget, a retry cap and a context-size guard, without lowering merge rate."
image:
  path: /assets/img/headers/ai/ai-sdlc-cost-per-merged-pr-coding-agent-token-budgets.webp
  alt: "Header card reading AI SDLC: cost per merged PR, token budgets for coding agents and the four numbers we track"
---

The first bill after we let coding agents open pull requests on their own was not frightening. The third one was. Spend had tripled while the number of merged changes had barely moved, and nobody could say which tasks the money had gone to. The agents were not doing anything wrong; they were doing exactly what we had asked - *keep going until the tests pass* - and some of them kept going for a very long time.

This post is what we changed and what we measured. The one number we now manage is **cost per merged PR**: total model spend attributed to agent runs, divided by the agent-authored pull requests that actually landed. Over eight weeks it went from $31 to $9 while the merge rate of agent PRs stayed between 60% and 67%.

## Why "tokens per run" was the wrong number

Our first dashboard showed tokens per run, and it looked fine: the median run was cheap. The problem lived in the tail. Pulling the run logs for one week showed:

- 6% of runs consumed 48% of the tokens.
- Almost all of those runs ended with a PR that was closed without merging, or with no PR at all.
- The typical shape was a loop: edit, run tests, read the whole failing output, edit again - twelve or fifteen times, re-reading the same 40 KB test log each pass.

Spend that produces nothing is the spend to cut, so the denominator had to be *merged* PRs. A task that burns $40 and lands is a bargain compared to one that burns $4 and is thrown away.

## The three changes

We introduced all three in week 4 and left everything else alone - same models, same repositories, same task mix from the backlog.

### 1. A per-task token budget, declared in the task

Every task the dispatcher hands to an agent carries a budget line, with a default of 400k input tokens and a cap chosen from the task's label:

```yaml
# .agents/budgets.yml
default: { input_tokens: 400000, output_tokens: 60000 }
labels:
  docs:        { input_tokens: 150000, output_tokens: 30000 }
  bugfix:      { input_tokens: 400000, output_tokens: 60000 }
  feature:     { input_tokens: 900000, output_tokens: 120000 }
```

The runner counts usage from every model response and stops the run at the cap. Stopping is not silent: the agent is told it is at 80% of budget and asked to either open the PR with what it has or write a handoff note saying exactly where it stopped. In practice about a third of near-cap runs now land a smaller PR instead of nothing.

### 2. A retry cap on the test loop

The runner tracks consecutive failing test invocations. After **three** failures of the same command with the same failing test names, it refuses to run the command again and returns one line: *same failure three times; change approach or stop*. That single rule removed most of the twelve-pass loops. It also surfaced a real defect: two repositories had a flaky integration test that the agents had been "fixing" by rerunning it, which is the subject of [the flaky-test triage post](/posts/ai-sdlc-flaky-test-triage/).

### 3. A context-size guard on tool output

The loop re-read full test logs because the tool returned full test logs. The guard truncates any tool result over 12 KB to its first and last 4 KB and inserts a line saying how much was cut, so the agent has to filter (`grep`, `--filter`, `head`) to see more. Per-pass input tokens on test-heavy tasks fell by roughly 60%.

## What moved

![Bar chart of coding-agent cost per merged PR by week, $31, $29, $33, $27 before the budget rules in week four, then $15, $12, $10, $9; a green line shows merge rate of agent PRs holding between 60 and 67 percent throughout](/assets/img/posts/ai/coding-agent-cost-per-merged-pr-weekly.webp)

| Week | Agent PRs opened | Merged | Merge rate | Spend | Cost per merged PR |
|------|-----------------:|-------:|-----------:|------:|-------------------:|
| 1 | 49 | 30 | 61% | $930 | $31 |
| 2 | 52 | 33 | 63% | $957 | $29 |
| 3 | 47 | 28 | 60% | $924 | $33 |
| 4 | 55 | 34 | 62% | $918 | $27 |
| 5 | 53 | 34 | 64% | $510 | $15 |
| 6 | 56 | 37 | 66% | $444 | $12 |
| 7 | 54 | 35 | 65% | $350 | $10 |
| 8 | 58 | 39 | 67% | $351 | $9 |

Two things stood out. First, the merge rate did not fall - the fear that budgets would produce half-finished PRs did not materialise, because the near-cap handoff turns a would-be abandoned run into a smaller landed one. Second, the budget cap itself fired on only 4% of runs by week 8. The retry cap and the context guard did most of the work; the budget is the backstop.

## The four numbers we track now

These are on the same dashboard the on-call engineer sees, next to the [Azure OpenAI cost tiles](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/):

1. **Cost per merged PR** (weekly) - the headline, alerted when the 7-day value rises more than 30% over the 28-day value.
2. **Share of spend in runs that did not merge** - the waste ratio; it went from 48% to 17%.
3. **Budget-cap hits and retry-cap hits per 100 runs** - if either climbs, the task mix or the model changed and the limits need revisiting.
4. **Median passes per task** - the loop length; from 7.8 to 3.4.

## What we would do differently

- Attribute spend from day one. Reconstructing the first three weeks from raw API logs by matching timestamps to runner IDs took longer than building the budget feature.
- Put the budget in the task, not in the agent. When we tried per-agent budgets, a cheap docs task and an expensive feature task shared the same cap and both were wrong.
- Treat a retry-cap hit as a signal about the repository, not about the agent. Every repository that produced repeated hits had a slow or flaky check that was costing human engineers time too.

## Related

- [AI SDLC: AGENTS.md instruction files coding agents actually follow](/posts/ai-sdlc-agents-md-instruction-files-coding-agents-actually-follow/) - the rules file the budget line lives next to.
- [AI SDLC: flaky test triage](/posts/ai-sdlc-flaky-test-triage/) - what the retry cap uncovered.
- [AI SDLC: code review agent metrics](/posts/ai-sdlc-code-review-agent-metrics/) - the review-side numbers that pair with cost per merged PR.
