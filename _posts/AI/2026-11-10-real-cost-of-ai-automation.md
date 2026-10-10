---
layout: post
title: "The Real Cost of AI Automation vs the Hype - Where the Money Goes After the Token Bill"
date: 2026-11-10 00:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise cost finops governance observability enterprise-ai
author: manishtiwari25
description: "A worked monthly cost model for one AI automation: tokens are 13 percent, human review, failures, monitoring and governance are the rest. With numbers."
image:
  path: /assets/img/headers/ai/real-cost-of-ai-automation.webp
  alt: "Two horizontal bars comparing a hype estimate of 1,200 dollars for tokens against a measured 12,400 dollars split into tokens, human review, failures, monitoring and governance"
---

"It is just an API call, the tokens cost a few hundred dollars, we switch it on next week." That sentence has started more AI automation projects than any business case, and it is wrong in a specific, measurable way: the token bill is the **smallest** recurring line once the thing is in production. This post walks through one real-shaped workload, an invoice-processing bot on Azure OpenAI handling 50,000 documents a month, and puts a number on each cost driver that the hype line leaves out. The pricing is the same public list pricing used in the [token counting post](/posts/azure-openai-token-counting-cost-dotnet/) and the [PTU vs pay-as-you-go comparison](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/); the labour numbers are deliberately conservative.

## The hype estimate

The pre-project estimate usually looks like this:

- 50,000 invoices x ~1,500 input tokens + ~300 output tokens
- GPT-4o class pricing: roughly $2.50 per million input, $10 per million output
- 75 M input tokens = $188, 15 M output tokens = $150, plus a safety margin

Rounded up generously: **$1,200 per month**. Compared with the two people currently keying invoices, that is a 90 percent saving on paper, and the slide writes itself.

Every number in that estimate is correct. What is missing is everything that happens *after* the model returns a JSON object.

## What month three actually looked like

![Table comparing the hype estimate with measured month-three cost per driver: tokens 1,800, human review 6,400, failures and rollback 1,500, monitoring 1,100, governance 1,600, total 12,400](/assets/img/posts/ai/real-cost-of-ai-automation-cost-breakdown-table.webp)

### 1. Tokens and compute: $1,800 (13 percent)

The token line was over by 50 percent, not because pricing changed, but because:

- **Retries on 429s and timeouts** re-sent full prompts. At a 6 percent retry rate (normal on a shared pay-as-you-go deployment during month-end peaks, see the [429 retry post](/posts/azure-openai-429-rate-limit-retry-dotnet/)) that is 6 percent more tokens.
- **Prompt growth.** Every edge case found in review became another instruction or few-shot example. The system prompt went from 400 to 1,900 tokens between week 1 and week 10. That is 75 M extra input tokens a month on its own until someone cached the prefix.
- **Multi-page PDFs** where the 1,500-token assumption was an average, not a cap. The p95 document was 4,200 tokens.

None of this is a surprise to anyone who has run an LLM workload; all of it is absent from the hype slide.

### 2. Human review and correction: $6,400 (52 percent)

This is the line that turns "we replaced two people" into "we redeployed two people". The bot's extraction accuracy on the golden set was 94 percent, which sounds like an A grade until you multiply it out:

- 6 percent of 50,000 = **3,000 documents a month with at least one wrong field**.
- A business rule routed anything with a confidence flag, a vendor not seen before, or a total mismatch to a human. That caught most errors but also flagged 12 percent of correct documents. **18 percent of all documents were touched by a person.**
- 9,000 documents x 4 minutes average = 600 hours = roughly 3.6 FTE-weeks a month, which at a loaded $40 an hour is **$6,400** before the second-level finance approvals the process already had.

The uncomfortable part: the human cost did not drop in a straight line as accuracy improved. Going from 94 to 97 percent halved the hard errors but the review queue only shrank by a quarter, because the confidence routing rules were tuned for the old error profile and nobody owned retuning them.

### 3. Failures and rollback: $1,500 (12 percent)

Two incidents in the month:

- A prompt change on a Tuesday afternoon started emitting dates as `DD/MM` for a subset of vendors. It ran for 11 hours before a finance analyst noticed. 2,100 documents were re-run (tokens again), 340 had already been posted to the ERP and needed manual reversal.
- A model version update on the deployment changed how line-item arrays were ordered. The downstream matcher silently dropped 2 percent of lines for three days.

Engineer time to diagnose, re-run, reverse and write the incident review was about 30 hours, plus the re-run tokens, plus the second batch of human corrections. The [canary rollout and rollback post](/posts/enterprise-ai-canary-rollout-llm-model-prompt-rollback/) exists because of exactly this shape of failure; the cost of *not* having it is this line.

### 4. Monitoring and evaluation: $1,100 (9 percent)

The cheapest line, and the one that shrinks the two above it:

- A 400-document golden set, re-labelled quarterly: about 20 hours of analyst time a quarter, call it $270 a month amortised.
- Nightly evaluation run against the golden set on every prompt or model change: roughly 1 M tokens a night, $75 a month.
- Dashboards and alerts on cost burn rate, p95 latency, extraction confidence distribution and review-queue depth, built once on the [cost dashboard](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/) and [SLO burn-rate](/posts/enterprise-ai-llm-cost-latency-slos-production/) patterns: about 8 hours a month of upkeep.

Both incidents above would have been caught in under an hour with the confidence-distribution alert that was added afterwards. That alert cost a day to build.

### 5. Governance and audit: $1,600 (13 percent)

Invoices are financial records, so the bot inherited every control the manual process had, plus some new ones:

- Prompt and model changes go through a change review with a named approver: a meeting a week, four people, 30 minutes.
- Audit trail of every request and response with content hashes, retained for seven years ([audit trail via APIM](/posts/enterprise-ai-audit-trail-azure-openai-apim/)): storage is cheap, the quarterly audit evidence pack is not.
- Access reviews for the service principal, the key vault, and the storage account holding the PDFs.
- Vendor and data-residency assessment that had to be redone when the model version changed.

Most of this is people time spread thinly across security, finance and platform teams, which is exactly why it never appears on the project's own budget line.

## The honest comparison

| | Hype slide | Measured, month 3 |
|---|---|---|
| Monthly cost | $1,200 | $12,400 |
| Cost per document | $0.024 | $0.25 |
| People involved | 0 | ~1.5 FTE equivalent across review, ops, governance |
| Manual baseline | $13,000 (2 FTE) | $13,000 |
| Saving | 91 percent | **5 percent** |

The automation still paid for itself, marginally, and by month six, with prompt caching, retuned routing rules and the confidence alert, it was at about $8,900 a month, a real 30 percent saving. That is a good outcome. It is not the outcome that was promised, and the gap between the two is where projects get cancelled in month four by someone who only saw the first slide.

## What to put on the slide instead

1. **Multiply tokens by at least 1.5x** for retries, prompt growth and long-tail documents. Use measured p95 token counts, not the average.
2. **Model the review queue explicitly.** Error rate x volume x minutes per correction x loaded rate. Include the false-positive routing rate; it is usually bigger than the error rate.
3. **Budget two incidents a quarter** with re-run tokens and a day of engineering each, and fund the canary and rollback path up front because it is cheaper than one incident.
4. **Fund the golden set and the alerts** before go-live. It is the only line that reduces the others.
5. **Ask finance, security and platform** what controls the manual process had and assume every one of them survives, plus change review for prompts and models.
6. **Report cost per processed document, end to end,** including people, and track it monthly. That is the number that decides whether the automation is working, and it is the only one the hype estimate cannot fake.

AI automation is neither free nor instant. It is a production system with an unusually cheap compute line and an unusually expensive correctness line, and the budget should look like that from day one.

## Related posts

- [Enterprise AI: LLM cost and latency SLOs in production](/posts/enterprise-ai-llm-cost-latency-slos-production/)
- [Azure OpenAI PTU vs pay-as-you-go under sustained load](/posts/enterprise-ai-azure-openai-ptu-vs-pay-as-you-go-sustained-load/)
- [Canary rollout and rollback for LLM model and prompt changes](/posts/enterprise-ai-canary-rollout-llm-model-prompt-rollback/)
- [Azure OpenAI cost observability dashboard](/posts/enterprise-ai-azure-openai-cost-observability-dashboard/)
- [AI SDLC: human vs agent PR review, test coverage and quality](/posts/ai-sdlc-human-vs-agent-pr-review-test-coverage-quality/)
