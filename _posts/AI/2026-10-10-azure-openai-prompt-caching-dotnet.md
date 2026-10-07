---
layout: post
title: "Azure OpenAI Prompt Caching in .NET: Cut Latency and Input Cost by Ordering Your Prompt Right"
date: 2026-10-10 00:00:00 +0200
categories: ai
tags: ai azure-openai dotnet csharp performance cost gpt-4o prompt-caching
author: manishtiwari25
description: "How Azure OpenAI prompt caching works, how to structure prompts so the static prefix hits the cache, and measured latency and cost savings from .NET."
image:
  path: /assets/img/headers/ai/azure-openai-prompt-caching-dotnet.webp
  alt: "Header card comparing time-to-first-token without prompt caching (1820 ms) and with prompt caching (640 ms) for Azure OpenAI in .NET"
---

If your Azure OpenAI requests carry a long system prompt, a pile of tool schemas or a few-shot block, you are sending the same few thousand tokens on every call and paying full price for them each time. Prompt caching fixes that: when the first part of a request matches a recently seen prefix, the service reuses its work, bills those input tokens at a discount and usually answers faster. The feature is on by default for the `gpt-4o`, `gpt-4o-mini`, `o1` and newer deployments, so the only thing you need to do is stop defeating it.

This post shows what the cache actually keys on, how to lay out a prompt in C# so the cache hits, how to read the hit count from the response, and what I measured when I did it.

{% include feed-ads.html %}

## How the cache decides

The rules are simple but unforgiving:

- Caching applies to the **prefix** of the request. Everything up to the first byte that differs from a previous request can be served from cache; everything after it cannot.
- Prefixes shorter than **1 024 tokens** are never cached. After that, matches are counted in 128-token steps.
- Cached entries live for roughly 5–10 minutes of inactivity and are evicted after about an hour regardless. A steady stream of traffic keeps them warm.
- The cache is per deployment and per subscription; nothing is shared between tenants.

The practical consequence: put everything that never changes **first**, in a stable order, and everything that changes per request **last**. A timestamp, a user id or a request id anywhere near the top of the system prompt breaks the prefix on every call and you get a 0 % hit rate while believing you have caching.

## Structuring the request in C#

I use the `Azure.AI.OpenAI` client, same as in the [function-calling post]({% post_url AI/2026-09-30-azure-openai-function-calling-dotnet %}). The messages are built in a fixed order and the tool definitions are registered once as a static field so their serialisation is byte-identical between requests:

```csharp
using Azure;
using Azure.AI.OpenAI;
using OpenAI.Chat;

static class Prompts
{
    // Long, stable, and first. Nothing request-specific goes in here.
    public static readonly string System = File.ReadAllText("prompts/support-agent.system.md");
}

static class Tools
{
    public static readonly IReadOnlyList<ChatTool> All =
    [
        ChatTool.CreateFunctionTool("lookup_order", "Look up an order by id",
            BinaryData.FromString("""{"type":"object","properties":{"orderId":{"type":"string"}},"required":["orderId"]}""")),
        ChatTool.CreateFunctionTool("open_ticket", "Open a support ticket",
            BinaryData.FromString("""{"type":"object","properties":{"summary":{"type":"string"}},"required":["summary"]}""")),
    ];
}

ChatCompletion Ask(ChatClient client, string tenantContext, string userText)
{
    var messages = new List<ChatMessage>
    {
        new SystemChatMessage(Prompts.System),        // static, cached
        new SystemChatMessage(tenantContext),         // changes per tenant, still cached per tenant
        new UserChatMessage(userText),                // changes per request
    };

    var options = new ChatCompletionOptions();
    foreach (var tool in Tools.All) options.Tools.Add(tool);

    return client.CompleteChat(messages, options);
}
```

Two details matter here. First, the tool list is appended in a fixed order; a `Dictionary<string, ChatTool>` iterated in insertion order usually behaves, but a `HashSet` does not, and a reordered schema is a cache miss. Second, the tenant context sits *after* the big system prompt, so a request from tenant B still hits the cache for the whole shared prefix and only misses on its own short block.

## Reading the hit count

The response tells you exactly how many prompt tokens came from cache. In the current SDK it is on `Usage.InputTokenDetails.CachedTokenCount`; if you are on the raw REST API it is `usage.prompt_tokens_details.cached_tokens`:

```csharp
var completion = Ask(client, tenantContext, userText);
var usage = completion.Usage;

Console.WriteLine($"input={usage.InputTokenCount} cached={usage.InputTokenDetails?.CachedTokenCount ?? 0} output={usage.OutputTokenCount}");
```

Emit that as a metric. I added it to the OpenTelemetry pipeline from the [LLM observability post]({% post_url AI/2026-10-04-enterprise-llm-observability-opentelemetry-dotnet %}) as a histogram `gen_ai.usage.cached_input_tokens`, and a hit ratio dashboard tile tells you within a minute whether someone has just shipped a change that breaks the prefix.

## What I measured

I ran 200 requests through a .NET 8 console app against a `gpt-4o` deployment in East US 2 with a 3 100-token prefix (system prompt plus six tool schemas) and a ~120-token user turn. Two variants: one where a `// generated at {timestamp}` line sat at the top of the system prompt, one with the layout above.

![Table of results for 200 Azure OpenAI gpt-4o requests: cache hit ratio 0% vs 91%, p50 time-to-first-token 1740 ms vs 610 ms, p95 2960 ms vs 1120 ms, billed input tokens per request 3220 vs 1810 equivalent, input cost per 1000 requests $8.05 vs $4.53](/assets/img/posts/ai/azure-openai-prompt-caching-results.webp)

The latency gain is the part people underestimate. The service skips re-processing the cached prefix, so time-to-first-token dropped by roughly 65 % at p50 and p95. The cost column uses the 50 % discount Azure applies to cached input tokens; your exact numbers depend on the model and region price sheet, but the ratio holds.

The 9 % of misses in the cached run were the first request after each idle gap longer than a few minutes, plus the first request for each new tenant context.

## Things that silently break caching

- **Dynamic content at the top.** Timestamps, request ids, "today's date is", the user's name. Move them to the last system message or into the user turn.
- **Non-deterministic serialisation.** Tool schemas built from reflection with unordered property enumeration, or JSON produced with different `JsonSerializerOptions` on different code paths.
- **Trimming the conversation from the front.** If you drop the oldest messages when the history grows, the prefix changes every turn. Keep the system block fixed and summarise the *middle* instead.
- **A/B prompt experiments with low traffic.** Each variant has its own cache; if neither sees a request every few minutes, both run cold.
- **Short prompts.** Under 1 024 tokens nothing is cached. That is fine; the savings would be small anyway.

## When it is not worth chasing

If your prompt is under about 1 500 tokens, or traffic is a few requests per hour, the cache will rarely be warm and the layout work buys little. Spend the effort on [token counting and budgets]({% post_url AI/2026-09-29-azure-openai-token-counting-cost-dotnet %}) first. For high-volume, long-prefix workloads such as RAG with a fixed instruction block or agents with many tools, it is the cheapest latency and cost win available: no code changes to the model call, just discipline about ordering.

## Summary

1. Static content first, in a fixed order; per-request content last.
2. Make tool-schema serialisation deterministic and register tools once.
3. Log `CachedTokenCount` and watch the hit ratio; a drop to zero means someone broke the prefix.
4. Expect roughly half the input cost and a large time-to-first-token reduction on warm traffic.

## Related posts

- Enterprise AI: Semantic Caching for Azure OpenAI with Azure API Management (coming soon)
- [Counting Tokens and Controlling Azure OpenAI Cost in .NET](/posts/azure-openai-token-counting-cost-dotnet/)
- [Streaming Azure OpenAI Responses in .NET: First Token in Under a Second](/posts/streaming-azure-openai-responses-dotnet/)
