---
layout: post
title: "Enterprise AI: What JSON Costs in an LLM Prompt - ERP Records in Six Formats, Measured"
date: 2026-11-24 08:00:00 +0000
categories: ai enterprise-ai
tags: [ai, enterprise-ai, enterprise, cost, finops, performance, llm, llama.cpp, python, benchmark]
author: manishtiwari25
description: "The same 12-field ERP invoices in six prompt formats: pretty JSON cost 1.86x the tokens of CSV, XML 2.25x, and pretty JSON took 2.4x as long to prefill."
image:
  path: /assets/img/headers/ai/enterprise-ai-prompt-data-formats-token-cost.webp
  alt: "Header card titled What JSON costs in an LLM prompt: tokens per ERP invoice record with the same 12 fields in six formats. XML 215, JSON with indent 2 178, YAML 144, minified JSON 139, Markdown table 100, CSV 96, measured with the SmolLM2-135M tokenizer through llama-server /tokenize"
---

Most enterprise copilots I review put ERP data into the prompt the same way: the backend already has the records as objects, so it calls `JSON.stringify(rows, null, 2)` or `JsonSerializer.Serialize(rows, new() { WriteIndented = true })`, pastes the result under the instructions, and asks the question. It works, the model reads it, and nobody looks at the format again.

The format is not free, though. A model bills, rate-limits and fits its context window in tokens, and every quote, brace, repeated key and indent costs tokens. I wanted to know how much, so I wrote the same vendor invoices in six formats and counted the tokens with the model's own tokenizer. I also timed how long the server took to read each prompt. Everything below comes from one script that is in the repo.

## The setup

- **Records:** synthetic vendor invoices of the kind an accounts-payable assistant reads from Dynamics 365 Finance & Operations or any other ERP. There are 12 fields: invoice id, vendor account, vendor name, invoice date, due date, currency, amount, VAT, main account, cost centre, status and description. They come from a seeded generator (seed 20261124), so every format gets exactly the same values.
- **Formats:** pretty JSON (indent 2), minified JSON, YAML, XML (one element per field), a Markdown table and CSV with a header row.
- **Tokenizer and server:** SmolLM2-135M-Instruct converted to GGUF and served by `llama-server` (llama.cpp b12359, Metal, Apple M2 Pro) with an 8,192-token context. Token counts come from the server's `POST /tokenize`. Prefill times come from `POST /completion` with `n_predict: 1` and `cache_prompt: false`, read from the server's own `timings.prompt_ms`, median of 5 runs after one warm-up.
- **Context fit:** how many records still fit after 1,024 tokens are kept free for the instructions and the answer. The script finds this by bisection with the real tokenizer, not by dividing.

A small model keeps the prefill runs short. It also means the absolute counts are for this one BPE tokenizer (49k vocabulary). GPT-4o, Claude or Llama 3 will give different numbers. The ranking comes from repeated keys, quotes and indentation, which every BPE tokenizer has to pay for, so it should carry over. You can check it against your own model in a minute (see "Run it yourself").

## The result

![Three bar charts side by side for six prompt formats of the same 12-field invoice records. Tokens per record: XML 215, JSON indent 2 178, YAML 144, minified JSON 139, Markdown table 100, CSV 96. Records that fit in 8,192 tokens with 1,024 reserved: XML 33, JSON indent 2 40, YAML 49, minified JSON 51, Markdown table 71, CSV 75. Prefill time for 30 records: XML 930 ms, JSON indent 2 679 ms, YAML 498 ms, minified JSON 473 ms, Markdown table 331 ms, CSV 286 ms](/assets/img/posts/ai/enterprise-ai-prompt-data-formats-token-cost-panels.webp){: width="1400" height="700" }

*Same records in each format. Each panel is scaled on its own, so the longest bar is 100% of that panel.*

| Format | Tokens per record | vs CSV | Records that fit in 8,192 (1,024 reserved) | Prefill, 30 records |
|---|---:|---:|---:|---:|
| XML | 215.3 | 2.25x | 33 | 930 ms |
| JSON, indent 2 | 177.7 | 1.86x | 40 | 679 ms |
| YAML | 144.4 | 1.51x | 49 | 498 ms |
| JSON, minified | 139.1 | 1.45x | 51 | 473 ms |
| Markdown table | 100.2 | 1.05x | 71 | 331 ms |
| CSV | 95.6 | 1.00x | 75 | 286 ms |

Three things stand out:

1. **Pretty JSON costs 1.86x the tokens of CSV for the same data.** For a 30-invoice prompt that is 5,358 tokens against 2,936. At 100,000 such calls a month that is about 242 million extra input tokens a month, and they buy nothing.
2. **The format decides how many records you can show the model.** With the same context window and reserve, CSV fits 75 invoices and pretty JSON 40. If your retrieval step returns "the top 60 open invoices", pretty JSON silently truncates the list or makes you move to a bigger, more expensive context tier.
3. **Prefill time grows faster than the token count.** Pretty JSON has 1.82x the tokens of CSV but took 2.37x as long to prefill (679 ms against 286 ms). XML had 2.21x the tokens and took 3.25x as long. Attention cost grows with prompt length, so longer prompts cost more per token. On a hosted API you see this as time to first token.

Minified JSON and YAML came out almost the same (139 and 144 tokens per record). Removing the indentation from JSON saves 22%. Switching to YAML saves about as much, but you then have to quote values like `"2026-10-22"` and `"655000"`, or a YAML parser will read them as a date and a number.

## Where the tokens go

The best way to see the difference is to look at where the tokenizer cuts one record. The page below comes from `token_view.py`. It sends one invoice in three formats to `/tokenize` with `with_pieces: true` and colours each token. Bold white tokens are part of a field value. Grey tokens are keys, quotes, indentation and separators.

![Screenshot of a token view page for one vendor invoice in three formats, each token in its own coloured box. JSON with indent 2 is 182 tokens, of which 84 carry values and 98 are keys, quotes, indentation and separators. YAML is 146 tokens, 83 values and 63 structure. CSV is 139 tokens, 84 values and 55 structure, and most of its structure is the one header row](/assets/img/posts/ai/enterprise-ai-prompt-data-formats-token-cost-token-view.webp){: width="1400" height="1188" }

*One invoice, split by the model's tokenizer. The values cost about 84 tokens in every format. The format only changes what it adds around them.*

The values, such as `INV-20260001`, `Northwind Traders Ltd` and `23809.18`, cost the same 83 or 84 tokens in every format. The format decides only the overhead. Pretty JSON repeats all 12 keys in every record, each wrapped in quotes and followed by `": "`, with a line break and indentation in front, which comes to 98 tokens of structure. CSV writes the keys once in the header row and then pays about one comma per field. That is also why the gap is small for a single record (139 tokens for CSV against 142 for minified JSON) and grows with every record after it. The Markdown table even loses at one record (170 tokens), because its header and `|---|` separator row cost about 70 tokens before any data. By ten records it is already ahead of every JSON and YAML variant.

Two details from this view are worth knowing:

- **Field names cost tokens too.** `vendor_account` is four tokens here (`v`, `endor`, `_`, `account`). The JSON and YAML formats pay for it in every record, so a short key such as `vendor` instead of `vendor_account` saves two tokens per record for that one field. Shorter keys are the cheapest change if you have to keep JSON.
- **Numbers and ids are expensive in every format.** This tokenizer gives every digit its own token, so `23809.18` is 8 tokens and `INV-20260001` is 11. Leave out the fields the question does not need. Removing two unused fields saves more than any change of format.

## What I would do in an enterprise copilot

- **Use a table for lists of records the model only reads.** Use CSV or a Markdown table when you send the model invoice lines, ticket lists or stock levels to answer a question about. Both formats work equally well. Markdown is easier to read when you debug a prompt, and it cost only 5% more tokens here.
- **Keep JSON for nested data and for the model's output.** Use JSON when the records are trees, such as an order with lines and each line with dimensions, because a table has to flatten them. Also keep structured output as JSON with a schema, as in the [D365 F&O invoice coding workflow](/posts/enterprise-ai-azure-openai-d365fo-vendor-invoice-coding/). The point is not to remove JSON everywhere. It is to stop sending pretty-printed JSON as input by default.
- **Never send indented JSON to a model.** If you change nothing else, minify it. Here that saved 22% of the tokens and 30% of the prefill time.
- **Check answer quality before you switch.** This post measures cost and prefill time, not accuracy. A model can read a wide table less reliably than labelled fields, especially with many columns. Put the format change through the same golden set you use for prompt changes, as in [LLM eval harness CI gates](/posts/ai-sdlc-llm-eval-harness-ci-gates-dotnet/), before it reaches users.
- **Count the tokens in CI, not in your head.** "About four characters per token" was wrong for all six formats here: they ranged from 1.53 characters per token (CSV) to 2.33 (XML). A test that counts the tokens of a real prompt and fails above a budget catches the day someone adds `WriteIndented = true` back. For the .NET side, see [Azure OpenAI token counting](/posts/azure-openai-token-counting-cost-dotnet/).

## Run it yourself

The scripts use only the standard library, plus Pillow for the charts. Any llama.cpp server works. Point it at the GGUF of the model you actually use, and the counts come from that model's tokenizer.

```bash
python3 scripts/finetune-eval/hf_to_gguf.py <SmolLM2-135M-Instruct snapshot> .tmp/smollm2-135m.gguf
llama-server -m .tmp/smollm2-135m.gguf -c 8192 -np 1 -ngl 99 --port 8093 &
python3 scripts/enterprise-ai-prompt-formats/measure.py --port 8093 --prefill-records 30 \
    --out scripts/data/enterprise-ai-prompt-formats.json | tee .tmp/formats-term.txt     # ~30 s
python3 scripts/enterprise-ai-prompt-formats/token_view.py --port 8093 --out .tmp/token-view.html
```

The numbers are in `scripts/data/enterprise-ai-prompt-formats.json`. Here is the raw output of the run used in this post:

![Terminal output of measure.py. The first table lists, per format, the tokens for 1, 10, 50 and 200 records, tokens per record, characters per token, records that fit and the ratio to CSV: json_pretty 182, 1775, 8830, 35487 tokens, 177.7 per record, fit 40, 1.86x; csv 139, 994, 4766, 19106 tokens, 95.6 per record, fit 75, 1.00x. The second table lists prefill for 30 records: json_pretty 5358 prompt tokens in 678.6 ms, xml 6491 tokens in 930.0 ms, csv 2936 tokens in 285.8 ms](/assets/img/posts/ai/enterprise-ai-prompt-data-formats-token-cost-terminal.webp){: width="1400" height="682" }

*The raw output, one colour per format. Token counts are exact and do not change between runs. The five prefill runs per format stayed within 5% of their median.*

To check the same thing on a prompt of your own without a server, paste it into the [Lamplit Labs token counter](https://tools.lamplitlabs.com/token-counter), once as pretty JSON and once as a table. The [AI pricing calculator walkthrough](/posts/ai-pricing-calculator-estimating-llm-api-costs-before-you-ship/) turns the difference into a monthly figure.

*Changing one variable, measuring it against a baseline and keeping the change only when the numbers say so is how we tune the prompts behind Lamplit Labs' products. It is also at the core of **Pulse**, Lamplit Labs' self-improving automation product, coming soon.*

## Related posts

- [Token budgets that hold under concurrency, measured on an LLM gateway](/posts/enterprise-ai-token-budgets-concurrency-measured/)
- [Wiring Azure OpenAI into a D365 F&O vendor invoice workflow](/posts/enterprise-ai-azure-openai-d365fo-vendor-invoice-coding/)
- [Token counter: checking prompt size and context window fit](/posts/token-counter-checking-prompt-size-and-context-window-fit/)
- [Azure OpenAI prompt caching in .NET](/posts/azure-openai-prompt-caching-dotnet/)
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/)
