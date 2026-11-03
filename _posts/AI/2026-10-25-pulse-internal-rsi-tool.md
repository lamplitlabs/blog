---
layout: post
title: "Pulse: Lamplit Labs' multi-project self-improving (RSI) automation product, coming soon"
description: "Pulse is Lamplit Labs' multi-project self-improving (RSI) automation product, coming soon. It already runs this blog's publishing loop - how the loop works."
date: 2026-10-25 14:07:00 +0000
categories: ai
tags: ai sdlc automation ai agents machine-learning
image:
  path: /assets/img/headers/ai/pulse-internal-rsi-tool.webp
  alt: "The Pulse RSI loop: plan, work, verify, review and learn, with every improvement gated by deterministic checks"
pin: false
math: false
mermaid: false
---

A disclosure before anything else, because posts like this eventually get misquoted: **Pulse is Lamplit Labs' multi-project self-improving (RSI) automation product. It is coming soon; it already runs across our projects, and this blog is its proving ground.** RSI here means recursive self-improvement in the narrow, engineering sense: the system reads its own failures and proposes changes to its own operating layer - which a human then reviews, and which deterministic checks must accept before anything lands. There is no self-modifying code running unsupervised. There is a loop, and the loop has a fence around it.

We write about it occasionally - the [automation evolution]({% post_url AI/2026-10-12-pulse-automation-evolution %}) post walked through how it grew from a published hand-run checklist into a daemon that drafts and checks this blog - but readers keep asking the same questions. What does the loop actually look like? What is the AI allowed to touch? And what does shipping it as a product mean? This post answers those, and shows a piece we have not shown before: how the failure-feedback half of the loop works.

![The Pulse RSI loop](/assets/img/posts/ai/pulse-internal-rsi-tool.webp)

## The loop, one turn at a time

One Pulse job is one turn of the loop:

1. **Plan.** A scheduler proposes work - a missing check, a post on a topic the backlog voted up, a defect a gate keeps catching. Nothing here is autonomous in the interesting sense; the backlog, the ballots and the daily caps are set by humans and reviewed in the open.
2. **Work.** A coding agent (the same kind we write about in the [AI SDLC series]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})) executes one task in a throwaway clone with pinned tools, no credentials, and a budget of model calls.
3. **Verify.** The project's own checks run before anything is committed: `tools/test.sh` with its coverage, tag and link rules, then `bundle exec jekyll build`. A job whose check fails lands nothing - the runner refuses it, and the failure becomes input to the loop rather than a broken deploy.
4. **Review.** A human reads the branch. Not skimmed, not rubber-stamped: the diff, the check output, and the agent's own report.
5. **Learn.** Every failure - a rejected branch, a flaky check, a job that burned its budget without committing - is classified and written back into the system: better task briefs, a new deterministic check, a record so the next agent does not repeat the mistake.

Step 5 is the "recursive" part, and it is deliberately the most boring step in the loop.

## The failure-feedback half, up close

The diagram's "review memory" box holds three kinds of records. The first is the *lesson*: when three separate jobs landed nothing because their final check failed after the commits, that pattern got written down as a failure record - "verify exit status on the merged result before finishing" - and every later worker reads it before starting. The check that failed did not change; the *briefs* changed, and the failure rate for that class went to zero. The system improved its own instructions, which is the safest form of self-improvement there is.

The second is the *vote*: suggestions for new checks or posts are proposed as small cards - one file, one variable, one hypothesis - and other workers vote on them. Only a card with a measured signal ever becomes a job. That is how the 13-check gauntlet in `tools/test.sh` grew: each check is a card that won a vote, not a grand design. The [prompt injection defences]({% post_url AI/2026-10-11-ai-sdlc-prompt-injection-defences-for-coding-agents %}) post enumerates what that layered posture produced.

The third is the *gate change*, and it is the one we are most conservative about. When Pulse itself noticed that posts with tables render poorly in the site's list layout, the loop did not get to ban tables. A human added a style check, a human set its threshold, and the loop merely enforces it thereafter. **The AI proposes; the checks dispose; humans own the checks.** That sentence is the entire security posture, and it is why the loop can run unattended without ever being unsupervised in the ways that matter.

## From this blog to every project

Pulse started as this blog's automation, and the loop above is exactly what runs here tonight. But nothing in it is blog-specific: the plan-work-verify-review-learn cycle, the failure records, the vote cards, and the gates are project-agnostic machinery. That is why we are building Pulse as a multi-project product:

- **The same loop, pointed at any repository.** The briefs, check lists, voter conventions and failure records are per-project configuration, not code. This blog is the first instance, not the only shape it takes.
- **Its value is the process, productised.** Everything durable about Pulse is already public in the posts it helps produce: gate everything, make failures cheap, add one deterministic check per defect class, keep the model inside a fence of scripts. Pulse turns that discipline into something you can point at your own projects instead of rebuilding it by hand.
- **Real workflows keep it honest.** Because Pulse runs on our real projects, its evals are production work, not a demo set. The [fine-tuning pipeline]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %}) and the supply-chain checks in this series exist because the loop needed them, and they are better for it.

Pulse is coming soon. We are not publishing a timeline or any unreleased specifics today; when it is ready, this blog is where you will read about it first.

## Related posts

- [How Pulse runs this blog: the automation evolution]({% post_url AI/2026-10-12-pulse-automation-evolution %})
- [Our blog pipeline: AI-assisted publishing]({% post_url AI/2026-10-09-our-blog-pipeline-ai-assisted-publishing %})
- [Model training and fine-tuning: the pipeline with regression gates]({% post_url AI/2026-10-25-fine-tuning-pipeline-regression-gates %})
- [AI SDLC: prompt injection defences for coding agents, in layers]({% post_url AI/2026-10-11-ai-sdlc-prompt-injection-defences-for-coding-agents %})
