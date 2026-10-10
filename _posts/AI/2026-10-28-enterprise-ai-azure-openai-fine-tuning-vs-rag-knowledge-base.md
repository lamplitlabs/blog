---
layout: post
title: "Enterprise AI: Azure OpenAI Fine-tuning vs RAG for an Enterprise Knowledge Base - A Worked Example with Numbers"
date: 2026-10-28 08:00:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise rag fine-tuning architecture knowledge-base enterprise-ai
author: manishtiwari25
description: "Fine-tuned gpt-4o-mini, RAG and a hybrid run against one 400-question golden set on an 18,000-document knowledge base: accuracy, citations, staleness, cost."
image:
  path: /assets/img/headers/ai/enterprise-ai-fine-tuning-vs-rag-knowledge-base.webp
  alt: "Grouped bar chart comparing fine-tuned gpt-4o-mini, RAG and RAG plus fine-tuning on a 400-question golden set: correct answers 61, 87 and 91 percent; answers with a valid citation 0, 84 and 86 percent; wrong but confident 22, 6 and 5 percent; stale after 30 days of edits 29, 3 and 3 percent"
---

![Grouped bar chart: correct answers 61% fine-tuned, 87% RAG, 91% hybrid; valid citation 0%, 84%, 86%; wrong but confident 22%, 6%, 5%; stale after 30 days 29%, 3%, 3%](/assets/img/headers/ai/enterprise-ai-fine-tuning-vs-rag-knowledge-base.webp){: width="1200" height="630" }

The [RAG vs fine-tuning for an internal copilot]({% post_url AI/2026-10-04-rag-vs-fine-tuning-enterprise-internal-copilot %}) post made the argument from first principles. This one is the experiment: the same knowledge base, the same 400 questions, three builds on Azure OpenAI, measured for a month. If you only want the decision rule, jump to [the decision table](#the-decision-table). If you have been asked "why don't we just fine-tune it on our docs?" in a steering meeting, the numbers below are what I now put on the slide.

## The knowledge base

- **18,000 documents** (SharePoint policies, Confluence runbooks, a ticketing system's resolved-incident notes), about 95 MB of text after HTML stripping.
- **Edit rate:** roughly 600 documents changed or added per month; 40-60 deleted or superseded.
- **Users:** 7,000 employees across support, finance and IT; about **40,000 questions per month**.
- **Constraints:** answers must carry a source link, and a user must never see content from a document they cannot open themselves.
- **Platform:** Azure OpenAI in Sweden Central, `gpt-4o-mini` for generation, `text-embedding-3-large` for RAG, Azure AI Search S1 with hybrid (BM25 + vector) and semantic ranker.

## The three builds

**Build A - fine-tuned on the documents.** We generated 14,200 question/answer pairs from the corpus with `gpt-4o` (two to four per document, reviewed by sampling 5%), ran a supervised fine-tuning job on `gpt-4o-mini` (3 epochs, about 4 hours), and deployed it. Prompt: system message plus the user question, no retrieval. This is the build most people mean when they say "fine-tune it on our data".

**Build B - RAG.** Documents chunked at ~600 tokens with 80-token overlap, embedded, indexed with a `groups` field holding the Entra group ids allowed to read the source. At query time: embed the question, hybrid search with a filter on the caller's groups, top 6 chunks into the prompt, model instructed to answer only from the context and to return the chunk ids it used. This is the pipeline from the [embeddings in .NET]({% post_url AI/2026-10-01-azure-openai-embeddings-semantic-search-dotnet %}) post, with the retriever evaluated the way the [golden set post]({% post_url AI/2026-10-11-evaluating-rag-retriever-golden-set-dotnet %}) describes.

**Build C - RAG plus a small fine-tune for format.** Same retrieval as B, but the generator is `gpt-4o-mini` fine-tuned on 900 *approved answers* (not on the documents) so that it reliably produces the house format: one-paragraph answer, bullet of steps, citation list. No facts in the training data that are not also in the index.

## How we scored them

A **golden set of 400 questions** written by support leads and policy owners, each with an accepted answer and the source document(s). Three reviewers scored every answer blind as *correct*, *partially correct* or *wrong*; a citation counted as valid only if the linked document actually supported the answer. To measure staleness, we froze the three builds on day 0, let the knowledge base churn for 30 days (the RAG index kept re-indexing nightly; the fine-tuned model was of course not retrained), and re-ran the 92 golden questions whose source documents had changed in that window.

| Metric (400 questions) | A: fine-tuned on docs | B: RAG | C: RAG + format fine-tune |
|---|---|---|---|
| Correct | **61%** | **87%** | **91%** |
| Partially correct | 17% | 9% | 6% |
| Wrong but confident (no hedge, no "I don't know") | 22% | 6% | 5% |
| Answer carries a valid citation | 0% | 84% | 86% |
| Said "not in the knowledge base" when it really was not (40 trap questions) | 15% | 83% | 85% |
| Stale answers on the 92 changed-document questions after 30 days | 29% | 3% | 3% |
| Permission leak in 60 restricted-document probes | 11 leaks | 0 | 0 |
| p95 time to first token | 0.55 s | 1.15 s | 1.20 s |

Three things in this table surprised the team.

1. **Fine-tuning on documents did not teach the model the documents.** 61% correct sounds respectable until you look at the 22% that were confidently wrong: the model had learned the *shape* of our policies and happily produced plausible retention periods, approval thresholds and server names that did not exist. 14,200 pairs over 18,000 documents is roughly one glimpse per fact; weights do not reliably store that.
2. **Zero citations is structural, not a tuning problem.** We tried training with the source URL in the completion. The model produced URLs 93% of the time; 41% of them pointed at the wrong document or did not exist. A citation you cannot trust is worse than none.
3. **The permission leaks were the hard stop.** Eleven of sixty probes from a contractor account returned content from the restricted finance folder. There is no per-user filter on weights. For RAG the filter is a `search.in(groups, ...)` clause on the query, and it held at 0 across every probe.

Build C beat B by four points mostly by eliminating answers that were right but unusable: wrong structure, missing the steps list, citation buried mid-paragraph. Reviewers had been marking those "partially correct".

## Cost and maintenance

![Line chart of monthly cost against questions per month from 0 to 500k: RAG starts near 250 dollars and rises slowly with tokens; fine-tuned starts near 2,500 dollars for two hosted deployments and rises more slowly; RAG plus one fine-tuned format model sits between them; at 40k questions per month RAG is about 430 dollars and fine-tuned about 2,550](/assets/img/posts/ai/fine-tuning-vs-rag-kb-cost-vs-volume.webp){: width="1200" height="700" }

List prices at the time of writing; treat the absolute numbers as order of magnitude and the shape as the point.

| Monthly line | A: fine-tuned | B: RAG | C: hybrid |
|---|---|---|---|
| Model tokens at 40k questions | ~$50 (short prompts, fine-tuned rate) | ~$180 (6 chunks ≈ 3.5k input tokens per question) | ~$190 |
| Always-on | 2 fine-tuned deployments (staging + prod) ≈ **$2,500** | AI Search S1 ≈ **$250** | AI Search S1 + 1 fine-tuned deployment ≈ $1,500 |
| Keeping it current | Regenerate pairs for changed docs, retrain (~$60-120 per run), re-evaluate, redeploy: about **2 engineer-days per month**, and the model is stale between runs | Nightly incremental re-index: cents, no engineer time once the pipeline is stable | Same as B; the format model is retrained only when the house style changes (twice a year so far) |
| **Total** | **≈ $2,550 + 2 days** | **≈ $430** | **≈ $1,700** |

The hosting fee dominates. A fine-tuned deployment is billed per hour whether or not anyone asks a question, and anyone who takes release discipline seriously runs two. RAG's cost curve starts low and grows with tokens; fine-tuning's starts high and grows slowly. The curves cross somewhere above 400k questions per month for this prompt size, and even there the fine-tuned build is still wrong 22% of the time, so the crossover is academic for a *knowledge* use case.

Latency is the one axis fine-tuning won cleanly: no embedding call, no search hop, a prompt a tenth of the size. 600 ms at p95 is noticeable in a chat UI. We clawed back about 200 ms in build B by caching question embeddings and dropping *k* from 8 to 6 after the golden set showed recall@6 within a point of recall@8.

## When fine-tuning is the right tool

None of this says "never fine-tune". It says fine-tuning is the wrong place to put **facts that change and must be cited**. It is the right tool when:

- **The gap is behaviour, not knowledge.** Output format, tone, consistently calling the right internal function, refusing in the house style. Build C is this: 900 examples, a few dollars of training, stable for months.
- **The domain vocabulary breaks the base model.** Internal product codenames, a proprietary query language, abbreviations the model keeps "correcting". Fine-tune for the language, retrieve for the content.
- **Prompt length is the cost driver.** If you are shipping a 2,000-token system prompt of rules on every call at high volume, a fine-tune that internalises the rules can pay for its hosting fee.
- **The knowledge is genuinely static and uncited.** Classification labels, routing decisions, a fixed taxonomy. Nobody needs a citation for "this ticket is a password reset".

For everything that lives in SharePoint, Confluence or a ticketing system and gets edited by people every week, retrieval owns the facts.

## The decision table

| If... | Pick | Evidence from this run |
|---|---|---|
| Users need to click through to the source | RAG | 84-86% valid citations vs 0% |
| Documents have per-user or per-group permissions | RAG | 0 leaks vs 11 in 60 probes |
| Content changes weekly or faster | RAG | 3% vs 29% stale after 30 days |
| "I don't know" matters more than a fast guess | RAG | 83% vs 15% correct abstention on trap questions |
| Reviewers keep rewriting the *shape* of correct answers | RAG + small format fine-tune | +4 points correct, mostly converted from "partial" |
| p95 first token must be well under a second | Fine-tune, or RAG with embedding cache and small *k* | 0.55 s vs 1.15 s |
| Volume is in the hundreds of thousands per month and prompts are long | Re-run the cost table; the curves cross | ~400k/month crossover at this prompt size |

## What we shipped

Build C, with three operational additions: the retriever golden set runs in CI on every chunking or index change; the APIM layer logs the chunk ids used per answer so an auditor can replay "why did it say that" (the [audit trail]({% post_url AI/2026-10-26-enterprise-ai-audit-trail-azure-openai-apim %}) post covers the plumbing); and the format model is retrained from approved answers only, never from source documents, so there is nothing in its weights that the index does not also hold and permission-filter.

The question "fine-tuning or RAG for our knowledge base?" turned out to have a measurable answer. Retrieval for the facts, a small fine-tune for the voice, and a golden set so you can prove it to the next steering meeting.

## Related posts

- [Enterprise AI: RAG vs Fine-tuning for an Internal Copilot - Cost, Latency, Freshness and Governance](/posts/rag-vs-fine-tuning-enterprise-internal-copilot/)
- [Evaluating a RAG Retriever in .NET: Precision@k, Recall@k, MRR and a Golden Set You Can Run in CI](/posts/evaluating-rag-retriever-golden-set-dotnet/)
- [Enterprise AI: An Audit Trail for Every Azure OpenAI Call with APIM, Event Hubs and Immutable Storage](/posts/enterprise-ai-audit-trail-azure-openai-apim/)
