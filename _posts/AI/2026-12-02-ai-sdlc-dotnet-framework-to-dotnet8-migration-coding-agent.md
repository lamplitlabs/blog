---
layout: post
title: "AI SDLC: Migrating a .NET Framework 4.8 Service to .NET 8 with a Coding Agent - What It Did, What We Did, and the Numbers"
date: 2026-12-02 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp migration devops testing enterprise
author: manishtiwari25
description: "Splitting a .NET Framework 4.8 to .NET 8 migration between a coding agent and two engineers: the plan, the gates, two closed agent PRs, 11 days vs 7-9 weeks."
image:
  path: /assets/img/headers/ai/ai-sdlc-dotnet-framework-to-dotnet8-migration-coding-agent.webp
  alt: "Header card for migrating a .NET Framework 4.8 service to .NET 8 with a coding agent showing 312 files changed by the agent, 9 agent PRs, 4 rewritten by hand and 11 days wall clock"
---

Framework-to-modern .NET migrations are the kind of work nobody volunteers for: mechanical for 80% of the files, subtle for the remaining 20%, and the subtle part hides inside the mechanical part. That shape makes them a good test for a coding agent in the [hand-off points]({% post_url AI/2026-11-18-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %}) model: give the agent the mechanical work in bounded pull requests, keep humans on the parts where a plausible-looking change can be wrong. This post is the record of doing that for one 41k-line .NET Framework 4.8 service - WCF front, ASP.NET MVC admin, EF6 data layer - and moving it to .NET 8 in eleven working days.

![Table of migration work split between coding agent and humans for one 4.8 WCF and ASP.NET service: agent converted 9 projects to SDK-style, removed 184 System.Web call sites, ported 38 WCF operations, 121 EF queries and 212 integration tests; humans rewrote binary serialization and fixed 67 ConfigureAwait findings; agent did 71% of changed lines in 11 working days against 7-9 weeks estimated manually](/assets/img/posts/ai/ai-sdlc-dotnet8-migration-agent-vs-human-work-split.webp){: width="1400" height="820" }

{% include feed-ads.html %}

## Why the migration was planned around PRs, not around the agent

The first instinct was to point the agent at the solution and say "upgrade to .NET 8". We did that on a branch for an afternoon to see what happened. It produced a 9,000-line diff that compiled and failed 140 integration tests, and nobody could review it. So the real plan started from the other end: what is the list of PRs we would open if two engineers did this by hand, in what order, and which of those PRs can an agent own end-to-end?

That gave nine work items. Each became a scope contract - the list of projects and folders the agent was allowed to touch - and each agent PR had to pass the same [merge gates]({% post_url AI/2026-11-20-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) we use for every agent PR: provenance trailer, scope diff, sandboxed build and tests, mutation score on changed files, human review.

## Step 0: the upgrade assistant and a test baseline

Before the agent touched anything we ran the .NET Upgrade Assistant in analysis mode and committed its report to the repo. It is not a migration tool for a codebase like this one, but its inventory - which APIs are gone, which packages have no netstandard build - became the agent's input. The second thing we committed was a green baseline: 221 integration tests passing on 4.8 against a containerised SQL Server, with the run wired into CI. Without that number, every later "the tests pass" claim is meaningless.

## Work the agent owned end-to-end

**SDK-style projects and package references.** Nine `.csproj` files, `packages.config` to `PackageReference`, `AssemblyInfo` attributes folded into the project. The agent did this in one PR, the scope diff was clean, one review round. This is the work people expect agents to do and it does it well.

**System.Web removal.** 184 call sites using `HttpContext.Current`, `HttpUtility`, `HostingEnvironment` and friends. The agent introduced an `IRequestContext` abstraction, replaced the call sites, and updated the tests. 12 sites it could not resolve - mostly static accessors in a legacy logging helper - it listed in the PR description rather than guessing. We fixed those by hand on the same branch. Two review rounds.

**WCF to ASP.NET Core minimal API.** 38 service operations. The agent generated endpoints with the same contracts, kept the DTOs, and wrote a compatibility shim so the old SOAP clients could keep working behind a small translation layer. Six operations were rewritten by a human after review because the agent had turned streaming responses into buffered ones, which was correct to the contract and wrong for the two callers that depend on the stream. The gate that caught this was not a test - it was the reviewer reading the contract comments.

**Configuration.** `app.config` and `web.config` keys to `appsettings.json` and the options pattern. Fully automatic; the one human task was deciding which keys were secrets and moving them to Key Vault references, which is a decision and not a transformation.

**EF6 to EF Core 8.** 121 queries converted by the agent, 31 by hand. The 31 were the ones that relied on EF6 client-side evaluation - EF Core throws where EF6 silently pulled a table into memory. The agent flagged those correctly in most cases because the integration tests failed in the sandbox, and it proposed rewrites for 19 of them; we accepted 11 and rewrote 20 ourselves because the proposed LINQ was correct but generated SQL we would not want in production.

**Integration tests.** 212 of the 221 tests ported by the agent to xUnit with `WebApplicationFactory`; 9 depended on WCF-specific hosting and were rewritten by hand. This was the most valuable PR in the whole migration, because it meant every later PR had a real safety net.

## Work the agent did not own

**Binary serialization.** The service used `BinaryFormatter` for a cache layer. It is disabled in .NET 8 for good reason. The agent proposed `System.Text.Json` with a custom converter and the PR compiled and passed tests. We closed it. The cached payloads include polymorphic types across a version boundary, and the right answer was a versioned, explicit contract - a design decision, and a security one. An engineer did it in two days.

**Threading and `ConfigureAwait`.** The Upgrade Assistant and the agent together flagged 67 places where sync-over-async or missing `ConfigureAwait(false)` had been harmless under the ASP.NET synchronisation context and could deadlock or change behaviour under Kestrel. The agent's PR added `ConfigureAwait(false)` to all 67. We closed it: half of them were in code that should have been made properly async rather than papered over, and that is exactly the "correct code at the wrong level of abstraction" category from the gating post. A human took the list and fixed them deliberately.

## The numbers

Agent PRs: 9 opened, 7 merged, 2 closed. Of the 7 merged, 4 needed substantial human edits on the same branch before merge. The agent accounted for 71% of changed lines in the final diff. Wall clock was 11 working days for two engineers part-time against a pre-migration estimate of 7 to 9 engineer-weeks. Defects found in the first month in production: two, both in hand-written code (one in the serialization contract, one in a rewritten EF query). None in agent-written code that passed the gates - which says more about the gates and the ported tests than about the agent.

The honest summary is that the agent compressed the mechanical 80% from weeks to days, and the subtle 20% took exactly as long as it would have taken anyway, because it was the same people making the same decisions. The planning step - deciding up front which 20% that was - is what made the split work, and it is the step teams skip when they ask the agent to "upgrade the solution".

## Related

- [AI SDLC: Where Coding Agents Fit in the Development Lifecycle - Four Hand-off Points]({% post_url AI/2026-11-18-ai-sdlc-coding-agents-in-the-dev-lifecycle-handoff-points %})
- [AI SDLC: How We Evaluate and Gate AI Coding-Agent Pull Requests Before Merge]({% post_url AI/2026-11-20-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: LLM-Assisted Dependency Upgrades for .NET - Major Version Bumps Without Losing the Weekend]({% post_url AI/2026-10-19-ai-sdlc-llm-assisted-dependency-upgrades-dotnet %})
