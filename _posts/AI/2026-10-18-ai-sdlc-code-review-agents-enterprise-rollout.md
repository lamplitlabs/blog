---
layout: post
title: "AI SDLC: Rolling Out AI Code-Review Agents Across an Enterprise - Four Gates and the Eight-Week Numbers"
date: 2026-10-18 11:30:00 +0530
categories: ai ai-sdlc
tags: ai ai-sdlc code-review coding-agents enterprise-ai governance github-actions azure-devops
description: "Taking an AI code-review agent from one pilot repo to 40 services: a per-repo policy file, four rollout gates, and eight weeks of acceptance and defect numbers."
image:
  path: /assets/img/headers/ai/ai-sdlc-code-review-agents-enterprise-rollout.webp
  alt: "Header card reading AI SDLC: rolling out AI code-review agents across an enterprise, four gates, one policy file per repo, and the eight-week numbers from 40 services and 140 engineers"
---

An AI code-review agent that works on one team's repository is a demo. The same agent on forty repositories owned by twelve teams, with different languages, different risk profiles and different opinions about what a review is for, is an enterprise SDLC change - and it fails for enterprise reasons, not model reasons. We have written before about [how to measure a review agent before trusting it]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %}) and about the [four-stage workflow on a single .NET repo]({% post_url AI/2026-10-13-ai-sdlc-code-review-agent-workflow %}). This post is about the part that came after: the rollout.

The short version: one policy file per repository, four gates each team passes in order, and two numbers reviewed every Friday. Over eight weeks the share of agent comments that engineers accepted went from 38% to 79%, and escaped defects per 100 merged PRs fell from 6.1 to 2.6.

## What went wrong in the pilot-to-everyone jump

The first attempt skipped the gates. We turned the agent on for every repository in the organisation on a Monday, with the configuration that had worked for the pilot team. By Thursday three teams had disabled it. The complaints were specific and all of them were legitimate:

- A payments service received comments about naming style on a hotfix PR at 2 a.m. The reviewer did not want style advice; they wanted to know whether the retry logic was correct.
- A data platform team working in Python got comments calibrated for a C# code base - `IDisposable` advice on a repository that had no `IDisposable`.
- A team with a strict change-advisory process had the agent's comments counted as "review" by a dashboard, which made it look as if humans had reviewed PRs they had not opened.

None of these were model failures. They were the result of one configuration meeting forty contexts, and the fix was to put the context in the repository.

## One policy file per repository

Every repository that gets the agent carries a `.review-agent.yml` at its root. The agent reads it before it reads the diff. The schema is deliberately small so that teams actually fill it in:

```yaml
# .review-agent.yml
language: csharp            # csharp | python | typescript | go | mixed
risk: high                  # low | medium | high -> changes what is blocking
mode: comment               # comment | required-check
blocking:
  - security                # secrets, injection, auth bypass
  - data-loss               # destructive migrations, missing transactions
  - concurrency             # shared state, missing locks/awaits
advisory:
  - error-handling
  - tests
  - performance
never:
  - naming
  - formatting              # the formatter already does this
skip_paths:
  - "**/Migrations/**"
  - "**/*.Designer.cs"
quiet_hours: "22:00-07:00 Europe/Berlin"   # hotfix PRs get a summary only
```

Three things in that file carried most of the value:

1. **`blocking` vs `advisory` vs `never`.** A blocking finding is one the agent will post as a request-changes review; an advisory one is a plain comment; `never` categories are not generated at all. The payments team moved `naming` and `formatting` to `never` on day one and their acceptance rate doubled in a week, because the comments that remained were the ones they cared about.
2. **`risk`.** A `high` risk repository gets a stricter default blocking list and a required human approval after the agent; a `low` risk internal tool can run in `required-check` mode where a clean agent pass plus one approval is enough.
3. **`quiet_hours`.** During the window, the agent posts one summary comment instead of inline comments. Nobody at 2 a.m. wants twelve threads.

The file is owned by the team, reviewed like any other change, and visible to the platform team through a nightly job that lists every repository's settings. That last part matters for the audit conversation below.

## The four gates

A repository moves through four gates. A gate is passed when its exit numbers hold for two consecutive weeks; the platform team runs the report, the owning team decides when to move.

| Gate | Agent behaviour | Exit criterion |
|---|---|---|
| 1. Shadow | Agent reviews, output goes to a log the team can read, nothing posted on the PR | Team has read 20 shadow reviews and written its `.review-agent.yml` |
| 2. Advisory | Comments posted, nothing blocks, humans review exactly as before | Acceptance rate above 50%; ignored-comment rate below 40% |
| 3. Blocking on `blocking` categories | Request-changes for blocking findings; advisory stays as comments | Precision on blocking findings above 85% for two weeks; zero false-positive blocks escalated |
| 4. Default | Agent is on by default for new repositories in the organisation with the team's template policy | Escaped defects per 100 PRs not worse than the gate-2 baseline |

Gate 1 looks like it costs a week for nothing. It is the most important gate. Reading twenty shadow reviews is how a team finds out which categories to put under `never` before the agent has annoyed anyone, and it is how we found the Python-repository problem: the shadow log made the C#-flavoured advice obvious without a single engineer having to argue with a bot in a PR thread.

Gate 3 is where the enterprise pushback comes. A blocking review from a non-human is a policy question in regulated environments, so we made two rules explicit: a human can always dismiss an agent block with a one-line reason (which is logged), and the agent never counts as the required reviewer. The agent gates the merge; it never approves it.

## The eight-week numbers

![Bar chart of AI code-review agent comment acceptance rate rising from 38 percent in week one to 41, 52, 61, 70, 74, 77 and 79 percent by week eight, with a red line showing escaped defects per 100 merged PRs falling from 6.1 to 5.9, 5.2, 4.3, 3.4, 3.0, 2.7 and 2.6 over the same weeks; a caption notes that the policy file and blocking versus advisory split landed in week three and the organisation-wide default in week six](/assets/img/posts/ai/code-review-agent-rollout-acceptance-escaped-defects.webp)

Two numbers, reviewed every Friday across all participating repositories:

- **Acceptance rate**: agent comments that led to a code change or an explicit "agreed, follow-up ticket", divided by all agent comments. 38% in week 1, when everyone still had the pilot configuration. The jump from 41% to 52% in week 3 is the policy file landing; the climb to 79% is teams tuning their `never` and `advisory` lists.
- **Escaped defects per 100 merged PRs**: production incidents or bug tickets traced to a merged PR that the agent had reviewed. 6.1 at the start - which was also roughly the pre-agent baseline - down to 2.6 by week 8. Most of the drop came from the `concurrency` and `data-loss` blocking categories, which caught missing `await`s and migrations without a down step that human reviewers had been skimming past.

A number we watched but did not chart: the dismiss-with-reason count for blocking findings. It peaked at 14 in week 4, right after gate 3 opened for the first teams, and settled at 2-3 per week. Every dismissal is read on Friday; the reasons are how the blocking rules get fixed.

## What the platform team actually had to build

Less than we expected, and almost none of it was prompt work:

- **A config loader with defaults per `language` and `risk`.** The prompt is assembled from the policy file; teams never edit a prompt.
- **A nightly inventory** of every repository's `.review-agent.yml`, which gate it is in, and its two numbers. This is the document the security and audit people asked for and it took an afternoon.
- **A dismissal log**: who dismissed which blocking finding and why. Required for gate 3 in any repository tagged `risk: high`.
- **Cost attribution per repository**, reusing the approach from the [cost-per-merged-PR post]({% post_url AI/2026-10-18-ai-sdlc-cost-per-merged-pr-coding-agent-token-budgets %}). Review runs are cheaper than coding-agent runs, but forty repositories add up, and `skip_paths` on generated code cut review spend by about a third.

## Mistakes we would not repeat

- **Turning it on everywhere at once.** The three teams who disabled the agent in week 1 were the last three to reach gate 3, not because the agent was worse for them but because trust had to be rebuilt.
- **Letting dashboards count agent comments as reviews.** Fixed in week 2 by tagging the agent's account; it should have been fixed before week 1.
- **A single acceptance-rate target for every repository.** A 60% acceptance rate on a low-risk internal tool with only advisory comments means something different from 60% on a payments service with blocking enabled. We now report the number per gate.

## Where to start

If you have one team using a review agent and are being asked to make it "the standard", do this before anything else: write the policy file schema, run every new repository through a shadow week, and decide in writing who can dismiss a block and how that is logged. The model matters less than the gates around it, and the gates are what the rest of the organisation will judge the rollout by.
