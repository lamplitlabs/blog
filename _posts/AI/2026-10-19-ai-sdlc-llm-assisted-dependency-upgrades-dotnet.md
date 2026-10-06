---
layout: post
title: "AI SDLC: LLM-Assisted Dependency Upgrades for .NET - Major Version Bumps Without Losing the Weekend"
date: 2026-10-19 09:00:00 -0500
categories: ai
tags: ai sdlc dotnet csharp devops nuget azure enterprise
author: manishtiwari25
description: "How an LLM turns a red Dependabot major-version PR into a reviewed .NET patch, gated by build, tests and API-compat, with a human still pressing merge."
image:
  path: /assets/img/headers/ai/ai-sdlc-llm-dependency-upgrades-dotnet.webp
  alt: "Header card for LLM-assisted dependency upgrades showing breaking-change PRs needing manual edits falling from 41 to 6, median engineer time per major bump of 3.5 hours down from 11, and zero upgrade PRs merged without a green build"
---

The [production debugging post]({% post_url AI/2026-10-18-ai-sdlc-llm-assisted-production-debugging %}) was about the pager. This one is about the quietest backlog in the building: the Dependabot PRs nobody wants. Across roughly thirty-eight .NET services we had forty-seven major-version bumps land in one quarter, from `Microsoft.EntityFrameworkCore` and `Azure.Identity` to `Polly`, `FluentValidation` and `System.Text.Json` behaviour changes. Forty-one of them failed the build or the tests as opened, which meant an engineer had to read the release notes, find every call site and fix them by hand. Median cost was eleven hours per bump, and most of that was reading. Reading release notes and matching them to compiler errors is exactly the kind of text-heavy work an LLM is good at, so we put one in the loop. This post covers what the agent sees, what it is allowed to change, the gate that rejects it, and the numbers after one quarter.

![Diagram of the upgrade loop in five steps, Dependabot PR, evidence bundle of release notes and build errors and call sites, LLM patch proposal, CI gate and human review, followed by a table showing PRs needing hand edits falling from 41 of 47 to 6 of 47, median engineer time per bump falling from 11 hours to 3.5 hours and zero upgrade PRs merged without a green build](/assets/img/posts/ai/ai-sdlc-dependency-upgrade-loop-results.webp)

{% include feed-ads.html %}

## The rule, again: the agent proposes, CI gates, a human merges

Same posture as our other AI SDLC work. The agent cannot merge, cannot push to `main`, and cannot touch anything outside the branch Dependabot created. It opens a commit on that branch, the normal pipeline runs, and a human reviews a diff that is already green or already explained. Nothing about the review process changed; what changed is that the reviewer gets a working patch instead of a red PR.

## Trigger

A GitHub Actions workflow runs on `pull_request` for branches matching `dependabot/nuget/*`. It only does anything when two things are true: the bump crosses a major version, and the first CI run on the untouched PR failed. Minor and patch bumps that are green merge on their own after tests, as they always did. We did not want the agent anywhere near a PR that was already fine.

## What the agent reads

The worker is a .NET console app using the same Azure OpenAI client setup as the [structured outputs post]({% post_url AI/2026-09-29-structured-outputs-azure-openai-dotnet %}). It builds an evidence bundle, capped at about 8,000 tokens:

- the package name, old version and new version from the Dependabot PR body;
- the package's release notes and any `BREAKING` or `Migration` sections between the two versions, pulled from the NuGet package `releaseNotes` field and the repository's GitHub releases, trimmed to headings and bullets;
- the compiler errors and failed test names from the first CI run, with file and line;
- the source of every method that contains one of those error locations, fetched through Roslyn so the model sees real code;
- every other call site of the APIs named in the errors, found with Roslyn's `SymbolFinder.FindReferencesAsync`, because the compiler only reports the first failure per overload and the rest show up after you fix it.

The last bullet mattered most. Without the reference search the agent fixed three call sites, CI failed again on the fourth, and the loop took two extra rounds.

## What the agent produces

Structured edits only, no prose, no whole-file rewrites:

```csharp
public sealed record UpgradePatch(
    string Package,
    string FromVersion,
    string ToVersion,
    IReadOnlyList<FileEdit> Edits,
    IReadOnlyList<string> UnresolvedErrors,  // things it could not fix, surfaced to the reviewer
    string Summary);                          // three sentences max, goes in the PR comment

public sealed record FileEdit(
    string Path,
    int StartLine,
    int EndLine,
    string Replacement,
    string Reason);                           // which release-note line justified this
```

Each edit must cite a release-note line in `Reason`. If the model wants to change code and cannot point at a note that says why, the worker drops the edit and lists it under `UnresolvedErrors`. That rule removed almost all of the "while I was here" refactors the first version produced.

Edits are applied with Roslyn's `SourceText.WithChanges` rather than string replacement, so a stale line number fails loudly instead of corrupting a file.

## The CI gate

The patch commit runs through the normal pipeline plus three checks we added for this workflow:

1. `dotnet build -warnaserror` - the upgrade may not introduce a single new warning, because obsolete-API warnings are how the next breaking change announces itself.
2. The full test suite, including the integration tests behind Testcontainers. No subset, no "affected tests only".
3. `Microsoft.DotNet.ApiCompat` against the previous release's public surface for any project packed as a library. An upgrade that changes our own public API is a different conversation and gets kicked to a human immediately.

Nineteen of forty-seven patches were rejected by this gate in the quarter. Most of those were test failures the model could not see because the test ran against a database, and the agent gets one retry with the new failure appended to its bundle. After that it stops and writes what it tried in the PR comment. There is no third attempt; a loop that keeps trying is a loop that eventually tries something stupid.

## What the reviewer sees

A PR comment with the summary, the list of edits with their release-note citation, the unresolved errors if any, and the pipeline result. A typical one for the `Polly` 7 to 8 bump reads:

> Migrated 14 `Policy.Handle<T>().WaitAndRetryAsync(...)` call sites to `ResiliencePipelineBuilder` with `AddRetry`, per Polly 8 release notes "Policy classes are deprecated". Replaced `Context` dictionary usage in `OrderService.RetryHandler` with `ResilienceContext` properties. Unresolved: `PaymentClient.cs:88` uses a custom `IAsyncPolicy` wrapper with no documented equivalent.

That last sentence is worth the whole project. The reviewer goes straight to the one place that needs a human.

## Numbers after one quarter

- PRs needing manual edits after the bump: 41 of 47 before, 6 of 47 with the agent.
- Median engineer time per major bump: 11 hours before, 3.5 hours after. Most of the remaining time is review and the integration-test run.
- Bumps reverted after merge: 4 before, 1 after. The one was a `System.Text.Json` behaviour change that no test covered, which is a testing gap, not an agent failure, and it now has a test.
- Upgrade PRs merged without a green build: 0 before, 0 after. That number is the one we promised security would not move.
- Token cost: about $0.90 per attempt at current Azure OpenAI pricing, roughly $60 for the quarter. Not worth a dashboard.

## What did not work

- **Letting the agent bump the version itself.** We tried having it open the PR instead of Dependabot. It chose versions, it chose timing, and nobody trusted the result. Dependabot decides *what* to upgrade; the agent only answers *how*.
- **Transitive bumps.** When a major bump drags a transitive dependency along, the release notes the agent needs belong to a package it was never told about. We now include the `dotnet list package --include-transitive` diff in the bundle, which fixed about half of those cases.
- **Framework upgrades.** `net8.0` to `net9.0` across a solution is not a dependency upgrade and the same loop produced large, nervous diffs. We kept it out of scope.

## If you want to try it

Start with the gate, not the agent. If your pipeline does not already run `-warnaserror`, the full suite and an API-compat check on dependency PRs, add those first; they are what make it safe to let anything propose a patch. Then start with one noisy package family, require a release-note citation for every edit, cap retries at one, and keep a human on merge. Measure engineer time per bump and reverts after merge before and after, and stop if either goes the wrong way.

## Related

- [AI SDLC: LLM-Assisted Production Debugging for .NET Services, With Guardrails]({% post_url AI/2026-10-18-ai-sdlc-llm-assisted-production-debugging %})
- [AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %})
- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %})
- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
