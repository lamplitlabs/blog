---
layout: post
title: "AI SDLC: Running an LLM Eval Harness as a CI Quality Gate in .NET - Thresholds, Regression Budgets and the Pipeline That Blocks Prompt Drift"
date: 2026-10-19 09:00:00 +0530
categories: ai ai-sdlc
tags: ai ai-sdlc dotnet csharp testing evaluation prompts azure openai github-actions ci
description: "Turn an LLM eval suite into a CI gate in .NET: a harness with four metrics, a diff against main, a regression budget and a GitHub Actions job that fails the PR."
image:
  path: /assets/img/headers/ai/ai-sdlc-llm-eval-harness-ci-gates-dotnet.webp
  alt: "Header card reading AI SDLC: LLM eval harness as a CI quality gate in .NET, with a terminal showing an eval run of 120 cases where the regression budget check fails with 5 regressions against a budget of 3"
---

The [prompt regression tests post]({% post_url AI/2026-10-02-testing-llm-prompts-dotnet %}) ended with a nightly live run that scored the real model. That caught drift, but it caught it the morning after the prompt change had merged. This post closes the gap: the same eval suite runs **on the pull request**, compares the branch against `main`, and fails the check when quality drops. The harness is a small .NET console app, the gate is forty lines of YAML, and everything here is copy-and-adapt.

## What a gate needs that a test suite does not

An xUnit test is pass or fail per case. An eval gate has to answer a different question: *is this prompt change acceptable?* Four things turned out to matter:

1. **Metrics, not assertions.** A single wrong label out of 120 should not block a PR; a 3% drop in exact match should. The harness emits scores, and the gate applies thresholds.
2. **A baseline from `main`.** Absolute thresholds catch collapses. Only a diff against the current `main` catches a prompt that got slightly worse on the cases it used to get right.
3. **A regression budget.** The number of individual cases that flipped from pass to fail. This is the metric reviewers actually read, because it comes with case ids they can open.
4. **Determinism where possible.** `temperature = 0`, a pinned model deployment, a fixed case order and a recorded-response mode for the cheap first pass.

## The harness: `tools/PromptEval`

One console project, no framework. It reads a JSONL suite, runs the prompt under test, scores each case and writes a JSON report. The data shapes:

```csharp
public sealed record EvalCase(
    string Id,
    string Input,
    string Expected,          // expected label or canonical answer
    string[]? MustContain,    // optional substrings for free-text answers
    string? Rubric);          // optional judge rubric for this case

public sealed record CaseResult(
    string Id,
    bool Exact,
    bool Schema,
    double Judge,
    string Actual,
    int PromptTokens,
    int CompletionTokens,
    long Ms);

public sealed record EvalReport(
    string Suite,
    string PromptVersion,
    string Model,
    DateTimeOffset RunAt,
    IReadOnlyList<CaseResult> Cases)
{
    public double ExactRate  => Cases.Average(c => c.Exact ? 1.0 : 0.0);
    public double SchemaRate => Cases.Average(c => c.Schema ? 1.0 : 0.0);
    public double JudgeMean  => Cases.Average(c => c.Judge);
    public double CostUsd    => Cases.Sum(c => c.PromptTokens * 0.15e-6 + c.CompletionTokens * 0.60e-6);
}
```

The runner is deliberately boring. It uses the same `IChatClient` abstraction as the production code so the prompt is exercised exactly as it ships:

```csharp
public sealed class EvalRunner(IChatClient chat, IJudge judge, int concurrency = 8)
{
    public async Task<EvalReport> RunAsync(
        string suite, string promptVersion, string systemPrompt,
        IReadOnlyList<EvalCase> cases, CancellationToken ct)
    {
        var results = new CaseResult[cases.Count];
        using var gate = new SemaphoreSlim(concurrency);

        await Parallel.ForEachAsync(
            Enumerable.Range(0, cases.Count),
            new ParallelOptions { MaxDegreeOfParallelism = concurrency, CancellationToken = ct },
            async (i, token) =>
            {
                var c = cases[i];
                var sw = Stopwatch.StartNew();
                var response = await chat.GetResponseAsync(
                    [new ChatMessage(ChatRole.System, systemPrompt),
                     new ChatMessage(ChatRole.User, c.Input)],
                    new ChatOptions { Temperature = 0, ResponseFormat = ChatResponseFormat.Json },
                    token);

                var text = response.Text;
                var schemaOk = ClassifyOutput.TryParse(text, out var parsed);
                var exact = schemaOk && string.Equals(parsed!.Label, c.Expected, StringComparison.Ordinal);
                var judgeScore = c.Rubric is null ? (exact ? 1.0 : 0.0)
                                                  : await judge.ScoreAsync(c, text, token);

                results[i] = new CaseResult(c.Id, exact, schemaOk, judgeScore, text,
                    response.Usage?.InputTokenCount ?? 0, response.Usage?.OutputTokenCount ?? 0,
                    sw.ElapsedMilliseconds);
            });

        return new EvalReport(suite, promptVersion, chat.Metadata.ModelId ?? "?", DateTimeOffset.UtcNow, results);
    }
}
```

Two notes on the scoring:

- **`Schema`** is the parse-and-validate check from the earlier post. It should be 1.000 always; anything less means the prompt started emitting Markdown fences or extra keys, and that is a hard fail regardless of the other metrics.
- **`Judge`** is an LLM-as-judge score, used only for the cases that carry a `Rubric`. It is the noisiest metric, so it has the loosest threshold and never contributes to the regression count on its own.

## Comparing against the baseline

The gate logic lives in one class so it can be unit tested without any model call:

```csharp
public sealed record GateConfig(
    double MinExact = 0.93,
    double MinSchema = 1.00,
    double MinJudge = 0.88,
    int MaxRegressions = 3,
    double MaxCostUsd = 0.50);

public sealed record GateOutcome(bool Passed, IReadOnlyList<string> Lines, IReadOnlyList<string> RegressedIds);

public static class Gate
{
    public static GateOutcome Evaluate(EvalReport pr, EvalReport? baseline, GateConfig cfg)
    {
        var lines = new List<string>();
        var passed = true;

        void Check(string name, double main, double value, double threshold, bool higherIsBetter = true)
        {
            var ok = higherIsBetter ? value >= threshold : value <= threshold;
            passed &= ok;
            lines.Add($"{name,-12}{main,6:0.000}{value,8:0.000}{value - main,+8:0.000;-8:0.000}   {(higherIsBetter ? ">=" : "<=")} {threshold:0.000}   {(ok ? "ok" : "FAIL")}");
        }

        Check("exact",  baseline?.ExactRate  ?? double.NaN, pr.ExactRate,  cfg.MinExact);
        Check("schema", baseline?.SchemaRate ?? double.NaN, pr.SchemaRate, cfg.MinSchema);
        Check("judge",  baseline?.JudgeMean  ?? double.NaN, pr.JudgeMean,  cfg.MinJudge);
        Check("cost",   baseline?.CostUsd    ?? double.NaN, pr.CostUsd,    cfg.MaxCostUsd, higherIsBetter: false);

        var regressed = new List<string>();
        if (baseline is not null)
        {
            var before = baseline.Cases.ToDictionary(c => c.Id, c => c.Exact && c.Schema);
            regressed = pr.Cases
                .Where(c => before.TryGetValue(c.Id, out var wasOk) && wasOk && !(c.Exact && c.Schema))
                .Select(c => c.Id)
                .ToList();
            var ok = regressed.Count <= cfg.MaxRegressions;
            passed &= ok;
            lines.Add($"regressions   -  {regressed.Count,6}        -   <= {cfg.MaxRegressions}        {(ok ? "ok" : "FAIL")}");
        }

        return new GateOutcome(passed, lines, regressed);
    }
}
```

The regression budget is the piece we iterated on most. The first version was `MaxRegressions = 0`; it blocked almost every prompt change, because any non-trivial rewording moves two or three borderline cases, often in exchange for fixing ten others. A budget of 3 on a 120-case suite, combined with the absolute exact-match floor, let real improvements through while still stopping the "added one helpful sentence, lost the Billing label" class of change. Pick the budget from your own suite size: roughly 2-3% of cases has held up across three suites so far.

`Program.cs` wires it together and sets the exit code, which is all the CI system needs:

```csharp
var outcome = Gate.Evaluate(report, baseline, cfg);
Console.WriteLine("metric      main    pr      delta   threshold   result");
foreach (var l in outcome.Lines) Console.WriteLine(l);
if (outcome.RegressedIds.Count > 0)
    Console.WriteLine($"regressions vs main: {string.Join(' ', outcome.RegressedIds)}");

await File.WriteAllTextAsync(outPath, JsonSerializer.Serialize(report, JsonOpts));
if (!outcome.Passed)
{
    Console.WriteLine($"##[error] prompt-eval gate failed: {outcome.RegressedIds.Count} regressions > budget {cfg.MaxRegressions}");
    return 1;
}
return 0;
```

## The pipeline

Two eval jobs run on every PR that touches `prompts/**` or `eval/**`. The first uses the recorded-response fake from the earlier post and is free; it catches schema and parsing breakage in under a minute. The second runs live against a pinned deployment, downloads the latest `main` report as the baseline, and applies the gate.

![Screenshot of a GitHub Actions run for PR 482 named prompt-eval: the job list shows build-and-unit-tests and prompt-eval recorded passing, prompt-eval live with 120 cases and compare-with-baseline failing and publish-report skipped; the log pane shows the PromptEval table with exact 0.942, schema 1.000, judge 0.91 all ok, regressions 5 against a budget of 3 marked FAIL, cost 0.21 USD ok, and the error line prompt-eval gate failed](/assets/img/posts/ai/ai-sdlc-llm-eval-harness-ci-pipeline-run.webp)

{% raw %}
```yaml
name: prompt-eval
on:
  pull_request:
    paths: ["prompts/**", "eval/**", "tools/PromptEval/**"]
  push:
    branches: [main]
    paths: ["prompts/**", "eval/**"]

permissions:
  contents: read
  id-token: write
  pull-requests: write

jobs:
  eval-recorded:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with: { dotnet-version: 8.0.x }
      - run: dotnet run -c Release --project tools/PromptEval -- --suite eval/classify.jsonl --prompt prompts/classify.md --mode recorded

  eval-live:
    needs: eval-recorded
    runs-on: ubuntu-latest
    environment: prompt-eval          # holds the endpoint; keyless via OIDC
    concurrency: { group: prompt-eval-${{ github.ref }}, cancel-in-progress: true }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-dotnet@v4
        with: { dotnet-version: 8.0.x }
      - uses: azure/login@v2
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      - name: Download main baseline
        if: github.event_name == 'pull_request'
        uses: dawidd6/action-download-artifact@v6
        with:
          workflow: prompt-eval.yml
          branch: main
          name: eval-report-main
          path: artifacts/main
          if_no_artifact_found: warn
      - name: Run eval and gate
        env:
          AZURE_OPENAI_ENDPOINT: ${{ vars.AZURE_OPENAI_ENDPOINT }}
          AZURE_OPENAI_DEPLOYMENT: gpt-4o-mini-2024-07-18   # pinned, see the retirement gate post
        run: |
          dotnet run -c Release --project tools/PromptEval -- \
            --suite eval/classify.jsonl --prompt prompts/classify.md --mode live \
            --baseline artifacts/main/classify.json --out artifacts/pr/classify.json
      - name: Upload report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: ${{ github.ref == 'refs/heads/main' && 'eval-report-main' || 'eval-report-pr' }}
          path: artifacts/pr/classify.json
```
{% endraw %}

Three details that saved us debugging time:

- **Pinned deployment name.** A floating `gpt-4o-mini` alias means the baseline and the PR can be scored by different model versions and the diff is meaningless. The [model retirement gate post]({% post_url AI/2026-10-14-enterprise-ai-azure-openai-model-retirement-upgrade-gate %}) covers how to roll the pin forward deliberately.
- **`concurrency` with `cancel-in-progress`.** Each live run costs about twenty cents and four minutes; a reviewer pushing three fix-up commits should not triple that.
- **Baseline refreshed on push to `main`.** The `push` trigger runs the same job without a baseline and uploads `eval-report-main`, so the next PR diffs against the prompt that is actually live.

The report is also posted as a PR comment (the `publish-report` job in the screenshot, omitted from the YAML above for length): the metric table plus one line per regressed case with expected and actual labels. Reviewers stopped opening the log once that comment existed.

## What moved

We enabled the gate in week 2 of a ten-week window on a six-prompt customer-message classification service. The suite grew from 84 to 120 cases over the period as production misclassifications were turned into eval cases.

![Combined chart over ten weeks: red bars show prompt regressions found in production per week falling from 9 before the gate to 0 by week 10, blue bars show PRs blocked by the eval gate at 1 to 4 per week after it was turned on in week 2, and a green line on the right axis shows the exact-match score on main rising from 0.91 to 0.96](/assets/img/posts/ai/ai-sdlc-llm-eval-harness-regressions-by-week.webp)

- **Production prompt regressions** (a misclassification traced back to a prompt change) went from 7-9 per week to 0 in the last week. The remaining ones in weeks 3-6 were cases the suite did not yet contain; each became a new case.
- **PRs blocked by the gate:** 20 over eight weeks, out of 61 prompt PRs. 14 were fixed in the same PR within a day; 6 were abandoned because the "improvement" did not survive the diff.
- **Exact match on `main`** rose from 0.91 to 0.96, partly from better prompts and partly because adding failing production cases to the suite forced the prompt to handle them.
- **Cost:** about $0.20 per live run, $31 over the whole window. Cheaper than any one of the week-0 incidents.

## Reusing this in your pipeline

1. Start from an existing golden-case suite; if you do not have one, the [earlier post]({% post_url AI/2026-10-02-testing-llm-prompts-dotnet %}) shows how to build it from production logs.
2. Make the harness emit a JSON report and an exit code. Everything else, including the PR comment, hangs off those two.
3. Set absolute floors from your current `main` score minus a small margin, and a regression budget of about 2-3% of the suite. Tighten both as the suite grows.
4. Pin the model deployment, set temperature to 0, and run the recorded mode first so a broken schema never costs a live run.
5. Refresh the baseline on every merge to `main`, not nightly; otherwise two prompt PRs merged on the same day diff against a stale baseline.

The eval harness is the same code that produced the nightly numbers; the only new idea is running it where the decision gets made, on the PR, with a diff and a budget. For the broader set of merge gates on AI-authored changes, see [gating coding-agent PRs before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}); for the token-counting side of keeping the suite within context limits, the [Token Counter](https://tools.lamplitlabs.com/token-counter) tool in Lamplit Tools is what we use before adding a long-document case.
