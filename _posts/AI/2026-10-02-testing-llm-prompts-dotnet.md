---
layout: post
title: "Testing LLM Prompts in .NET: Regression Tests for Azure OpenAI Outputs"
date: 2026-10-02 09:00:00 -0500
categories: ai
tags: ai azure openai dotnet csharp testing xunit prompts
author: manishtiwari25
description: "Build an xUnit regression suite for Azure OpenAI prompts in .NET: golden cases, structural asserts, a recorded-response fake for CI and a nightly live run."
image:
  path: /assets/img/headers/ai/testing-llm-prompts-dotnet.webp
  alt: "Four-step diagram of an LLM prompt regression suite: golden test cases, a recorded-response fake for CI, structural assertions on the JSON output, and a nightly live run against Azure OpenAI with a score threshold"
---

A prompt is code. It ships to production, a colleague edits one sentence of it to fix a customer complaint, and three unrelated behaviours quietly change. Nobody notices until the next complaint. If a C# method behaved like that, you would write a test for it. Prompts deserve the same treatment, but the usual unit-test reflexes do not fit: the output is non-deterministic, every call costs money, and "correct" is often a judgement call.

This post shows a practical setup I use for Azure OpenAI prompts in .NET: a small set of **golden cases**, **structural assertions** that never flake, a **recorded-response fake** so CI stays free and fast, and a **nightly live run** that scores the real model and fails only when quality drops below a threshold.

![LLM prompt regression suite: golden cases, recorded fake, structural asserts, nightly live run](/assets/img/headers/ai/testing-llm-prompts-dotnet.webp)

{% include feed-ads.html %}

## What goes wrong without tests

Three failure modes show up again and again:

- **Format drift**: you ask for JSON, the prompt is edited, and the model starts wrapping the JSON in a Markdown fence. `JsonSerializer.Deserialize` throws in production.
- **Scope creep**: a classification prompt with five allowed labels starts returning a sixth one ("Other / Unsure") after someone adds "be helpful" to the system message.
- **Silent regressions on edge cases**: empty input, non-English input, or a 10,000-token document now produce a worse answer, and the happy path still looks fine in manual testing.

None of these are caught by eyeballing one response in the Azure AI Foundry playground.

## Step 1: Make the prompt a testable unit

Put the prompt and the call behind one small class so the tests target a real seam instead of string literals scattered across the codebase.

```csharp
public sealed record TicketClassification(string Category, string Priority, string Summary);

public sealed class TicketClassifier(ChatClient chat)
{
    public const string SystemPrompt = """
        You classify customer support tickets.
        Reply with JSON only: {"category": one of [billing, bug, feature, account, other],
        "priority": one of [low, medium, high], "summary": one sentence}.
        """;

    public async Task<TicketClassification> ClassifyAsync(string ticket, CancellationToken ct = default)
    {
        var completion = await chat.CompleteChatAsync(
            [new SystemChatMessage(SystemPrompt), new UserChatMessage(ticket)],
            new ChatCompletionOptions
            {
                Temperature = 0,
                ResponseFormat = ChatResponseFormat.CreateJsonObjectFormat()
            },
            ct);

        var json = completion.Value.Content[0].Text;
        return JsonSerializer.Deserialize<TicketClassification>(json, JsonOptions)!;
    }

    private static readonly JsonSerializerOptions JsonOptions = new(JsonSerializerDefaults.Web);
}
```

`Temperature = 0` and the JSON response format remove most of the randomness. They do not remove all of it, which is why the next steps exist.

## Step 2: Golden cases as data, not as test methods

Keep the cases in a JSON file so product people can add one without touching C#.

```json
[
  {
    "name": "refund-request",
    "input": "I was charged twice for my subscription this month, please refund one.",
    "expect": { "category": "billing", "priority": "high" }
  },
  {
    "name": "empty-input",
    "input": "",
    "expect": { "category": "other" }
  },
  {
    "name": "hindi-bug-report",
    "input": "ऐप लॉगिन के बाद क्रैश हो जाता है",
    "expect": { "category": "bug" }
  }
]
```

Each case asserts only what matters. The summary sentence is never compared exactly; the model will phrase it differently every day and that is fine.

## Step 3: Structural assertions that never flake

These run on every CI build against a fake client and check the things that *must* hold regardless of the model's mood.

```csharp
public sealed class TicketClassifierTests
{
    public static IEnumerable<object[]> Cases() =>
        GoldenCases.Load("golden/tickets.json").Select(c => new object[] { c });

    [Theory]
    [MemberData(nameof(Cases))]
    public async Task Output_is_valid_and_within_allowed_values(GoldenCase c)
    {
        var client = RecordedChatClient.For(c.Name);   // replays recorded JSON
        var sut = new TicketClassifier(client);

        var result = await sut.ClassifyAsync(c.Input);

        Assert.Contains(result.Category, new[] { "billing", "bug", "feature", "account", "other" });
        Assert.Contains(result.Priority, new[] { "low", "medium", "high" });
        Assert.False(string.IsNullOrWhiteSpace(result.Summary));
        Assert.True(result.Summary.Length < 200);

        if (c.Expect.Category is { } cat) Assert.Equal(cat, result.Category);
        if (c.Expect.Priority is { } pri) Assert.Equal(pri, result.Priority);
    }
}
```

The `RecordedChatClient` is a `ChatClient` subclass (or a `DelegatingHandler` under the `AzureOpenAIClient`'s `HttpClient`) that serves the response captured during the last nightly run. CI is deterministic, costs nothing, and still proves that the parsing, allowed values and prompt wiring have not broken.

## Step 4: Recording responses

Record once, commit the fixtures, re-record when you intentionally change the prompt.

```csharp
public sealed class RecordingHandler(string folder) : DelegatingHandler
{
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage req, CancellationToken ct)
    {
        var name = req.Headers.TryGetValues("x-test-case", out var v) ? v.First() : "default";
        var path = Path.Combine(folder, $"{name}.json");

        if (File.Exists(path) && Environment.GetEnvironmentVariable("LLM_RECORD") != "1")
        {
            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(await File.ReadAllTextAsync(path, ct), Encoding.UTF8, "application/json")
            };
        }

        var response = await base.SendAsync(req, ct);
        await File.WriteAllTextAsync(path, await response.Content.ReadAsStringAsync(ct), ct);
        return response;
    }
}
```

Run `LLM_RECORD=1 dotnet test` locally after a prompt change, review the fixture diff in the pull request, and reviewers can see exactly how the outputs moved. That diff is the single most useful artefact of this whole setup.

## Step 5: The nightly live run with a score threshold

Recorded tests cannot tell you the model changed underneath you, or that a new deployment version answers differently. For that, run the same golden cases against the real endpoint once a night and compute a pass rate.

```csharp
[Fact]
[Trait("Category", "Live")]
public async Task Golden_cases_pass_rate_is_above_threshold()
{
    var client = new AzureOpenAIClient(new Uri(Env("AOAI_ENDPOINT")), new DefaultAzureCredential())
        .GetChatClient(Env("AOAI_DEPLOYMENT"));
    var sut = new TicketClassifier(client);
    var cases = GoldenCases.Load("golden/tickets.json").ToList();

    var passed = 0;
    foreach (var c in cases)
    {
        var r = await sut.ClassifyAsync(c.Input);
        var ok = (c.Expect.Category is null || c.Expect.Category == r.Category)
              && (c.Expect.Priority is null || c.Expect.Priority == r.Priority);
        if (ok) passed++; else _output.WriteLine($"FAIL {c.Name}: got {r.Category}/{r.Priority}");
    }

    var rate = (double)passed / cases.Count;
    Assert.True(rate >= 0.95, $"Pass rate {rate:P0} is below 95%");
}
```

Filter it out of the normal build with `dotnet test --filter "Category!=Live"` and run it in a scheduled pipeline with `--filter "Category=Live"`. A threshold instead of 100% stops a single borderline case from waking anyone up, while a real regression (format drift breaks every case) fails loudly.

## Tips that save time

- **Pin the model version** in the deployment (`gpt-4o-2024-08-06`, not `gpt-4o`) so a nightly failure means *you* changed something, not Microsoft.
- **Test the prompt diff, not the model.** When the live run fails after a prompt edit, re-record, read the fixture diff, and decide. Most "regressions" are actually the prompt now doing what was asked.
- **Keep golden cases small.** Twenty to fifty cases catch most problems; hundreds make the nightly run slow and expensive and nobody maintains them.
- **Budget the live run.** Fifty short cases on a GPT-4o deployment cost a few cents per night. Add `MaxOutputTokenCount` so a runaway summary cannot blow that up.
- **Log `custom_id`-style case names in telemetry** so a production failure can be turned into a new golden case in minutes.

## Summary

Treat prompts like code: isolate them behind a class, pin them to golden cases stored as data, assert structure on every build with recorded responses, and let a nightly live run with a pass-rate threshold tell you when the real model drifts. The fixture diff in each pull request makes prompt changes reviewable, which is the part teams miss most.

If you are building on Azure OpenAI from .NET, the earlier posts on [structured outputs](/posts/structured-outputs-azure-openai-dotnet/) and [handling 429 rate limits](/posts/azure-openai-429-rate-limit-retry-dotnet/) pair well with this one.
