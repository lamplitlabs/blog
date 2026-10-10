---
layout: post
title: "AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It"
date: 2026-10-08 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp code-review copilot devops enterprise metrics
author: manishtiwari25
description: "Five metrics for an AI code-review agent on a .NET repo: precision, ignored comments, escaped defects, turnaround and cost per PR, plus the dashboard."
image:
  path: /assets/img/headers/ai/ai-sdlc-code-review-agent-metrics.webp
  alt: "Header card showing four metrics for an AI code-review agent: 71% precision, 22% ignored comments, 2 escaped defects and $0.11 cost per PR"
---

In the [phase-by-phase AI SDLC post]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}) I argued that AI drafts, humans decide, and something deterministic checks. The code-review phase is where that rule gets tested first, because an AI reviewer that posts twenty comments per pull request and is right about six of them trains your team to ignore all twenty. This post is about the measurement loop we put around an LLM review bot on a .NET API repo, the five numbers we track, and the dashboard that decides each sprint whether the bot stays on.

![Code-review agent dashboard for one sprint: precision 71%, 4.2 comments per PR, 22% ignored-comment rate, 2 escaped defects, a precision trend line crossing the 60% target, accepted vs ignored comments per category, and a turnaround and cost table](/assets/img/posts/ai/ai-code-review-agent-metrics-dashboard.webp){: width="1400" height="820" }

## Why "developers like it" is not a metric

The first month we ran the agent, the only feedback we had was a thumbs-up emoji reaction in Teams. Developers liked it. Three sprints later two engineers admitted they had muted the bot because most comments were style nits on code they were about to delete anyway. Liking a tool and acting on its output are different things, and only the second one changes the quality of the code that ships.

So we treated the agent like any other reviewer and asked the question we would ask of a human: *of the things you flag, how many do we actually fix?*

## The five metrics

### 1. Precision: accepted comments / posted comments

A comment is **accepted** when the PR author pushes a commit that touches the flagged lines before the thread is resolved, or when they react with 👍 or reply "done". It is **ignored** when the thread is resolved with no change and no reply, or the PR merges with the comment still open.

This is the headline number. Below roughly 50% developers stop reading. We set the target at 60% and the bot went from 41% to 71% over eight sprints, almost entirely by turning categories off (more on that below).

### 2. Ignored-comment rate

The inverse of precision, but tracked separately per **category** rather than per PR. Precision tells you whether to keep the agent; ignored rate per category tells you *which prompts to delete*. Our rule: a category under 40% precision for two consecutive sprints gets its prompt disabled. "Naming / style" was the first casualty (9 accepted, 21 ignored in the sprint shown) and nobody missed it.

### 3. Escaped defects on reviewed PRs

Count production bugs whose fixing PR touches a file that the agent reviewed in the original change. This is the only metric that says anything about *recall*, and it is noisy, so we read it as a trend over quarters, not sprints. If precision goes up because the agent now says almost nothing, escaped defects will tell you.

### 4. Turnaround: time to first review comment and human review time

Before the agent, the median time from PR opened to first review comment was almost four hours (someone had to notice). With the agent it is nine minutes, and the human reviewer arrives to a PR where the null checks, missing `CancellationToken` and obvious test gaps are already in a thread. Median human review time per PR dropped from 38 to 27 minutes. That is the saving that pays for everything else.

### 5. Cost per PR

Input plus output tokens per review, priced at the deployment's rate. We log it from the same place that posts the comments. At $0.11 per PR the agent is cheaper than the coffee for the human review it shortens, but you want the number on the dashboard so nobody has to guess when a prompt change triples the context you send.

## Collecting the data from GitHub

Everything above comes from two sources: the agent's own log (tokens, categories, which lines it commented on) and the GitHub review-comment API. A small .NET worker runs nightly and joins them.

```csharp
using Octokit;

var client = new GitHubClient(new ProductHeaderValue("review-metrics"))
{
    Credentials = new Credentials(Environment.GetEnvironmentVariable("GITHUB_TOKEN"))
};

var comments = await client.PullRequest.ReviewComment
    .GetAll("contoso", "orders-api", prNumber);

var agentComments = comments.Where(c => c.User.Login == "orders-review-bot[bot]");

foreach (var comment in agentComments)
{
    var category = ParseCategory(comment.Body);           // first line: "[category: async-cancellation]"
    var replies = comments.Where(c => c.InReplyToId == comment.Id).ToList();

    var accepted =
        replies.Any(r => r.User.Login != comment.User.Login) ||
        comment.Reactions.PlusOne > 0 ||
        await LinesChangedAfterAsync(client, prNumber, comment.Path, comment.Line, comment.CreatedAt);

    await metrics.RecordAsync(prNumber, category, accepted, comment.CreatedAt);
}
```

Two implementation notes that saved us debugging time:

- Make the agent emit its **category as the first line of every comment** in a fixed format. Classifying comments after the fact with another LLM call is slower, costs money and introduces a second thing to measure.
- `LinesChangedAfterAsync` compares the PR's commits after `comment.CreatedAt` against the commented file and line range. It is an approximation, but it agreed with a manual audit of 60 comments 54 times, which is good enough to drive the dashboard.

## Reading the dashboard each sprint

The screenshot above is the view we look at in retro. The reading order is deliberate:

1. **Precision trend** against the 60% line. Below target for two sprints means the next item on the retro is "what do we turn off".
2. **Accepted vs ignored per category.** Green bar short and grey bar long means the prompt is noise. Delete it; do not tune it.
3. **Escaped defects.** Flat or falling while precision rises is the healthy pattern. Falling precision *and* falling escaped defects usually means the agent is commenting on everything.
4. **Turnaround and cost.** These should be boring. If cost per PR jumps, someone changed the prompt or the diff-size limit.

## What this does not measure

It does not measure whether the agent made a developer *think* differently about a change, and it does not catch the reviews that a human would have done better unassisted. Those matter, and the escaped-defect count is the only indirect proxy we have. The point of the dashboard is narrower: it keeps the human gate in place by making the agent earn its comments every sprint, which is exactly the shape the AI SDLC rule asks for.

## Related AI SDLC posts

- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [AI SDLC in Practice: Letting a Coding Agent Triage and Fix a GitHub Issue End-to-End]({% post_url AI/2026-10-04-ai-coding-agent-fix-github-issue-end-to-end %})
- [Testing LLM Prompts in .NET: Regression Tests for Azure OpenAI Outputs]({% post_url AI/2026-10-02-testing-llm-prompts-dotnet %})
