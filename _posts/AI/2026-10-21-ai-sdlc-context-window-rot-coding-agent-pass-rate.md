---
layout: post
title: "Context-window rot: agent pass@1 falls 45 points before the window is even half full"
description: "Gate logs from 96 seeded coding tasks: one growing agent thread loses 45 pass@1 points by 192K tokens while fresh sessions hold 80%."
date: 2026-10-21 08:05:00 +0000
categories: [ai]
tags: [ai-sdlc, coding-agents, llm, evaluation, context-window]
image:
  path: /assets/img/posts/ai/context-window-rot-pass-rate.webp
  alt: "Line chart from our gate logs: one growing agent thread drops from 86% to 41% pass@1 as context grows from 8K to 192K tokens, while a fresh session with the same total tokens holds near 80%."
---

We kept feeding our coding agent more context and it kept getting worse — long before the window was full. This is the chart that made us stop.

The [merge gates post]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) described the five gates an agent PR passes here before a human sees it. Those gates give us something most anecdotes about "context rot" lack: a log of every agent patch attempt, the size of the context window at patch time, and whether the patch passed its seeded failing test. This post is what that log showed when we sliced it by context size.

## The experiment we did not mean to run

We never set out to measure context rot. We set out to fix bugs. Every seeded task in the log is the same shape: a failing test, a repository, and an agent told to make the test pass. What varied was how the agent got its context. Some runs started fresh and read only what the retrieval step handed them. Others were continuations — one long thread where the agent had already explored, run tools, mis-run tools, pasted CI output, and re-read files it had already seen.

Ninety-six tasks, weeks 34 through 41, same model, same seed set. We bucketed every patch attempt by the token count in the window at the moment the agent produced its diff, and plotted pass@1 — did the first patch pass the seeded test.

![Line chart comparing pass@1 across context sizes: a single growing thread degrades from 86% at 8K tokens to 41% at 192K, while fresh sessions holding the same total tokens stay between 80% and 87%.](/assets/img/posts/ai/context-window-rot-pass-rate.webp)

The orange line is the uncomfortable one. At 8K tokens the agent passes 86% of tasks. At 64K — a third of the advertised window — it is down to 68%. At 192K it passes 41%, worse than a coin flip on tasks calibrated so a fresh agent passes four out of five. The green dashed line is the control: same tasks, same model, same *total* tokens spent, but spent across short fresh sessions instead of one long thread. It barely moves. The model did not get dumber; the thread got longer.

## What actually fills the window

The natural reading is "long conversations confuse models", but that reading did not survive the second cut. We took the 64K-bucket tasks and grouped them by what was filling the window, not how much.

![Bar chart showing pass@1 at 64K tokens by window content: diffs-only baseline 79%, adding CI logs and test output 64%, adding the full tool-call transcript 48%, adding whole-repo file dumps 22%.](/assets/img/posts/ai/context-window-rot-what-fills-window.webp)

Diffs only — the retrieval step from our [eval-harness CI post]({% post_url AI/2026-10-19-ai-sdlc-llm-eval-harness-ci-gates-dotnet %}), which hands the agent the failing test and the handful of files it touches — holds the 79% baseline. Add raw CI logs and test output and it drops 15 points: the agent starts quoting failure messages instead of fixing them. Add the full tool-call transcript, every `grep` and `cat` the agent ran, and it drops to 48%: the agent starts treating its own earlier dead ends as facts. Worst of all is whole-repo file dumps at 22% — the agent edits a plausible-looking file it happened to see instead of the right one, which is exactly the failure class the [defect-classes checklist]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %}) calls "fixed the wrong file cleanly".

The pattern across all three drops is the same: every token in the window that is *not* the failing test or the target file is a small vote for the wrong patch, and the votes add up.

## What we changed in the harness

Three changes came out of this log, all boring, all effective.

1. **Restart, do not continue.** When an agent's exploration thread crosses 32K tokens, the harness now throws the thread away and starts a fresh session seeded with only the failing test, the touched files, and a three-line summary of what was tried. Pass@1 on those tasks went from 61% (continue) to 78% (restart) in the following two weeks. A three-line summary of a dead end beats twelve thousand tokens of it.
2. **CI output is summarized before it is re-fed.** The agent never sees raw logs twice. The first read is raw; every subsequent read is a ten-line extraction of the failing assertion. This alone recovered about half the "CI logs" bar's drop.
3. **The gate rejects patches to files outside the retrieval set** unless the agent's summary justifies the new file. This is the same instinct as the scope gate in the merge-gates post, applied one step earlier: it catches the "edited a plausible file it happened to see" failure while it is still cheap.

None of this required a newer model or a bigger window. It required treating the window as a budget, the way we already treat latency and cost.

## What we would tell a team running agents today

- **Log context size at patch time.** Without that one field, "the agent got worse" is a vibe. With it, the orange line is undeniable and you can argue about causes instead of about whether anything happened.
- **Measure rot on your own tasks, not a benchmark.** The published long-context evals test retrieval of planted facts. Coding-agent rot is different: the failure is not forgetting, it is overweighting the wrong memories. Only your own seeded tasks show that.
- **Prefer many short sessions over one long one**, even when the long one fits. The green line says you lose almost nothing by restarting and the orange line says you lose a great deal by not.
- **Summarize tool output on the second read.** Raw logs are load-bearing exactly once.

The window is a budget. Spend it on the failing test and the files that fix it, and evict everything else without sentiment.

## Related

- [Gating AI coding-agent pull requests before merge: five checks that caught what review missed]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %})
- [An LLM eval harness with CI gates: catching model regressions before they ship]({% post_url AI/2026-10-19-ai-sdlc-llm-eval-harness-ci-gates-dotnet %})
- [Reviewing AI-generated code: the defect-class checklist that catches what vibe review misses]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %})
- [Model context window chart: how much fits before you start trimming]({% post_url AI/2026-10-12-model-context-window-chart-how-much-fits-before-you-start-trimming %})
