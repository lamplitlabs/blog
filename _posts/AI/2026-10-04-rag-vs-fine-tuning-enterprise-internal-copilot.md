---
layout: post
title: "Enterprise AI: RAG vs Fine-tuning for an Internal Copilot - Cost, Latency, Freshness and Governance"
date: 2026-10-04 09:00:00 -0500
categories: ai
tags: ai azure openai enterprise rag fine-tuning architecture dotnet
author: manishtiwari25
description: "RAG or fine-tuning for an enterprise internal copilot? A side-by-side on cost, latency, data freshness and governance, with a decision table."
image:
  path: /assets/img/headers/ai/rag-vs-fine-tuning-internal-copilot.webp
  alt: "Side-by-side comparison of RAG and fine-tuning for an enterprise internal copilot: freshness, latency, cost and governance"
---

Every internal-copilot pitch I have reviewed this year ends in the same argument: "we should fine-tune a model on our documents" versus "we should just put a vector index in front of GPT-4o". Both camps are usually arguing about the wrong axis. For an *internal* copilot (HR policy, engineering runbooks, sales playbooks, support macros) the decision is rarely about answer quality. It is about four operational properties: **what it costs per month, how long the user waits, how stale the answers are allowed to be, and who is allowed to see what**. This post puts numbers and a decision table on each.

![RAG vs fine-tuning side-by-side for an internal copilot](/assets/img/headers/ai/rag-vs-fine-tuning-internal-copilot.webp)

{% include feed-ads.html %}

## The scenario

To keep the comparison honest, fix the use case:

- 5,000 employees, roughly **40,000 questions per month** (about 1,300 per working day).
- Knowledge base of **12,000 documents** (Confluence, SharePoint, PDFs), ~60 MB of text, updated by dozens of people every week.
- Hosted on Azure OpenAI; the team already has `gpt-4o-mini` and `text-embedding-3-small` deployments.
- Answers must respect existing document permissions (a contractor must not see the M&A folder).

Everything below is for that shape of problem. A customer-facing chatbot or a code-completion model would tilt several rows.

## What each approach actually does

**RAG (retrieval-augmented generation)** keeps the model frozen. At query time you embed the question, pull the top-k chunks from a search index (Azure AI Search, PostgreSQL + pgvector, etc.), and paste them into the prompt. The model's job is to read and summarise, not to remember. I covered the embedding pipeline in [Azure OpenAI embeddings and semantic search in .NET]({% post_url AI/2026-10-01-azure-openai-embeddings-semantic-search-dotnet %}).

**Fine-tuning** changes the weights. You prepare a JSONL file of prompt/completion pairs, run a supervised fine-tuning job (hours), and deploy the resulting model to its own hosted endpoint. The knowledge is now *inside* the model; prompts can be shorter, and the model picks up tone, format and domain vocabulary.

These are not mutually exclusive, and the best production systems I have seen combine them. But each dollar and each millisecond lands in a different place.

## Cost

Rough monthly figures for the scenario above, using public Azure OpenAI list prices at the time of writing. Treat the absolute numbers as order-of-magnitude; the *ratios* are what matter.

| Cost item | RAG (gpt-4o-mini + AI Search) | Fine-tuned gpt-4o-mini |
|---|---|---|
| One-off preparation | Chunk + embed 60 MB of text: a few dollars of embedding tokens, plus 1-2 engineer-weeks on ingestion and ACL mapping | Curate 2,000-10,000 Q&A pairs: 2-4 engineer-weeks; training run itself typically tens to low hundreds of dollars |
| Per-query model tokens | Long prompts: ~3,000 input tokens of retrieved context + 300 output. 40k queries ≈ 120M input tokens → roughly **$20-30/month** | Short prompts: ~400 input + 300 output. 40k queries ≈ 16M input tokens → **$5-10/month**, but at the fine-tuned token rate (~1.5-2x base) |
| Always-on infrastructure | Azure AI Search Basic/S1 tier: **~$75-250/month** regardless of traffic | Fine-tuned deployment hosting fee: **~$1.70/hour ≈ $1,200/month** per deployment, charged even at zero traffic |
| Keeping it current | Re-embed changed documents nightly: cents | Re-run the fine-tune and redeploy: engineer time plus another training run, every time policies change |

The surprise for most teams is the **hosting line**. A fine-tuned deployment is billed by the hour whether or not anyone is asking questions, and you need at least two of them (staging and production) if you take release discipline seriously. For 40k queries a month, RAG's token bill plus a search tier is comfortably cheaper. Fine-tuning wins on cost only when query volume is high enough that the per-token savings from short prompts outrun the fixed hosting fee - typically several hundred thousand queries per month per deployment.

## Latency

Measured on a `gpt-4o-mini` deployment in Sweden Central, p50/p95 over a working day, using the streaming approach from [streaming Azure OpenAI responses in .NET]({% post_url AI/2026-09-30-streaming-azure-openai-responses-dotnet %}) so the user sees first tokens quickly:

| Stage | RAG | Fine-tuned |
|---|---|---|
| Embed the question | 40-80 ms | - |
| Vector/hybrid search (top 8, with ACL filter) | 60-250 ms | - |
| Prompt build + time to first token | 500-900 ms (3k-token prompt) | 300-500 ms (400-token prompt) |
| **Time to first token (p95)** | **~1.2 s** | **~0.6 s** |
| Full answer (300 tokens) | ~3.5 s | ~3.0 s |

Fine-tuning is faster, mostly because the prompt is short and there is no retrieval hop. In practice the gap is 400-600 ms at p95, which users notice in a chat UI but rarely complain about once tokens are streaming. If the retrieval hop is your bottleneck, the cheap fixes are: cache embeddings of repeated questions, use a hybrid (keyword + vector) query so you can drop *k* from 8 to 4, and keep the search service in the same region as the model.

## Data freshness

This is the axis that decides most internal copilots.

| Question | RAG | Fine-tuned |
|---|---|---|
| New HR policy published Monday 9:00 - when does the copilot know? | After the next ingestion run (minutes to hours) | After someone notices, adds examples, retrains and redeploys (days to weeks) |
| Document deleted because it was wrong | Gone from answers at the next index update | Still "known" by the model until retrained; you cannot delete a fact from weights |
| Can you cite the source? | Yes - return the chunk's URL and last-modified date with the answer | No reliable way; the model may invent a plausible document title |

Internal knowledge churns. In our scenario dozens of people edit documents every week; a fine-tuned model is out of date the day after it ships. Fine-tuning is appropriate for knowledge that is **stable for quarters**: product terminology, internal code conventions, the house style for incident reports.

## Governance

This is where the two approaches differ in *kind*, not degree.

| Concern | RAG | Fine-tuned |
|---|---|---|
| Per-user document permissions | Enforce at retrieval: filter the search query by the caller's group claims so restricted chunks never reach the prompt | Not possible. Once the M&A folder is in the training set, every user of that deployment can elicit it |
| Right to be forgotten / data deletion | Delete the chunk, re-index | Retrain from a cleaned dataset |
| Audit: "why did it say that?" | Log the retrieved chunk IDs with the response | Only the prompt and completion; the reasoning is in the weights |
| Data residency | Index and model both stay in your chosen region | Training data and the resulting model are tied to the fine-tuning region; check it matches your classification |
| Review effort | Standard: it is a search index plus an API | Higher: a new model artefact that security and legal want to assess as its own asset |

For a copilot that spans HR, finance and engineering content, the permissions row alone rules out fine-tuning *on the documents*. The governance checklist in [Enterprise AI governance for Azure OpenAI]({% post_url AI/2026-10-03-enterprise-ai-governance-azure-openai %}) applies to both, but RAG lets you reuse the access-control model you already have.

## The decision table

| If your situation is... | Choose | Why |
|---|---|---|
| Knowledge changes weekly or faster | RAG | Freshness in minutes, deletions actually delete |
| Answers must respect existing document permissions | RAG | ACL filtering at retrieval; weights cannot be filtered per user |
| You need citations the user can click | RAG | Chunk metadata travels with the answer |
| The gap is tone, format or domain vocabulary, not facts | Fine-tune a small model (or start with few-shot examples) | Cheap to train, short prompts, stable for quarters |
| Query volume is in the hundreds of thousands per month and prompts are long | Consider fine-tuning to shorten prompts | Per-token savings start to beat the hosting fee |
| p95 time-to-first-token must be under ~700 ms | Fine-tune, or RAG with aggressive caching and small *k* | Retrieval hop costs 100-350 ms |
| Both facts change and style matters | RAG for facts + fine-tuned small model for style | The common production shape |

![Decision flow for choosing between RAG, fine-tuning and prompt engineering for an internal copilot](/assets/img/posts/ai/rag-vs-fine-tuning-decision-flow.webp)

## What I would ship for this scenario

1. **RAG first**, with Azure AI Search hybrid queries, ACL filtering by Entra group, and nightly incremental re-indexing. This covers freshness, governance and citations on day one, for well under $500/month.
2. Instrument retrieval: log chunk IDs, hit rate and the fraction of answers where the model says it could not find anything. Those numbers tell you whether the index or the prompt is the problem.
3. Only after a quarter of logs, **fine-tune `gpt-4o-mini` for format and tone** if reviewers keep editing the answers' structure. Train on your own approved answers, not on the source documents, so the permissions model is untouched.
4. Revisit the cost table when monthly volume crosses ~250k queries; that is roughly where the fixed hosting fee of a fine-tuned deployment stops being the dominant line.

The argument "RAG vs fine-tuning" is mostly a false choice for internal copilots. Retrieval owns the facts; fine-tuning, if you do it at all, owns the voice.

## Related posts

- [Azure OpenAI Embeddings in .NET: Semantic Search Without a Vector Database](/posts/azure-openai-embeddings-semantic-search-dotnet/)
- [Evaluating a RAG Retriever in .NET: Precision@k, Recall@k, MRR and a Golden Set You Can Run in CI](/posts/evaluating-rag-retriever-golden-set-dotnet/)
- [Enterprise AI: Six Governance Controls Before Azure OpenAI Goes to Production in a Regulated Org](/posts/enterprise-ai-governance-azure-openai/)
