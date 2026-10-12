# Writing a post for this blog

Every research or improve job that ends with "publish a post" must reference
this checklist in its brief. It exists because too many jobs finish without a
change: the writer has a topic but no image, or an image but a topic outside the
blog's scope. Hitting every box below is what turns a brief into a landed post
that passes `bash tools/test.sh`.

## 1. Pick a topic from the checklist

Each post must sit in exactly one of these four topics, and the brief must name
which one. Pick the folder to match; `folder-categories` in `tools/test.sh`
fails the build when `categories:` does not include the lowercased folder name.

| Topic | Folder | What readers come here for | Recent example |
| --- | --- | --- | --- |
| **AI SDLC** | `_posts/AI/` | Coding agents in the development lifecycle: gates, hand-off points, review, test generation, migrations, debugging. Title prefix `AI SDLC:`. | `AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge.md` |
| **Enterprise AI** | `_posts/AI/` | Running Azure OpenAI in production: APIM, quotas, cost, observability, governance, data residency, RAG vs fine-tuning. Title prefix `Enterprise AI:`. | `AI/2026-10-12-enterprise-ai-azure-openai-data-residency-compliance-checklist.md` |
| **Performance** | `_posts/Performance/` | Measured comparisons with numbers: .NET, Go, Rust, Java, Node, databases, vector stores, LLM serving. | `Performance/2026-10-12-go-vs-rust-ai-inference-gateway-latency-memory.md` |
| **Own products** | `_posts/AI/` (tools) or `_posts/Automation/` (pipeline) | A walkthrough of one tool on `tools.lamplitlabs.com` (token counter, text chunker, schema builder, ...) or of this blog's own publishing pipeline, with screenshots of the product. | `AI/2026-10-12-token-counter-checking-prompt-size-and-context-window-fit.md` |

Programming-language comparisons go under `_posts/Languages/` and count as
**Performance** when they carry measurements, otherwise they are out of scope
for a research brief. Beginner, OData and Automation posts are welcome but are
not what a research brief should default to.

A brief that cannot name one of the four topics should not be planned as
"publish a post"; report it as a finding instead.

## 2. Bring the images before writing

`image-coverage` and `body-image-coverage` in `tools/test.sh` report every post
without a front-matter `image:` or an inline `![...]()` image. The target is
`0 missing`; a post without images moves the count the wrong way, so the brief
must list the images it will ship:

- One header card at `assets/img/headers/<folder>/<slug>.webp`, referenced as
  front-matter `image: { path: ..., alt: ... }`.
- At least one body image (`![alt](/assets/img/posts/<folder>/<name>.webp){:
  width="W" height="H" }`): a screenshot of the product, a benchmark chart or
  a table. For an **Own products** post the screenshot must show the real tool.
- Alt text that describes what is in the picture and is unique to this post
  (`alt-duplicate-coverage` flags verbatim repeats).
- Both files committed; `image-link-coverage` fails the build on a path that
  does not exist.

## 3. Front matter that passes the checks

```yaml
---
layout: post
title: "Enterprise AI: <one concrete claim>"
date: YYYY-MM-DD 00:00:00 +0200      # must equal the filename date (date-match-coverage)
categories: ai                       # lowercased folder name (folder-categories)
tags: ai enterprise azure-openai     # reuse existing tags; see TAG_SYNONYM_GROUPS in tools/test.sh
author: manishtiwari25
description: "50-160 characters, says what the reader gets."   # description-coverage fails outside that range
image:
  path: /assets/img/headers/ai/<slug>.webp
  alt: "What the header card shows"
---
```

Date the post no more than 14 days out and keep the future backlog at or below
10 posts (`future-backlog`).

## 4. End with `## Related`

Link two or three existing posts with `{% raw %}{% post_url Folder/YYYY-MM-DD-slug %}{% endraw %}`
under a `## Related` heading. `ai-related-coverage` counts posts without one
and `related-link-resolution` fails on a slug that does not exist.

## 5. The brief template

Copy this into the job's "publish a post" brief and fill every line:

```text
Topic:      AI SDLC | Enterprise AI | Performance | Own products
Folder:     _posts/<Folder>/
Title:      ...
Header:     assets/img/headers/<folder>/<slug>.webp - <what it shows>
Body image: assets/img/posts/<folder>/<name>.webp - <what it shows>
Related:    <2-3 existing post slugs>
Check:      bash tools/test.sh -> image-coverage and body-image-coverage still 0 missing
```
