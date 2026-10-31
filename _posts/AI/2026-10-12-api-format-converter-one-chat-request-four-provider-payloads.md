---
layout: post
title: "AI API Format Converter: One Chat Request, Four Provider Payloads"
date: 2026-10-12 13:00:00 +0200
categories: ai lamplit-tools
tags: ai enterprise-ai ai-sdlc tools llm openai claude gemini ollama
author: manishtiwari25
description: "How the Lamplit Labs AI API Format Converter rewrites a chat request between OpenAI, Anthropic, Gemini and Ollama, and what it drops."
image:
  path: /assets/img/headers/ai/api-format-converter-lamplit-tools.webp
  alt: "Lamplit Labs AI API Format Converter header showing an OpenAI chat request on the left converted into a Google Gemini contents and systemInstruction payload on the right"
---
Every team that has swapped LLM providers has written the same twenty lines of glue: pull the system message out of `messages` because Anthropic wants it as a top-level `system` string, rename `assistant` to `model` because Gemini insists, move `max_tokens` into `generationConfig.maxOutputTokens`, and then discover that Ollama calls the same thing `options.num_predict`. The [AI API Format Converter](https://tools.lamplitlabs.com/api-format) on the Lamplit Labs [tools site](https://tools.lamplitlabs.com/) does that translation in the browser so you can see the target payload before you write the adapter. Like the [Token Counter](/posts/token-counter-checking-prompt-size-and-context-window-fit/) and the [Prompt Template Editor](/posts/prompt-template-editor-and-prompt-diff-versioning-prompts-like-code/), nothing you paste leaves the page.

## What the page looks like

The tool opens with a standard OpenAI chat completion request as the input:

```json
{
  "model": "gpt-4o",
  "messages": [
    { "role": "system", "content": "You are a helpful assistant." },
    { "role": "user", "content": "What is the capital of France?" }
  ],
  "temperature": 0.7,
  "max_tokens": 1024
}
```

Above the editors is a bar with two tab rows, **From** and **To**, each offering `OpenAI`, `Anthropic`, `Google Gemini` and `Ollama`, and a swap button between them. The left pane is an editable JSON editor labelled with the source provider; the right pane is read-only, labelled with the target, with a copy button in its header. Conversion is live: every keystroke re-parses the input and re-renders the output, and a parse error or shape error appears as a red chip above the editors instead of a stale result.

![Screenshot of the Lamplit Labs AI API Format Converter with From set to OpenAI and To set to Anthropic, the sample OpenAI request in the left editor and the converted Anthropic payload on the right with the system message hoisted to a top-level system field](/assets/img/posts/ai/api-format-converter-openai-to-anthropic.webp){: width="1400" height="900" }

With `From = OpenAI` and `To = Anthropic`, the sample above becomes:

```json
{
  "model": "claude-3.5-sonnet-20241022",
  "max_tokens": 1024,
  "temperature": 0.7,
  "system": "You are a helpful assistant.",
  "messages": [
    { "role": "user", "content": "What is the capital of France?" }
  ]
}
```

The system message has moved out of the array, `max_tokens` has become required-and-first (Anthropic rejects a request without it), and the model name has been replaced because `gpt-4o` is meaningless to the Anthropic endpoint.

## How the conversion works

The converter does not keep a four-by-four matrix of provider pairs. Each source format is parsed into one small canonical shape, and each target format is rendered from that shape:

```text
messages:    [{ role, content: string }]
model:       string
temperature: number   (default 0.7)
maxTokens:   number   (default 1024)
```

That design is why the **Swap** button is cheap: it copies the current output into the input editor and flips the two tabs, so you can round-trip a request and see what survives. The per-provider rules are the part worth knowing when you read the output.

**Parsing in**

- *OpenAI* reads `messages`, `model`, `temperature`, `max_tokens`.
- *Anthropic* reads the same, then prepends the top-level `system` string as a `system` message so it is not lost.
- *Google Gemini* requires a `contents` array (anything else is an error chip); each item's `parts` are flattened to text, `role: "model"` is mapped back to `assistant`, `systemInstruction.parts` becomes a leading system message, and `generationConfig.temperature` / `maxOutputTokens` fill the two numbers.
- *Ollama* reads `messages` and `model`, and takes `temperature` and `num_predict` from `options`.

**Rendering out**

- *OpenAI* emits `model`, `messages`, `temperature`, `max_tokens`.
- *Anthropic* hoists the first system message into `system`, keeps the model only if its name contains `claude` (otherwise `claude-3.5-sonnet-20241022`), and forces every non-assistant role to `user`.
- *Google Gemini* emits `systemInstruction.parts[].text`, a `contents` array with `assistant` renamed to `model` and every content wrapped in `parts: [{ text }]`, and a `generationConfig` block. Note that it emits no `model` field at all, because Gemini takes the model from the URL.
- *Ollama* keeps the model only if its name contains `llama` or `mistral` (otherwise `llama3.1`), adds `stream: false`, and nests `temperature` and `num_predict` under `options`.

## What it deliberately drops

Because the canonical shape is `role + text`, the converter is lossy by design, and the losses are the exact places where provider adapters bite in production:

1. **Multimodal and structured content is flattened.** An OpenAI `content` array of `{ type: "text" }` and `{ type: "image_url" }` parts becomes the text parts joined with newlines; the image reference is gone. Gemini `inlineData` parts are serialised as JSON strings rather than carried across.
2. **Tool and function calling is not translated.** `tools`, `tool_choice`, `tool_calls` and Anthropic `tool_use` blocks are ignored; if you need that mapping, build the schema once with the [Function Call Schema Builder](https://tools.lamplitlabs.com/function-schema) and wire it per provider.
3. **Sampling parameters other than temperature and max tokens are dropped.** `top_p`, `stop`, `seed`, `response_format`, `presence_penalty` and friends do not appear in the output.
4. **Model names are substituted, not mapped.** The tool does not know that `gpt-4o` is "roughly" any particular Claude or Gemini model; it falls back to a sensible default and leaves the choice to you.

None of these are bugs to work around; they are the boundary of what a shape converter can do honestly. The value is that the output is a correct *minimal* request for the target API, which is the thing you want to diff your adapter's output against.

## Where it fits in an AI SDLC

Three uses have come up repeatedly:

- **Provider evaluation.** When comparing answer quality across vendors, paste the request you already send to one provider and copy the converted payload into `curl` for the other. The comparison is then about the model, not about whether you remembered Gemini's `parts` wrapper.
- **Adapter tests.** Convert a handful of representative requests and commit the outputs as fixtures. Your own adapter code should produce the same shape, and when it does not, the diff tells you which rule you missed.
- **Local fallback.** Teams running Ollama as an offline or cost-control fallback can see at a glance that the Ollama body is close to OpenAI's except for `options` and `stream`, which usually settles the "do we need a second client library" question quickly.

If you use the [AI Pricing Calculator](/posts/ai-pricing-calculator-estimating-llm-api-costs-before-you-ship/) to decide *which* provider to try next, this is the tool that gets the first request onto the wire without reading four sets of docs.
