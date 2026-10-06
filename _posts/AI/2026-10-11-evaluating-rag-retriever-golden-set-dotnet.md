---
layout: post
title: "Evaluating a RAG Retriever in .NET: Precision@k, Recall@k, MRR and a Golden Set You Can Run in CI"
date: 2026-10-11 09:00:00 -0500
categories: ai
tags: ai azure openai rag evaluation dotnet testing ai-sdlc enterprise
author: manishtiwari25
description: "Stop eyeballing RAG answers. Build a golden set, compute Precision@k, Recall@k and MRR for your .NET retriever, and gate regressions in CI."
image:
  path: /assets/img/headers/ai/rag-retriever-evaluation-dotnet.webp
  alt: "Bar chart of Precision@5, Recall@5, MRR and Hit@5 for a RAG retriever next to a golden set of 200 queries"
---

Most RAG quality problems I have debugged were not model problems. The LLM did exactly what it was told with the chunks it was given; the chunks were simply the wrong ones. Yet almost every team I meet evaluates their pipeline end-to-end ("does the answer look right?") and almost nobody measures the retriever on its own. That is backwards: the retriever is deterministic, cheap to run thousands of times, and the single biggest lever on answer quality. This post shows how to build a **golden set**, compute **Precision@k, Recall@k, MRR and nDCG** in plain C#, and turn the numbers into an xUnit test that fails the build when a chunking or embedding change silently makes retrieval worse.

![Bar chart of Precision@5, Recall@5, MRR and Hit@5 for a RAG retriever next to a golden set of 200 queries](/assets/img/headers/ai/rag-retriever-evaluation-dotnet.webp)

{% include feed-ads.html %}

## Why evaluate the retriever separately

End-to-end LLM evaluation ("LLM-as-judge") is slow, costs tokens, and is noisy: the same chunks can produce a good answer on one run and a hedged one on the next. Retriever evaluation has none of those problems:

| Property | End-to-end eval | Retriever eval |
|---|---|---|
| Deterministic | No (sampling) | Yes |
| Cost per query | 1 LLM call + judge call | 1 embedding + 1 search |
| Runtime for 200 queries | minutes | seconds |
| Pinpoints the cause | No | Yes: chunking, embedding model, k, filters |

You still want end-to-end checks before a release. But the retriever metric is the one you can run on every pull request.

## Step 1: Build the golden set

A golden set is a list of realistic user queries, each paired with the IDs of the chunks that *should* be retrieved. You need stable chunk IDs for this, so make chunk IDs content-derived (for example `sha256(docId + ":" + chunkOrdinal + ":" + text)` truncated) rather than auto-increment, otherwise every re-index invalidates your labels.

Store it as JSONL under `tests/golden/retriever.jsonl` and commit it next to the code:

```json
{"id":"q001","query":"How many days of parental leave do contractors get?","relevant":["hr-leave-policy:12","hr-contractors:4"]}
{"id":"q002","query":"Which Azure regions is the payments service deployed to?","relevant":["runbook-payments:2"]}
{"id":"q003","query":"Rotate the Key Vault secret used by the invoicing job","relevant":["runbook-invoicing:7","runbook-invoicing:8","kv-rotation-howto:1"]}
```

Where do the labels come from? Three sources, in order of trust:

1. **Support tickets and search logs** - real questions people asked; a domain owner marks the chunk(s) that answered them.
2. **Synthetic questions generated per chunk** - ask the model "write 3 questions this passage answers"; the chunk is the label. Cheap, biased towards easy lexical matches, so cap it at ~40% of the set.
3. **Adversarial queries** - paraphrases, typos, questions that span two documents. These are what catch chunking regressions.

Two hundred queries is enough to see a 3-point change in Precision@5 with reasonable confidence. Fifty is enough to start.

The C# model is trivial:

```csharp
public sealed record GoldenQuery(string Id, string Query, IReadOnlyList<string> Relevant);

public static class GoldenSet
{
    public static IReadOnlyList<GoldenQuery> Load(string path) =>
        File.ReadLines(path)
            .Where(l => !string.IsNullOrWhiteSpace(l))
            .Select(l => JsonSerializer.Deserialize<GoldenQuery>(l, JsonOptions)!)
            .ToList();

    private static readonly JsonSerializerOptions JsonOptions =
        new(JsonSerializerDefaults.Web);
}
```

## Step 2: An abstraction over the retriever under test

Whether you use Azure AI Search, pgvector, Qdrant or an in-memory index, the evaluator only needs ranked IDs:

```csharp
public interface IRetriever
{
    /// Returns chunk ids ordered best-first; Count <= k.
    Task<IReadOnlyList<string>> SearchAsync(string query, int k, CancellationToken ct = default);
}
```

An Azure AI Search implementation using the `Azure.Search.Documents` package and a vector field looks like this:

```csharp
public sealed class AzureAiSearchRetriever(SearchClient search, IEmbedder embedder) : IRetriever
{
    public async Task<IReadOnlyList<string>> SearchAsync(string query, int k, CancellationToken ct = default)
    {
        ReadOnlyMemory<float> vector = await embedder.EmbedAsync(query, ct);

        var options = new SearchOptions
        {
            Size = k,
            Select = { "chunkId" },
            VectorSearch = new()
            {
                Queries = { new VectorizedQuery(vector) { KNearestNeighborsCount = k, Fields = { "embedding" } } }
            }
        };

        var results = await search.SearchAsync<SearchDocument>(query, options, ct);
        var ids = new List<string>(k);
        await foreach (var r in results.Value.GetResultsAsync().WithCancellation(ct))
            ids.Add(r.Document.GetString("chunkId"));
        return ids;
    }
}
```

Passing `query` as the text parameter *and* a vector query gives you hybrid search; pass `null` for text to evaluate pure vector retrieval. You will want to evaluate both - more on that below.

## Step 3: The metrics, in plain C#

Each metric answers a different question. Here is the full set with definitions for one query; averaging over the golden set gives the reported number.

- **Precision@k** - of the k chunks returned, what fraction are relevant? Measures *noise in the prompt*.
- **Recall@k** - of the relevant chunks, what fraction did we return? Measures *missing evidence*.
- **Hit@k** - did at least one relevant chunk appear? The minimum bar.
- **MRR** (Mean Reciprocal Rank) - 1 / rank of the first relevant chunk. Rewards putting the answer at the top, which matters when you truncate context.
- **nDCG@k** - rank-weighted gain; the most informative single number when queries have several relevant chunks.

```csharp
public sealed record QueryMetrics(string Id, double PrecisionAtK, double RecallAtK, bool Hit, double ReciprocalRank, double NdcgAtK);

public static class RetrievalMetrics
{
    public static QueryMetrics Score(GoldenQuery gold, IReadOnlyList<string> retrieved, int k)
    {
        var relevant = gold.Relevant.ToHashSet(StringComparer.Ordinal);
        var topK = retrieved.Take(k).ToList();

        int hits = topK.Count(relevant.Contains);
        double precision = (double)hits / k;
        double recall = relevant.Count == 0 ? 0 : (double)hits / relevant.Count;

        int firstRank = topK.FindIndex(relevant.Contains); // -1 if none
        double rr = firstRank < 0 ? 0 : 1.0 / (firstRank + 1);

        double dcg = 0;
        for (int i = 0; i < topK.Count; i++)
            if (relevant.Contains(topK[i]))
                dcg += 1.0 / Math.Log2(i + 2);           // rank i+1 -> log2(rank+1)

        int idealHits = Math.Min(relevant.Count, k);
        double idcg = 0;
        for (int i = 0; i < idealHits; i++) idcg += 1.0 / Math.Log2(i + 2);

        return new QueryMetrics(gold.Id, precision, recall, hits > 0, rr, idcg == 0 ? 0 : dcg / idcg);
    }
}
```

Note the `Take(k)`: if your retriever returns more than k results the metric must still be computed at k, otherwise Precision@k is undefined and Recall@k is inflated.

## Step 4: The evaluation harness

```csharp
public sealed record EvalReport(int K, int Queries,
    double PrecisionAtK, double RecallAtK, double HitRateAtK, double Mrr, double NdcgAtK,
    IReadOnlyList<QueryMetrics> PerQuery);

public static class RetrieverEvaluator
{
    public static async Task<EvalReport> RunAsync(IRetriever retriever, IReadOnlyList<GoldenQuery> golden, int k,
        int parallelism = 8, CancellationToken ct = default)
    {
        var results = new ConcurrentBag<QueryMetrics>();

        await Parallel.ForEachAsync(golden,
            new ParallelOptions { MaxDegreeOfParallelism = parallelism, CancellationToken = ct },
            async (q, token) =>
            {
                var ids = await retriever.SearchAsync(q.Query, k, token);
                results.Add(RetrievalMetrics.Score(q, ids, k));
            });

        var list = results.OrderBy(r => r.Id).ToList();
        return new EvalReport(k, list.Count,
            list.Average(r => r.PrecisionAtK),
            list.Average(r => r.RecallAtK),
            list.Average(r => r.Hit ? 1.0 : 0.0),
            list.Average(r => r.ReciprocalRank),
            list.Average(r => r.NdcgAtK),
            list);
    }
}
```

Running this against a 200-query golden set and an Azure AI Search index of about 9,000 chunks takes under ten seconds with `parallelism = 8`, dominated by the embedding calls. Cache query embeddings on disk (keyed by model name + query text) and the second run is well under two seconds.

![Offline retriever evaluation loop: golden set JSONL feeds the retriever under test, metrics are computed, and a CI gate fails if Precision@5 drops](/assets/img/posts/ai/rag-retriever-eval-loop.webp)

## Step 5: Turn it into a CI gate

The metrics are only useful if a regression blocks a merge. Commit a baseline (`tests/golden/baseline.json`) and compare against it with a tolerance. Absolute thresholds ("P@5 must be above 0.7") rot; *relative* thresholds against the last accepted baseline catch what you actually care about - "this PR made retrieval worse".

```csharp
public class RetrieverRegressionTests(RetrieverFixture fx) : IClassFixture<RetrieverFixture>
{
    private const double Tolerance = 0.03; // 3 points

    [Fact]
    public async Task Retriever_does_not_regress_against_baseline()
    {
        var golden = GoldenSet.Load("golden/retriever.jsonl");
        var report = await RetrieverEvaluator.RunAsync(fx.Retriever, golden, k: 5);
        var baseline = JsonSerializer.Deserialize<EvalReport>(File.ReadAllText("golden/baseline.json"))!;

        await File.WriteAllTextAsync("TestResults/retriever-report.json",
            JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));

        Assert.True(report.PrecisionAtK >= baseline.PrecisionAtK - Tolerance,
            $"Precision@5 dropped {baseline.PrecisionAtK:F3} -> {report.PrecisionAtK:F3}");
        Assert.True(report.RecallAtK >= baseline.RecallAtK - Tolerance,
            $"Recall@5 dropped {baseline.RecallAtK:F3} -> {report.RecallAtK:F3}");
        Assert.True(report.Mrr >= baseline.Mrr - Tolerance,
            $"MRR dropped {baseline.Mrr:F3} -> {report.Mrr:F3}");
    }
}
```

The fixture builds the index from the same documents the production indexer uses, into a throwaway index named after the git SHA, so the test exercises real chunking and real embeddings rather than a mock. When someone intentionally improves retrieval, they update `baseline.json` in the same PR - the diff makes the improvement visible to reviewers.

Print the per-query table on failure. The worst-ranked queries tell you *why* it regressed faster than any aggregate:

```csharp
foreach (var q in report.PerQuery.Where(q => !q.Hit).Take(10))
    Console.WriteLine($"MISS {q.Id}: {golden.First(g => g.Id == q.Id).Query}");
```

## What the numbers taught us

A few concrete results from running this harness on an internal runbook corpus (200 golden queries, k = 5):

| Change | P@5 | R@5 | MRR | Verdict |
|---|---|---|---|---|
| Baseline: 512-token chunks, vector only | 0.58 | 0.49 | 0.66 | - |
| 256-token chunks, 64 overlap | 0.61 | 0.57 | 0.69 | keep |
| Hybrid (BM25 + vector) | 0.72 | 0.61 | 0.78 | keep |
| Hybrid + semantic reranker | 0.74 | 0.62 | 0.84 | keep, +90 ms latency |
| Switch embedding model without re-embedding golden queries | 0.31 | 0.27 | 0.35 | **caught in CI** |

The last row is the whole point. The index had been re-embedded with a new model, but the query path still used the old deployment. End-to-end spot checks looked "a bit worse"; the retriever metric showed a collapse in seconds.

Two more lessons:

- **Recall@k is the metric to watch when k is small.** With k = 5 and a prompt budget that fits 3 chunks, a Recall@5 of 0.6 means 40% of answers are generated without the evidence. Raising k to 10 and adding a reranker fixed more complaints than any prompt change.
- **MRR exposes ordering bugs.** When Hit@5 stays flat and MRR drops, the right chunk is still retrieved but ranked lower - usually a scoring-profile or boosting change.

## Where this fits in the AI SDLC

Treat the golden set like a test suite: it lives in the repository, it grows with every production incident ("add the query that failed"), and it runs on every change to chunking, embedding deployment, index schema or search options. The LLM-as-judge evaluation still runs nightly, but it no longer has to explain retrieval failures, because those never reach it.

If you are starting today: write 50 queries from real tickets this week, compute Precision@5 and MRR with the thirty lines above, commit the baseline, and make the test red when it drops by three points. Everything after that is tuning with a number attached.

## Related posts

- [Azure OpenAI Embeddings in .NET: Semantic Search Without a Vector Database](/posts/azure-openai-embeddings-semantic-search-dotnet/)
- [Enterprise AI: RAG vs Fine-tuning for an Internal Copilot - Cost, Latency, Freshness and Governance](/posts/rag-vs-fine-tuning-enterprise-internal-copilot/)
- [Testing LLM Prompts in .NET: Regression Tests for Azure OpenAI Outputs](/posts/testing-llm-prompts-dotnet/)
