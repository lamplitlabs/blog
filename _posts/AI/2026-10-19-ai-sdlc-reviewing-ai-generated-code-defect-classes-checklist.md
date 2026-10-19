---
layout: post
title: "AI SDLC: Reviewing AI-Generated Code - The Seven Defect Classes Green Tests Missed and the Checklist That Cut Escapes 65%"
date: 2026-10-19 05:00:00 +0530
categories: ai ai-sdlc
tags: ai ai-sdlc code-review coding-agents dotnet typescript testing quality
description: "Seven defect classes human reviewers found in 312 green coding-agent PRs, and the seven-item checklist that cut post-merge defects from 23 to 8 per 100 PRs."
image:
  path: /assets/img/headers/ai/ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist.webp
  alt: "Header card reading AI SDLC: reviewing AI-generated code, where 312 agent PRs actually broke and the 7-item review checklist, with a code snippet showing a silent catch-and-return-null fallback"
---

Every coding-agent pull request we merged last quarter arrived green. The build passed, the unit tests passed, the agent's own summary said the change was complete. We still logged 184 defects across 312 of those PRs, and 38 of them reached `main`. This post is about what the human reviewers found, why the automated gates did not find it first, and the short checklist that changed the numbers.

It sits between two earlier posts: [gating agent PRs before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) covers the mechanical gates, and [human vs agent PR review]({% post_url AI/2026-10-08-ai-sdlc-human-vs-agent-pr-review-test-coverage-quality %}) compares reviewers. Here the question is narrower: when a person opens an AI-written diff, what should they look for?

## The data

- 312 pull requests opened by coding agents (GitHub Copilot coding agent and an internal Claude-based agent) across nine .NET 8 and TypeScript services, June to September 2026.
- Every PR passed `dotnet build` / `tsc`, unit tests and the linters before a human saw it.
- Reviewers tagged each finding with a defect class in the PR comment. Post-merge defects were tagged from incident and bug tickets linked back to the PR.
- Weeks 1-6 used the team's ordinary review template. Weeks 7-12 added the seven-item checklist below to the PR template for agent-authored PRs only.

## The seven defect classes

![Horizontal bar chart of 184 defects in 312 agent PRs by class: silent error fallback 52, boundary and off-by-one 36, tests assert the mock 27, hallucinated API 24, duplicated existing helper 19, concurrency misuse 14, security 12; each bar split into caught by human review versus found after merge](/assets/img/posts/ai/ai-sdlc-reviewing-ai-generated-code-defects-by-class.webp)

### 1. Silent error fallback (52)

The single biggest class, and the one that most often escaped. The agent wraps the risky call, catches everything and returns a default so that the happy-path test passes:

```csharp
public async Task<Customer?> GetAsync(Guid id)
{
    try
    {
        return await _repo.FindAsync(id);
    }
    catch (Exception)
    {
        return null; // agent added: "handle errors gracefully"
    }
}
```

Nothing in the test suite exercises a database timeout, so the test stays green while a transient outage turns into "customer not found" for every caller. The TypeScript variant is `catch { return [] }` or `.catch(() => undefined)`. Eleven of the 52 reached production; three of those became incidents.

### 2. Boundary and off-by-one (36)

Pagination offsets never checked against the total, `Substring` on strings shorter than the assumed prefix, date ranges that include the end day in one place and exclude it in another. Agents produce idiomatic-looking loops and slices; they rarely write the test for the empty collection or the last page unless asked.

### 3. Tests that assert the mock (27)

The PR includes tests, coverage goes up, and the tests prove nothing:

```csharp
_mock.Setup(r => r.FindAsync(id)).ReturnsAsync(customer);
var result = await sut.GetAsync(id);
Assert.Equal(customer, result); // asserts the mock, not the behaviour
```

Twenty of 27 were caught in review once reviewers started reading test bodies instead of the coverage delta. This class is why we stopped treating a coverage increase as a positive signal on agent PRs.

### 4. Hallucinated API or overload (24)

A method that does not exist on that version of the library, or an overload with the parameters in a plausible but wrong order. Every one was caught before merge, because the compiler or a type check failed on the reviewer's machine when the agent's run had used a cached or different package. These cost review time rather than production incidents; the fix was pinning the agent's environment to the lockfile, covered in the [dependency upgrades post]({% post_url AI/2026-10-05-ai-sdlc-llm-assisted-dependency-upgrades-dotnet %}).

### 5. Duplicated existing helper (19)

A new `ParseIsoDate`, `NormaliseEmail` or retry wrapper next to one that already existed two folders away. Not a bug on day one, but four of these diverged within the quarter and produced inconsistent behaviour between endpoints. An `AGENTS.md` pointer to the shared utilities folder reduced this class noticeably in weeks 9-12.

### 6. Concurrency and async misuse (14)

`.Result` and `.Wait()` on async calls inside ASP.NET request handling, `Task.Run` wrapping already-async I/O, a shared `Dictionary` mutated from `Parallel.ForEach`. Half of these escaped review - the lowest catch rate of any class - because they look correct and only misbehave under load. These are the ones the checklist moves to a named reviewer.

### 7. Security (12)

String-concatenated SQL in a reporting query, a connection string pasted into a test fixture, user input reaching a `Process.Start` argument. Eleven of twelve were caught, mostly by the existing secret scanner and static analysis rather than by eyes. The one that escaped was a log line that included a bearer token.

## Why the gates missed them

The pattern across classes 1, 2, 3 and 6 is the same: the defect is in behaviour the test suite does not exercise, and the agent wrote both the code and the tests. An agent optimising for "tests pass" will, quite reasonably, write tests that pass. Compile and unit-test gates verify internal consistency of the PR, not its correctness against the system it lands in. That is what the human review slot is for, and the generic template ("does this look right?") was not pointing reviewers at the places AI code goes wrong.

## The seven-item checklist

This is the block we added to the PR template for agent-authored PRs. It is deliberately short enough to actually be done.

```markdown
## AI-authored PR review
- [ ] Every new `catch` either rethrows, logs with context, or is justified in a comment.
- [ ] Empty, single-item and last-page cases have a test or are provably unreachable.
- [ ] At least one new test would fail if the production code were deleted.
- [ ] No new helper duplicates something under `src/Shared` (searched by name and intent).
- [ ] No `.Result`, `.Wait()`, or `Task.Run` around I/O; shared state under parallelism is named.
- [ ] No string-built SQL/shell, no literals that look like credentials, no tokens in logs.
- [ ] I ran it locally, not just read it.
```

Item three is the one reviewers said changed their habits most: it forces reading a test for what it would catch, not whether it exists.

## What changed

![Bar chart of post-merge defects per 100 agent PRs over twelve weeks: weeks one to six between 21 and 26 under generic review, weeks seven to twelve between 6 and 12 after the seven-item checklist was added, with a dashed line marking the week the checklist was introduced](/assets/img/posts/ai/ai-sdlc-reviewing-ai-generated-code-post-merge-defects-before-after.webp)

- Post-merge defects per 100 agent PRs: 23.3 (weeks 1-6) to 8.2 (weeks 7-12), a 65% drop.
- Median review time per agent PR: 11 minutes to 16 minutes. Five extra minutes per PR against roughly 15 fewer post-merge defects per 100 PRs; the cheapest fix we made this year.
- Silent-fallback escapes went from 9 to 2. Concurrency escapes went from 5 to 2, and the remaining two were both in PRs where the named reviewer item was skipped.
- Agent PR acceptance rate did not fall. Reviewers requested changes more often, but the changes were small and the agent usually fixed them in one round.

## Caveats

This is one organisation's log, nine services, one quarter, and reviewers knew they were being measured. The checklist also coincided with an `AGENTS.md` update, so the duplicated-helper drop is not attributable to the checklist alone. Treat the classes as a starting taxonomy and the numbers as a reason to measure your own, as the [published-evidence post]({% post_url AI/2026-10-09-ai-sdlc-what-published-evidence-says-cycle-time-stability-defects %}) argues more generally.

## Related

- [AI SDLC: Gating AI coding agent pull requests before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [AI SDLC: Human vs agent PR review - test coverage and quality]({% post_url AI/2026-10-08-ai-sdlc-human-vs-agent-pr-review-test-coverage-quality %})
- [AI SDLC: AGENTS.md instruction files coding agents actually follow]({% post_url AI/2026-10-18-ai-sdlc-agents-md-instruction-files-coding-agents-actually-follow %})
