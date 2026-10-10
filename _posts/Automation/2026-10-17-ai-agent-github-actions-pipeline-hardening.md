---
layout: post
title: "AI SDLC for Automation: Letting a Coding Agent Harden GitHub Actions Workflows, One PR at a Time"
date: 2026-10-17 00:00:00 +0200
categories: [automation, ai, devops, github]
tags: [github-actions, ai, sdlc, automation, ci, devops, security, enterprise]
author: manishtiwari25
description: "How an AI coding agent hardens GitHub Actions workflows: pinned actions, least-privilege tokens, timeouts and concurrency, delivered as reviewable PRs."
image:
  path: /assets/img/headers/automation/ai-agent-github-actions-pipeline-hardening.webp
  alt: "Header card for AI-assisted GitHub Actions hardening showing the loop: failed or audited workflow run, agent diagnoses, agent proposes a workflow diff, actionlint and a dry run check it, human reviews and merges"
---

Two of the older posts in this category show how to make GitHub Actions do work for you: [exporting Draw.io diagrams on every push]({% post_url Automation/2025-04-16-automate-drawio-github-actions %}) and [posting an RSS feed to social media on a schedule]({% post_url Automation/2024-02-11-auto-post-RSS-feed-to-social-media-using-github %}). Both of those workflows, as first written, had the same four problems almost every hand-written workflow has: actions pinned to a floating tag, a default `GITHUB_TOKEN` with write access to everything, no `timeout-minutes`, and no `concurrency` group so two pushes in a minute run twice. None of that breaks the pipeline on day one. It breaks it on the day a tag is moved, a runner hangs for six hours, or a fork PR gets to run with more permissions than it should.

This post is about the agent we put in front of those workflows. It follows the same rule as the rest of the [AI SDLC series]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}): *AI drafts, humans decide, something deterministic checks*. The agent never pushes to `main`; it opens a PR with one hardening change and the evidence for it.

## What "hardening" means here

Across 23 workflow files in 9 repositories we audited the same list by hand first, so the agent has a fixed rubric rather than an open-ended "make it better":

| Check | Why it matters | Deterministic verifier |
| --- | --- | --- |
| Third-party actions pinned to a commit SHA, not `@v4` | A moved tag is a supply-chain change you did not review | `actionlint` plus a regex for `uses: .*@[0-9a-f]{40}` |
| `permissions:` declared at workflow or job level | Default token can write contents, packages and PRs | `actionlint` warns on missing `permissions` |
| `timeout-minutes` on every job | A hung runner burns minutes and blocks the queue | YAML lint rule |
| `concurrency:` with `cancel-in-progress` for PR workflows | Two pushes in a minute run twice; the older one is wasted | YAML lint rule |
| Caches keyed on a lockfile hash | A cache keyed on the branch name never invalidates | Regex on `key:` |
| Retried steps have a bounded retry, not `continue-on-error: true` | `continue-on-error` turns a real failure into a silent one | Regex |

The verifier column is the important one. Every rubric item has a check that does not involve an LLM, so a PR from the agent is either green against the rubric or it is not.

## The trigger: a failed or flaky run

The agent is a GitHub App installed on the org. It wakes up on two events:

1. `workflow_run.completed` with `conclusion: failure` on a default-branch run.
2. A weekly `schedule` that audits every workflow file against the rubric, whether or not anything failed.

For a failed run it pulls the job logs with the Actions API, trims them to the last failing step plus 80 lines of context, and asks the model one structured question: *Is this failure caused by the workflow definition, by the code under test, or by the environment (runner, network, external service)?* The answer is a JSON object with a `cause` enum and a `confidence` number, the same structured-output pattern from the [Azure OpenAI structured outputs post]({% post_url AI/2026-09-29-structured-outputs-azure-openai-dotnet %}).

Only `cause: workflow` and `cause: environment` continue. `cause: code` is handed to the [flaky test triage agent]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %}), which owns that problem; this agent does not touch application code at all.

## The fix: a workflow diff with a reason

For each rubric violation the agent produces a minimal patch to the workflow YAML and a one-paragraph justification that must cite the rubric row. Here is the diff it proposed for the Draw.io export workflow from the earlier post, trimmed:

{% raw %}
```diff
 name: Export Draw.io diagrams
 on:
   push:
     paths: ["docs/**/*.drawio"]
+permissions:
+  contents: write   # commits the exported PNGs back; nothing else
+concurrency:
+  group: drawio-export-${{ github.ref }}
+  cancel-in-progress: true
 jobs:
   export:
     runs-on: ubuntu-latest
+    timeout-minutes: 10
     steps:
-      - uses: actions/checkout@v4
+      - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
-      - uses: rlespinasse/drawio-export-action@v2
+      - uses: rlespinasse/drawio-export-action@3c7aff6e2bef2a76d9f3b1b1b0a4e1cda7b84d4f # v2.6.0
```
{% endraw %}

The justification it attached: *"`contents: write` is required because the final step commits PNGs; no other scope is used. Pinned both actions to the SHA behind their current tag; the comment keeps the human-readable version. Added a 10 minute timeout: the longest recorded run of this job in the last 90 days was 2m41s."*

That last sentence is the kind of thing a human reviewer would otherwise have to look up, and it is why the agent is given the run history, not just the file.

![Screenshot-style mockup of the agent's pull request on a GitHub Actions workflow: title Harden drawio-export workflow, four rubric findings each with a check mark, the YAML diff pinning actions to SHAs and adding permissions, timeout and concurrency, and three green status checks for actionlint, workflow dry run and rubric verifier](/assets/img/headers/automation/ai-agent-workflow-hardening-pr.webp){: width="1200" height="820" }

## The deterministic gate before a human sees it

The agent's branch runs three checks before it is allowed to open the PR; if any fail, the agent gets one retry with the error text, then gives up and files an issue instead.

1. **`actionlint`** on every changed workflow file. This catches invalid YAML, unknown keys, bad `{% raw %}${{ }}{% endraw %}` expressions and shellcheck findings in `run:` blocks.
2. **A dry run** of the changed workflow with `act -n` where the workflow is runnable locally, or `workflow_dispatch` on the agent's branch where it is not. The dry run must reach the same step that originally failed.
3. **The rubric verifier**, a 60-line script that re-checks every rubric row on the patched file and fails if the patch introduced a new violation (the common one is pinning to a SHA that does not resolve, because the model made it up).

Point three is why we never let the model type a SHA. The agent resolves tags to SHAs with the Git Refs API and substitutes the result into the diff after the model has written it. The model writes `@<PIN:v4.2.2>`; a tool call replaces the placeholder. A hallucinated SHA is the single most likely failure mode for this kind of agent, and it is also the easiest one to make impossible.

## What the human still does

The PR arrives with the diff, the justification, the three green checks and a link to the run that triggered it. The reviewer has three jobs:

- Decide whether the permission scope is actually the minimum. The agent errs on the side of what the workflow currently uses, which is not always what it should use.
- Check whether a `timeout-minutes` derived from history is sensible for a job whose runtime depends on input size.
- Merge or close. There is no "let the agent merge if checks pass" setting, and we have not been tempted to add one: a workflow change is a change to who can do what in the repository.

## Numbers after eight weeks

| Metric | Before | After 8 weeks |
| --- | --- | --- |
| Workflows with every action SHA-pinned | 3 / 23 | 23 / 23 |
| Workflows with explicit `permissions:` | 5 / 23 | 23 / 23 |
| Jobs without `timeout-minutes` | 41 | 0 |
| Agent PRs opened / merged / closed | - | 61 / 54 / 7 |
| Longest hung job (minutes) | 360 (the default) | 25 |
| Minutes spent on cancelled-by-concurrency runs | ~900 / month | ~40 / month |

The 7 closed PRs were all permission scope disagreements: the agent proposed `pull-requests: write` where the reviewer wanted a separate workflow with a narrower trigger instead. That is a judgment call, and it is correct that the agent lost it.

## Where it fell down

**Dependabot already does half of this.** Dependabot can bump pinned SHAs once they exist, but it will not introduce pins, permissions, timeouts or concurrency. The agent does the first pass; Dependabot keeps the pins fresh. If you only want the pinning, Dependabot plus a one-off script is cheaper than an agent.

**Composite and reusable workflows confuse it.** When a job calls `uses: ./.github/workflows/build.yml`, the rubric has to be applied to the callee, and the agent initially proposed `permissions:` on the caller that the callee then narrowed to nothing. We now run the rubric on the resolved call graph, not per file.

**Logs are noisy.** The first version sent the entire job log to the model; a 4 MB `dotnet restore` log cost more than the fix was worth. Trimming to the failing step plus context cut token cost by about 95% with no change in the `cause` classification accuracy on our 120-run labelled sample.

## Checklist if you want to try this

1. Write the rubric first, as a table with a deterministic verifier per row. If you cannot verify a row without an LLM, it is not ready for the rubric.
2. Run `actionlint` in CI today, before any agent exists. Half the value is there.
3. Never let the model write a SHA, a version number or a URL that must resolve; have a tool fill those in.
4. Start on `schedule`, not on `workflow_run`. A weekly audit PR is calmer than a bot replying to every red run.
5. Keep the merge button human. The agent is good at being thorough; it is not the one accountable for the repository.

## Related

- [Automate Draw.io Diagram Export with GitHub Actions]({% post_url Automation/2025-04-16-automate-drawio-github-actions %})
- [Automating RSS Feed Posts to Social Media Using GitHub: Say Hello To Ferret]({% post_url Automation/2024-02-11-auto-post-RSS-feed-to-social-media-using-github %})
- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
- [AI SDLC in Practice: Letting a Coding Agent Triage and Fix a GitHub Issue End-to-End]({% post_url AI/2026-10-04-ai-coding-agent-fix-github-issue-end-to-end %})
- [AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %})
