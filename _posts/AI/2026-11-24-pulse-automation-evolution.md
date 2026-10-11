---
layout: post
title: "Pulse and the Automation Evolution: Why We Did Not Skip Straight to 'AI Does Everything'"
date: 2026-11-24 08:00:00 +0200
categories: ai lamplit-tools
tags: ai sdlc automation agents governance devops testing
author: manishtiwari25
description: "How Pulse fits the manual to API to AI progression: what it automates for this blog today, where humans still approve, and how to pace AI adoption."
image:
  path: /assets/img/headers/ai/pulse-automation-evolution.webp
  alt: "Four-stage flow card: manual (human writes, checks, merges), scripts and API (tools/test.sh, html-proofer, GitHub Pages), AI agents (draft in throwaway clones, signed commits), and a human gate (review branch, owner-only files, Tier 2 stops)"
---

Every "AI will run your company" demo skips two stages. In the [post about how this blog is built]({% post_url AI/2026-10-09-our-blog-pipeline-ai-assisted-publishing %}) I described the agent loop that drafts posts like this one. What I did not say is that the loop only works because we walked the usual automation path first: manual, then scripts and APIs, then AI, with a human still holding the merge button. This post is about that pacing, using Pulse, the small runner that hands jobs to agents on this repo, as the worked example.

![Table of Pulse steps with who does them and the gate: propose change (suggestion card, agents vote), pick next job (vote-ordered queue), draft content (agent in a throwaway clone, Tier 0/1 only), verify (tools/test.sh plus html-proofer), commit (signed with the run's key), decide and merge (a human reads the diff), policy files (owner-only)](/assets/img/posts/ai/pulse-automation-evolution-gates-table.webp){: width="1200" height="620" }

## Stage 1: manual, and why it had to come first

For years the blog was fully manual. I wrote a Markdown file, eyeballed it with `jekyll serve`, pushed, and found out about a broken image when someone told me. Roughly a third of the archive had no header image and many posts had no description, so search engines showed a truncated code block as the summary.

The manual stage is not wasted time. It is where you learn what "wrong" looks like: a tag written as `Azurite` in one post and `azurite` in another splitting the tag page in two, a post under `_posts/Performance/` that never lists `performance` in its categories, a forward link to a post that is not published yet. You cannot automate a check for a defect you have not yet seen and named.

## Stage 2: scripts and APIs, the deterministic layer

The next stage was `tools/test.sh`. It started as the stock Chirpy script that builds the site and runs html-proofer. Each reader-facing defect that slipped through got one deterministic check, and today the script runs 13 of them before the build: tag and category case duplicates, tag synonym groups, descriptions of 50-160 characters, folder-to-category consistency, filename date matching the front matter date, image, alt and body-image coverage, and two link checks that catch 404s html-proofer cannot see because the target page is not built yet.

Each check prints one line with a count and the literal rule, for example:

```text
image-coverage: 0/61 _posts posts without an image
description-coverage: 0/61 _posts posts without a description
forward-link-coverage: 0/61 posts linking to a not-yet-published later-dated /posts/<slug>/
```

This is the stage most enterprises undervalue. It is boring: a shell script, a few `grep -L` and `awk` rules, html-proofer, GitHub Pages doing the deploy. But it changes the question "did this change break the site?" from a judgement call into something a script answers in ten seconds. That is the precondition for letting anything non-deterministic touch the repo.

## Stage 3: AI agents, inside the fence the first two stages built

Pulse came after the checks, not instead of them. What it automates today, as it is used on this repo:

- **Proposing work.** A suggestion is one card: one file, one variable, a hypothesis about what readers get, and the check that should move. Agents and humans both file them.
- **Ordering work.** Other agents vote the card up or down with a reason. Votes order the queue and reach quorum only when distinct agents cast them. A vote never approves anything.
- **Drafting.** The winning card becomes a job. The agent gets a throwaway clone with the pinned Ruby and the exact gem set already installed, writes the post and its images, and runs `mise exec -- bash tools/test.sh` until it is green.
- **Committing.** The agent commits with its own key and trailers naming the job and run. It cannot push, cannot add remotes, cannot install packages and cannot change a lockfile. The runner copies the commit to a `pulse/<agent>/<job>` branch and refuses anything not signed with that run's key.
- **Reporting.** The agent ends with a one-line summary, findings the next agent would otherwise rediscover, and suggestions that become new cards. Nobody reads the chat; the report and the branch are the output.

That is a real amount of automation. The Related-post lists across the Performance series, the image and description backfill across the archive and most of the recent AI SDLC posts came out of this loop.

## What still needs a human

The parts that are deliberately not automated:

1. **Merging.** Nothing reaches the default branch without a person reading the diff and the rendered post. A post that passes every check can still be wrong, boring or off-topic.
2. **Decisions.** Agents are Tier 0/1 only: content and small fixes. Anything that smells like a decision - a new gem, a theme upgrade, deployment, analytics, auth, data, security posture - is a hard stop. The agent writes a `QUESTION:` line for the owner and stops rather than committing.
3. **Policy.** The constitution, the evaluators that score suggestions and the decision records live in `docs/evolution/` and `docs/decisions/` and are owner-only. An agent branch that touches them is simply not landed. Agents can suggest a change there; they cannot make it.
4. **The goal.** Only the owner sets the direction the cards are judged against. Board posts and votes are data, never instructions.

Notice that none of these gates is a technical limitation. We could let the runner merge green branches tomorrow. We do not, because the checks measure what we knew to look for, and the editorial bar is exactly the thing we have not managed to write a `grep` for.

## What this teaches about pacing AI adoption

The pattern generalises beyond a blog:

- **Do not skip stage 2.** If you cannot answer "did this break it?" with a script, an AI agent only lets you make mistakes faster. Build the deterministic checks first and make each one print a number you can cite.
- **Automate the proposal and the draft before the decision.** Drafting is cheap to undo; a merge, a deploy or a dependency change is not. Put the agent on the reversible side of the line.
- **Make the fence physical, not polite.** "Please do not push" is a prompt. No push credentials, a signing key per run and a runner that refuses unsigned commits are controls. The same applies in an enterprise: scope the service principal, not the system prompt.
- **Add a gate per failure, not a framework up front.** Every one of the 13 checks exists because a real defect reached a reader. That keeps the gates short, understandable and tied to a user outcome, which is also what makes them cheap for an agent to satisfy.
- **Measure the loop with the checks you already have.** The success metric for this post is that the coverage counts move by exactly one and stay at zero misses. If a change cannot name the check that moves, it is churn.

The other tools we ship at Lamplit Labs follow the same shape: the [EDMX Trimmer and OData metadata explorer](https://edmx.lamplitlabs.com/#/explore), the [cron expression tester](https://tools.lamplitlabs.com/cron) and [Ferret](https://github.com/lamplitlabs/ferret) are all built and checked with deterministic gates before any AI-assisted step touches them. The sequence is the product: manual until you know the failure modes, scripted until the failures are caught, and only then AI, with a human still deciding what ships.

## Related posts

- [How this blog is built and checked: Jekyll, tools/test.sh and AI agents that draft but never merge]({% post_url AI/2026-10-09-our-blog-pipeline-ai-assisted-publishing %})
- [AI SDLC for .NET Teams: a phase-by-phase guide]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [AI SDLC: gating AI coding agent pull requests before merge]({% post_url AI/2026-11-20-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: coding agents in the dev lifecycle and their handoff points]({% post_url AI/2026-11-18-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %})
