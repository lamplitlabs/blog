---
layout: post
title: "LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest"
date: 2026-10-12 00:00:00 +0200
categories: ai
tags: ai sdlc dotnet csharp testing xunit copilot mutation-testing enterprise
author: manishtiwari25
description: "LLM-generated xUnit tests hit 94% coverage but killed only 41% of mutants. A review loop with Stryker.NET and five prompt rules fixed that."
image:
  path: /assets/img/headers/ai/llm-test-generation-mutation-testing-dotnet.webp
  alt: "Bar chart comparing 94% line coverage against a 41% mutation score for raw LLM-generated tests and 83% after a review loop"
---

Asking an LLM to "write unit tests for this class" is the single most popular AI-in-the-SDLC request I see in .NET teams, and the single most misleading. The tests compile, they pass, and coverage jumps. Then a real bug slips through a month later and nobody can explain how a method with 94% line coverage shipped a broken boundary check. This post walks through what happened when we ran **Stryker.NET** against 48 Copilot-generated xUnit tests for a pricing service, why the **mutation score** exposed what coverage hid, and the prompt rules and review loop that took the score from 41% to 83% without writing the tests by hand.

![Bar chart comparing 94% line coverage against a 41% mutation score for raw LLM-generated tests and 83% after a review loop](/assets/img/headers/ai/llm-test-generation-mutation-testing-dotnet.webp)

{% include feed-ads.html %}

## The setup

The class under test is a deliberately boring `PricingService`: compute a total from line items, apply a tier discount, apply an optional coupon, write an audit entry, return a `PriceResult`. About 90 lines, no I/O except an injected `IAuditLog`. We prompted GitHub Copilot Chat with the file open and the instruction *"Generate xUnit tests for PricingService with full coverage"*. It produced 48 `[Fact]` and `[Theory]` methods in under a minute. All green, 94% line coverage in Coverlet.

Then we ran mutation testing:

```bash
dotnet tool install -g dotnet-stryker
cd tests/Pricing.Tests
dotnet stryker --project Pricing.csproj --reporter html --reporter progress
```

Stryker rewrites the production code one small change at a time (`>` becomes `>=`, `*` becomes `/`, a method body becomes empty) and reruns the suite. A mutant that still passes every test **survived**, meaning no test noticed the behaviour change. Result for the generated suite: **120 mutants, 49 killed, 71 survived, mutation score 41%**.

## What the survivors had in common

![Stryker.NET report excerpt listing survived mutants in PricingService.cs: boundary, arithmetic, conditional and block-removal mutations that the generated tests never detected](/assets/img/posts/ai/llm-test-generation-stryker-survived-mutants.webp)

Reading the survived mutants side by side, four patterns covered almost all of them.

**1. Snapshot assertions instead of specification.** The model ran the code in its head and asserted whatever it thought the output was. A test like this kills nothing interesting:

```csharp
[Fact]
public void CalculateTotal_ReturnsExpected()
{
    var result = _sut.Calculate(_sampleOrder);
    Assert.NotNull(result);
    Assert.True(result.Total > 0);
}
```

`total * 0.9` mutated to `total / 0.9` still returns a positive, non-null result. The test documents that the method runs, not what it computes.

**2. No boundary values.** The discount applies when `total > 1000`. Copilot generated cases for 500 and 5000, never for 1000 or 1000.01. The `>` to `>=` mutant survived for exactly that reason, and this is the class of bug that actually ships.

**3. Side effects unverified.** `audit.Log(...)` was replaced with an empty block and every test still passed. The mock `IAuditLog` was injected but no test ever called `Verify` on it. Generated tests are very good at satisfying constructors and very bad at asserting on collaborators.

**4. Duplicate tests with different names.** Eleven of the 48 tests were the same scenario with a renamed method. They inflate the count and coverage, and they cost CI time while adding zero mutant kills.

## The review loop that fixed it

We did not hand-write the tests. We changed the prompt, fed the Stryker output back, and reviewed the diff. Three iterations took about forty minutes.

### Prompt rules that moved the score

1. **"For every comparison operator in the class, write a Theory with the value on, just below and just above the boundary."** This alone killed most Equality mutants.
2. **"Assert exact expected values computed from the business rule in the test, not from running the code. Show the arithmetic in a comment."** Forces specification over snapshot. Review becomes: is the comment right?
3. **"For every injected dependency, add at least one test that verifies it was called with the expected arguments, and one that verifies it was not called when it should not be."** Kills Block-removal mutants on side effects.
4. **"Do not generate two tests with the same inputs and assertions. Prefer `[Theory]` with `[InlineData]` over repeated `[Fact]`s."**
5. **"Here is the list of survived mutants from Stryker. Write one test per mutant that would fail if that mutation were applied."** This is the feedback loop; paste the report's survivors table directly.

A boundary test after rule 1 and 2 looks like what a careful human would have written:

```csharp
[Theory]
// Rule: Gold tier gets 10% off when subtotal is strictly greater than 1000.
[InlineData(999.99, 999.99)]   // below: no discount
[InlineData(1000.00, 1000.00)] // on the boundary: no discount (strict >)
[InlineData(1000.01, 900.009)] // above: 10% off -> 1000.01 * 0.9
public void GoldDiscount_AppliesOnlyAbove1000(decimal subtotal, decimal expected)
{
    var order = OrderWith(Tier.Gold, subtotal);

    var result = _sut.Calculate(order);

    Assert.Equal(expected, result.Total, precision: 3);
}

[Fact]
public void Calculate_WritesOneAuditEntryWithOrderId()
{
    var order = OrderWith(Tier.Silver, 100m);

    _sut.Calculate(order);

    _audit.Verify(a => a.Log(It.Is<AuditEntry>(e => e.OrderId == order.Id)), Times.Once);
}
```

### What review rejected

Of the regenerated tests, we threw out 11. Most were rule 2 violations where the "expected" comment was simply wrong: the model had computed `1000.01 * 0.9` as `900.01`. That is the whole point of the comment: a human can check a line of arithmetic in seconds, but cannot check a bare `Assert.Equal(900.01m, result.Total)` without opening the production code. Two tests tried to assert on a private field through reflection, which we reject regardless of who wrote it.

Final numbers: **120 mutants, 100 killed, 20 survived, mutation score 83%.** Line coverage was unchanged at 94%, which is the headline: coverage could not tell the two suites apart.

## Putting the gate in CI

Mutation testing is slower than unit testing (minutes, not seconds), so run it as its own job and gate on the score rather than on coverage:

```json
// stryker-config.json in the test project
{
  "stryker-config": {
    "project": "Pricing.csproj",
    "reporters": ["html", "json", "progress"],
    "thresholds": { "high": 85, "low": 70, "break": 70 },
    "since": { "enabled": true, "target": "main" }
  }
}
```

`"break": 70` fails the job when the score drops below 70%; `since` limits mutation to files changed against `main`, which keeps the job to a few minutes on a pull request. For a nightly job, drop `since` and mutate everything.

```yaml
# .github/workflows/mutation.yml (excerpt)
- name: Mutation test changed files
  run: |
    dotnet tool restore
    dotnet stryker --config-file tests/Pricing.Tests/stryker-config.json
```

Publish the HTML report as a build artefact. The survived-mutants table is the input to the next round of generation, so make it easy for the developer to copy.

## Where this sits in the AI SDLC

In the [phase-by-phase AI SDLC post]({% post_url AI/2026-10-03-ai-sdlc-dotnet-teams %}) the rule was *AI drafts, humans decide, something deterministic checks*. Test generation is the phase where the deterministic check is weakest, because "the tests pass" is a check on the tests' consistency with the code, not on their value. Mutation testing supplies the missing check: it measures whether the tests would notice if the code were wrong, which is the only thing a test is for.

The same principle extends to LLM-generated tests for prompts themselves, covered in [Testing LLM Prompts in .NET]({% post_url AI/2026-10-02-testing-llm-prompts-dotnet %}), and to the [code review agent metrics]({% post_url AI/2026-10-08-ai-sdlc-code-review-agent-metrics %}) where we measure the reviewer rather than trusting its confidence.

## Takeaways

- Coverage measures which lines ran; mutation score measures whether tests would catch a change. Generated tests inflate the first and often leave the second untouched.
- The four failure modes of LLM-generated tests are snapshot assertions, missing boundaries, unverified side effects and duplicates. Put a prompt rule against each.
- Feed the survived-mutants list back into the prompt; it is the best test-generation prompt you will ever write because it names exactly what is missing.
- Review the expected-value comments, not the assertions. A wrong comment is cheap to spot; a wrong magic number is not.
- Gate pull requests on Stryker's `break` threshold with `since` enabled, and run the full mutation set nightly.

## Related posts

- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It](/posts/ai-sdlc-code-review-agent-metrics/)
- [Testing LLM Prompts in .NET: Regression Tests for Azure OpenAI Outputs](/posts/testing-llm-prompts-dotnet/)
- [AI SDLC: Where AI Actually Helps a .NET Team, Phase by Phase](/posts/ai-sdlc-dotnet-teams/)
