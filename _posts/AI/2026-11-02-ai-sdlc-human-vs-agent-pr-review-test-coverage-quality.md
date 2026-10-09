---
layout: post
title: "AI SDLC: Human vs Agent PR Review - Measuring Test Coverage Quality With Defect Escape Rate and Mutation Score"
date: 2026-11-02 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp code-review testing mutation-testing devops enterprise metrics
author: manishtiwari25
description: "412 .NET PRs reviewed by humans, an agent, or both: defect escape rate, mutation score of agent-written tests and turnaround, with the numbers that decided it."
image:
  path: /assets/img/headers/ai/ai-sdlc-human-vs-agent-pr-review-test-quality.webp
  alt: "Header card comparing human and agent PR review over 412 PRs: defect escape rate 4.1% down to 2.7%, mutation score 64% up to 78%, review turnaround 19.6 hours down to 7.3 hours, and a 6.8% escape rate for agent-only review"
---

The [code-review agent metrics post]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %}) answered "is the bot's output worth reading?" with precision and ignored-comment rate. The [mutation testing post]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %}) showed that LLM-written tests can hit 90% line coverage while asserting almost nothing. This post joins the two: once an agent is both *writing* tests and *reviewing* pull requests, who should sign off on the tests, and how do you know the answer is not just a feeling?

We ran a one-quarter comparison across twelve .NET 8 services with three review arms - human only, agent only, agent plus human - and measured each arm on the same three numbers: **defect escape rate**, **mutation score of the tests changed in the PR**, and **review turnaround**. The short version: the agent alone shipped more escaped defects than humans alone, but agent-then-human cut escapes by roughly a third while more than halving turnaround.

{% include article-ads.html %}

## What we measured and how

A PR counted if it touched at least one test file. That gave 412 PRs over the quarter. Arms were assigned per repository and rotated monthly, so every service spent one month in each arm and the same nine engineers reviewed across all of them.

- **Defect escape rate**: a production incident or bug ticket opened within 30 days of merge whose fix commit touched code changed in the PR. Counted per 100 PRs.
- **Mutation score**: [Stryker.NET](https://stryker-mutator.io/docs/stryker-net/introduction/) run only against the source files covered by the test files changed in the PR, using `--mutate` globs built from the diff. Line coverage was deliberately *not* a metric - that was the lesson of the mutation testing post.
- **Turnaround**: median hours from first review event to merge.
- **Comments acted on**: a review comment counted as acted on if a later commit on the PR changed a line within 5 lines of the comment anchor.

The agent in the "agent" arms is the same GPT-4o review bot from the metrics post, with one addition: it is given the Stryker report for the PR and asked specifically about surviving mutants in changed tests.

![Table comparing three PR review arms over 412 PRs: human only had 6 escaped defects (4.1%), 64% median mutation score, 11 PRs with assertion-free tests and 19.6 hour turnaround; agent only had 8 escapes (6.8%), 71% mutation score, 3 assertion-free PRs and 1.2 hour turnaround; agent plus human had 4 escapes (2.7%), 78% mutation score, 1 assertion-free PR and 7.3 hour turnaround, with 17 human reviewer minutes per PR instead of 41](/assets/img/posts/ai/ai-sdlc-human-vs-agent-review-arms-table.webp){: width="1400" height="760" }
_Arm-by-arm results. Green cells are the best value in the row; red is the number that got agent-only review switched off after month two's data was in._

## Reading the table

**Agent-only review is fast and wrong in the expensive direction.** 1.2 hours to merge is seductive, and the agent was good at the mechanical stuff - only 3 PRs got through with assertion-free tests, versus 11 under humans. But 6.8 escapes per 100 PRs is worse than the human baseline. Looking at the eight escapes, six were cases where the test *did* assert, the mutants *were* killed, and the behaviour under test was simply not the behaviour the ticket asked for. The agent checks the test against the code; a human checks the test against the intent.

**Humans alone are slow and miss the boring things.** 19.6 hours median turnaround, and 7.5% of merged PRs carried a test with no assertion at all - usually a `[Fact]` that calls a method and ends. Nobody enjoys reviewing test files, and it shows.

**Agent then human is the arm that moved every metric.** The agent posts first (it sees the Stryker surviving-mutant list and the assertion-free detector), the author fixes what it flags, and the human reviews a PR that is already mechanically clean. Human time per PR fell from 41 to 17 minutes, turnaround from 19.6 to 7.3 hours, and escapes from 4.1 to 2.7 per 100 PRs. Across the quarter that is roughly 2 fewer production defects per 100 PRs from a bot that costs 14 cents each.

![Grouped bar chart of mutation score bands for tests changed in a PR, by review arm: under human-only review 14% of PRs scored below 50% and 8% scored 90% or more; under agent-only 7% and 10%; under agent plus human 3% scored below 50% and 18% scored 90% or more](/assets/img/posts/ai/ai-sdlc-human-vs-agent-mutation-score-bands.webp){: width="1400" height="700" }
_The distribution matters more than the median. The agent + human arm nearly eliminated the sub-50% tail, which is where the escaped defects lived: 7 of the 18 escapes across all arms came from PRs whose changed tests scored under 50%._

## Wiring the mutation score into the review

The piece of plumbing that made this work is scoping Stryker to the diff, so a PR gets a mutation report in about four minutes rather than the forty it takes for the whole solution.

```bash
# Files changed in this PR, test projects only
changed_tests=$(git diff --name-only origin/main...HEAD | grep -E 'Tests?/.*\.cs$')

# Map test files to the source files they cover via the naming convention
# (OrderServiceTests.cs -> OrderService.cs); fall back to the whole project
mutate_globs=""
for t in $changed_tests; do
  src=$(basename "$t" | sed -E 's/Tests?\.cs$/.cs/')
  path=$(git ls-files "src/**/$src" | head -n1)
  [ -n "$path" ] && mutate_globs="$mutate_globs --mutate \"$path\""
done

dotnet stryker --reporter json --reporter markdown \
  --threshold-break 0 $mutate_globs
```

The JSON report is what the agent receives as context, trimmed to surviving mutants only:

```csharp
var report = JsonDocument.Parse(File.ReadAllText("StrykerOutput/latest/reports/mutation-report.json"));
var survivors = report.RootElement.GetProperty("files")
    .EnumerateObject()
    .SelectMany(f => f.Value.GetProperty("mutants").EnumerateArray()
        .Where(m => m.GetProperty("status").GetString() == "Survived")
        .Select(m => new
        {
            File = f.Name,
            Line = m.GetProperty("location").GetProperty("start").GetProperty("line").GetInt32(),
            Mutator = m.GetProperty("mutatorName").GetString(),
            Replacement = m.GetProperty("replacement").GetString()
        }))
    .ToList();
```

The prompt then asks for exactly one thing per surviving mutant: *"Which existing or new assertion would kill this mutant? If none is reasonable, say why."* That phrasing is what cut the agent's comment count from the 6 per PR in the agent-only arm to a more tolerable 4 in the combined arm, and raised acted-on comments from 38% to 63%.

The assertion-free detector is a Roslyn analyzer rather than the LLM, for the same reason as always: deterministic checks should be deterministic.

```csharp
[DiagnosticAnalyzer(LanguageNames.CSharp)]
public sealed class TestWithoutAssertionAnalyzer : DiagnosticAnalyzer
{
    private static readonly DiagnosticDescriptor Rule = new(
        "TQ001", "Test has no assertion",
        "Test method '{0}' contains no Assert, Should or Verify call",
        "TestQuality", DiagnosticSeverity.Warning, isEnabledByDefault: true);

    public override ImmutableArray<DiagnosticDescriptor> SupportedDiagnostics => [Rule];

    public override void Initialize(AnalysisContext context)
    {
        context.EnableConcurrentExecution();
        context.ConfigureGeneratedCodeAnalysis(GeneratedCodeAnalysisFlags.None);
        context.RegisterSyntaxNodeAction(Analyze, SyntaxKind.MethodDeclaration);
    }

    private static void Analyze(SyntaxNodeAnalysisContext ctx)
    {
        var method = (MethodDeclarationSyntax)ctx.Node;
        if (!method.AttributeLists.SelectMany(a => a.Attributes)
                .Any(a => a.Name.ToString() is "Fact" or "Theory" or "Test"))
            return;

        var hasAssert = method.DescendantNodes().OfType<InvocationExpressionSyntax>()
            .Any(i => i.ToString() is var s &&
                      (s.StartsWith("Assert.") || s.Contains(".Should(") || s.Contains(".Verify(")));

        if (!hasAssert)
            ctx.ReportDiagnostic(Diagnostic.Create(Rule, method.Identifier.GetLocation(), method.Identifier.Text));
    }
}
```

## What this does not prove

- **Twelve services, one quarter, 18 escapes in total.** The direction is clear; the second decimal place is not. We would not bet a budget on 2.7% versus 2.4%.
- **Rotation, not randomisation.** Arms rotated monthly per repository, which controls for team but not for what shipped that month. A release-heavy month inflates escapes for whichever arm it lands in.
- **30-day escape window.** Defects that surface later are not counted, and for data migration code they often do.
- **The agent saw the Stryker report; humans had to open it.** Some of the agent arm's mutation-score advantage is simply that the information was in front of it. Putting surviving mutants as a PR comment for the human-only arm would have been a fairer test, and is what we do now.

## Takeaways

1. Measure agent-written tests with mutation score, not line coverage, and measure review arms with defect escape rate, not comment counts.
2. Agent-only review of tests is a false economy: fast, mechanically tidy, and worse than humans at catching tests that verify the wrong behaviour.
3. Agent first, human second, with the agent fed the surviving-mutant list, was the only arm that improved escapes, mutation score and turnaround together.
4. Keep the deterministic checks deterministic. An analyzer finds assertion-free tests in milliseconds; the LLM is for the question "what assertion would kill this mutant?"

## Related

- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %})
- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest]({% post_url AI/2026-10-12-llm-test-generation-mutation-testing-dotnet %})
- [AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines]({% post_url AI/2026-10-16-ai-sdlc-flaky-test-triage %})
- [AI SDLC: LLM-Assisted Dependency Upgrades for .NET - Major Version Bumps Without Losing the Weekend]({% post_url AI/2026-10-19-ai-sdlc-llm-assisted-dependency-upgrades-dotnet %})
- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %})
