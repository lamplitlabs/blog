---
layout: post
title: "AI SDLC in Practice: Letting a Coding Agent Triage and Fix a GitHub Issue End-to-End"
date: 2026-10-04 09:00:00 -0500
categories: ai
tags: ai sdlc dotnet csharp copilot github testing enterprise
author: manishtiwari25
description: "Worked example of an AI coding agent on a real bug: triaging the GitHub issue, planning, writing the fix and test, running dotnet test and opening the PR."
image:
  path: /assets/img/headers/ai/ai-agent-github-issue-end-to-end.webp
  alt: "Five-step flow of an AI coding agent working a GitHub issue: triage issue, plan, write fix, run tests, open PR, with the note that the human approves the plan, reviews the diff and merges"
---

The [previous AI SDLC post]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}) laid out the rule *AI drafts, humans decide, something deterministic checks* phase by phase. This one is the same rule applied to a single bug, start to finish, with the agent's actual plan, diff and test output so you can see where the human sits in the loop and what the deterministic check caught.

The repository is a .NET 8 reporting library. The bug is a classic CSV one.

{% include feed-ads.html %}

## The issue

> **#412 Export to CSV drops rows when a cell contains a newline**
>
> When a note field contains a line break, the exported CSV has the row split across two physical lines. Excel shows the second half as a separate, mostly empty row. Repro: export any report where `Note` is `"line one\nline two"`.

Triage is where the agent earns its first keep. It reads the issue, searches the repo for the exporter, and comes back with a plan before touching a file. I run the agent with *plan first, edit only after approval*; the approval prompt at the bottom is the human gate.

![Agent plan for issue #412: reproduce with a failing test, root cause in WriteRow splitting on newline, fix by RFC 4180 quoting, run dotnet test, open PR](/assets/img/posts/ai/ai-agent-issue-plan.webp)

Two things to check in a plan like this before saying yes:

1. **Does step 1 reproduce before fixing?** A plan that goes straight to the fix has nothing to prove the fix works. Here it adds `Export_PreservesEmbeddedNewline` first, so there is a red test to turn green.
2. **Is the root cause stated as a claim you can verify?** "`WriteRow` splits on `\n` before quoting fields" is a 20-second check in the editor. It was true: someone had added the `Split('\n')` years ago to normalise line endings and it quietly destroyed multi-line cells.

The risk line is also worth reading. The agent searched for callers relying on one physical line per row and found none; if it had found some, that would have turned this into a design conversation, not a patch.

## The diff

With the plan approved the agent edits two files. This is the whole change:

![Diff of CsvExporter.cs replacing Split on newline with an RFC 4180 Quote helper, plus the new xUnit test Export_PreservesEmbeddedNewline](/assets/img/posts/ai/ai-agent-issue-diff.webp)

The `Quote` helper does what RFC 4180 asks for: a field containing a comma, a double quote, a CR or an LF is wrapped in quotes and embedded quotes are doubled. Everything else passes through untouched, so existing output for plain fields is byte-for-byte the same.

Reading the diff took me about three minutes, and this is the review I would give any colleague's PR, not a lighter one because an agent wrote it. The questions I actually asked:

- **Did it change the row terminator?** Yes, from `WriteLine` (platform-dependent) to an explicit `\r\n`. That is what RFC 4180 specifies and what Excel expects, but it is a behaviour change on Linux build agents, so it goes in the PR description. The agent had flagged it; I kept it.
- **Does the test assert the *right* value, not the current one?** The expected string has one data row with the newline inside quotes. That is the behaviour the issue asks for, not a snapshot of what the code happened to do.
- **Anything hallucinated?** No new `using`, no package reference, no API that does not exist. The compiler would have caught the last one anyway, which is the point of pairing every agent step with a deterministic check.

## The test run

The agent runs the suite itself and shows the result alongside the failure it got before the fix:

![dotnet test output: 87 passed, 0 failed, including Export_PreservesEmbeddedNewline; before the fix the same test failed with expected 1 data row, actual 2 rows](/assets/img/posts/ai/ai-agent-issue-tests.webp)

Red-then-green is the evidence I care about. The before-fix failure message, *expected 1 data row, actual 2 rows*, is the bug from #412 stated by a machine, and the after-fix line shows nothing else in the 87 tests moved. If the agent had skipped the "before" run I would have asked for it; a test that was never seen failing has not demonstrated anything.

## The pull request

The last step the agent takes is opening the PR. It is allowed to create the branch, push it and write the description; it is not allowed to merge, request reviewers or touch the issue labels. The description it wrote is short and, crucially, explains the diff in words so I can check the explanation against the code:

> Fixes #412. `CsvExporter.WriteRow` split each row on `\n` before writing, so a cell containing a newline became two physical rows. Fields containing `,`, `"`, CR or LF are now quoted per RFC 4180 and the row terminator is an explicit CRLF. Adds `Export_PreservesEmbeddedNewline`; full suite 87/87.

When the explanation and the code disagree, the code is usually wrong, so this paragraph is a cheap extra review tool rather than ceremony. CI ran the same `dotnet test` on the PR, a second reviewer who had not seen the agent session approved it, and I merged it. Elapsed time from reading the issue to merge: about forty minutes, of which the agent's part was under five.

## What to copy

- **Plan before edit, with an approval prompt.** The plan is where you catch a wrong root cause for the price of a paragraph instead of a diff.
- **Insist on a failing test first.** Red-then-green is the only proof the fix addresses the issue rather than the symptom.
- **Review the diff as if a person wrote it.** Look for behaviour changes outside the issue's scope (here, the CRLF terminator) and make sure they are called out in the PR.
- **Keep merge, reviewers and labels human.** The agent may open the PR; the team decides what happens to it.
- **Make the agent explain its diff in the PR body.** Disagreement between prose and code is a fast signal that something is off.

## Summary

- An AI coding agent triaged a real CSV bug, proposed a plan, wrote an RFC 4180 fix and a regression test, ran the suite red-then-green and opened a PR.
- Human gates were plan approval, diff review and merge; the deterministic checks were the compiler, the new failing test and the full suite in CI.
- The agent saved the mechanical minutes; the review discipline stayed exactly the same as for a human PR.

## Related posts

- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase](/posts/ai-sdlc-dotnet-teams/)
- AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It
- How This Blog Is Built and Checked: Jekyll, tools/test.sh and AI Agents That Draft but Never Merge
