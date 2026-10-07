---
layout: post
title: "How This Blog Is Built and Checked: Jekyll, tools/test.sh and AI Agents That Draft but Never Merge"
date: 2026-10-09 09:00:00 -0500
categories: ai
tags: ai sdlc jekyll github-pages automation agents devops testing
author: manishtiwari25
description: "Behind the scenes of this blog: the Jekyll setup, the six content checks in tools/test.sh, and the AI agent workflow where agents draft and humans merge."
image:
  path: /assets/img/headers/ai/our-blog-pipeline-ai-assisted-publishing.webp
  alt: "Header card showing the blog pipeline: a Markdown post flows into tools/test.sh with six checks plus html-proofer, then into the GitHub Pages Jekyll build"
---

Most of the posts here are about building things with .NET, Azure OpenAI and AI agents. This one is about the thing you are reading. The blog is itself a small product with users, defects and a test suite, and over the last year it has turned into a working example of the [AI SDLC loop]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}) I keep recommending: AI drafts, humans decide, and something deterministic checks. Here is how the pieces fit.

![Terminal output of tools/test.sh: Jekyll build done, then tag-case-duplicates, image-coverage 0/58, alt-coverage 0/58, body-image-coverage 18/58, description-coverage all 58 posts, folder-categories, and HTML-Proofer finished successfully](/assets/img/posts/ai/our-blog-pipeline-test-sh-output.webp)

{% include feed-ads.html %}

## The stack: Jekyll on GitHub Pages

The site is a plain [Jekyll](https://jekyllrb.com/) project using the Chirpy theme, built and deployed by GitHub Pages. There is no CMS, no database and no server-side code. A post is one Markdown file under `_posts/<Topic>/`, for example `_posts/AI/2026-10-09-our-blog-pipeline-ai-assisted-publishing.md`, with YAML front matter on top:

```yaml
---
layout: post
title: "How This Blog Is Built and Checked"
date: 2026-10-09 09:00:00 -0500
categories: ai
tags: ai sdlc jekyll
description: "One sentence, 50-160 characters, used for search snippets and the feed."
image:
  path: /assets/img/headers/ai/our-blog-pipeline-ai-assisted-publishing.webp
  alt: "What the header image shows"
---
```

Images live under `assets/img/headers/<topic>/` for the social card and `assets/img/posts/<topic>/` for screenshots and charts, all as WebP so a post with three screenshots still loads under 200 KB.

The Ruby toolchain is pinned with `.ruby-version` and `mise`, and `bundle install` puts the exact gem set from `Gemfile.lock` in place. Every contributor, human or agent, runs the same command locally that CI runs:

```bash
mise exec -- bash tools/test.sh
```

## The checks: what tools/test.sh refuses to ship

`tools/test.sh` started as the stock Chirpy script that builds the site and runs [html-proofer](https://github.com/gjtorikian/html-proofer) over `_site` to catch broken links and images. Each time a real reader-facing defect slipped through, we added one deterministic check for it. Today the script prints one line per check so an agent or a human can cite a single number instead of re-deriving it:

| Check | What it enforces | Why a reader cares |
|---|---|---|
| `tag-case` | A tag uses one letter case across all posts | `Azurite` and `azurite` otherwise become two tag pages with half the posts each |
| `image-coverage` | Every post has a header `image:`, a `![...]` or an `<img>` | Posts without images render as blank cards in the feed and on social |
| `alt-coverage` | Every header `image:` block has a non-empty `alt:` | Screen readers and image search otherwise get nothing |
| `body-image-coverage` | Reports posts with no inline screenshot (informational) | Tells us which posts to illustrate next |
| `description-coverage` | Every post has a `description:` of 50-160 characters | Search engines show it uncut; the RSS feed describes the post rather than the first paragraph |
| `folder-categories` | A post under `_posts/Performance/` lists `performance` in `categories` | Otherwise the post is missing from the category page its folder promises |

The coverage checks share one glob (`find _posts -name '*.md'`) and one denominator, so when a new post lands the count moves by exactly one and nothing else. The rule each line prints is the literal `grep` you can paste into a shell to reproduce it:

```bash
# posts without any image
grep -L -E '^image:|!\[|<img' $(find _posts -name '*.md')

# posts without a description
grep -L '^description:' $(find _posts -name '*.md')
```

Two things about these checks that took a few iterations to get right:

1. **Anchor the pattern.** The first version of `image-coverage` matched `image:` anywhere in the file, so a caption like `*Header image: generated with...*` counted as a header image. Anchoring to `^image:` fixed a false "pass".
2. **Fail loud, with the fix in the message.** A failing check lists the offending files *and* the one-line instruction to repair them. That matters more than usual here, because the thing reading the error is often an agent with no memory of the last run.

## The workflow: agents draft, checks gate, humans merge

The newer posts in the Performance and AI SDLC categories were drafted by AI agents working in a loop that looks like this:

1. **A suggestion card.** An agent or a human proposes one change as an experiment: one file, one variable, a hypothesis about what readers get, and the check that should move. For this post the card said: add one post on how the blog is built, with a screenshot, and `tools/test.sh` image and description coverage stays green with the post counted.
2. **Votes.** Other agents vote the card up or down with a reason. Cards that are pure tooling churn get voted down; cards tied to a reader-visible outcome float to the top.
3. **A throwaway clone.** The winning card becomes a job. The agent gets a fresh clone with the pinned Ruby and gems already installed, writes the post and images, and runs `tools/test.sh` until it is green.
4. **A signed commit on a review branch.** The agent commits with its own key and trailers naming the job. It cannot push, cannot add remotes and cannot touch dependencies; the runner copies the commit to a `pulse/<agent>/<job>` branch.
5. **A human reads it.** Nothing reaches the default branch without a person reading the diff and the rendered post.

The constraints are the interesting part. Agents are Tier 0/1 only: content and small fixes. Anything that smells like a decision (a new gem, a theme upgrade, deployment, analytics) is a hard stop and comes back as a question for the owner rather than a commit. The constitution and the evaluators that score suggestions live in `docs/evolution/` and are owner-only files; an agent branch that touches them is simply not landed.

## What the numbers say

Since the checks and the agent loop went in, the practical outcomes for readers have been:

- **Zero posts without an image or alt text**, down from roughly a third of the archive. The feed no longer has blank cards.
- **Every post has a search-length description**, so Google and the RSS feed stop showing a truncated code block as the summary.
- **Zero broken internal links at build time**, because html-proofer runs on every change and the "Related posts" lists the agents add use `{% raw %}{% post_url %}{% endraw %}`, which fails the Jekyll build if the target file is renamed.
- **Related-post lists across the Performance series**, something a human never got around to and an agent did in one afternoon across four posts.

What has *not* changed is the editorial bar: a post that passes every check can still be wrong, boring or off-topic, and that is exactly the judgement that stays with a human.

## Try it on your own Jekyll site

If you run a Jekyll blog, the cheapest wins are the two anchored `grep -L` checks above wrapped in a script that `set -eu` fails on. Add html-proofer after that. Only once the deterministic checks exist does it make sense to let an AI agent draft posts, because then "did the agent break the site?" is a question a script answers in ten seconds, and the human review can spend its time on whether the post is worth reading.

## Our Products

The same "AI drafts, checks gate, humans merge" habit shapes the tooling we ship at Lamplit Labs. Our flagship is the [EDMX Trimmer and OData metadata explorer](https://edmx.lamplitlabs.com/#/explore), which turns a multi-megabyte D365 or OData `$metadata` file into just the entities, enums and types your client actually needs. Our platform also includes the [cron expression tester](https://tools.lamplitlabs.com/#/cron) for Azure Functions timer triggers and [Ferret](https://github.com/lamplitlabs/ferret), our open-source Go toolkit for posting to social APIs such as Threads and LinkedIn. All of them are built and checked with the same kind of deterministic gates described above.

![Side-by-side flow showing an AI coding agent's plan for a GitHub issue, used as the drafting step that precedes the deterministic checks in our tooling pipeline](/assets/img/posts/ai/ai-agent-issue-plan.webp)

## Related posts

- [AI SDLC for .NET Teams: a phase-by-phase guide]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [AI SDLC: how to measure an AI code-review agent before you trust it]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %})
- [An AI coding agent fixing a GitHub issue end to end]({% post_url AI/2026-10-04-ai-coding-agent-fix-github-issue-end-to-end %})
