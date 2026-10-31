---
layout: post
title: "Enterprise AI: surviving Azure OpenAI model retirements without a weekend of firefighting"
date: 2026-10-14 05:30:00 +0200
categories: ai enterprise-ai
tags: ai azure openai enterprise enterprise-ai governance architecture dotnet evaluation apim
description: "Azure OpenAI versions retire and auto-upgrade. How we inventory deployments, pin versions in Bicep, gate upgrades on a golden eval set and canary via APIM."
image:
  path: /assets/img/headers/ai/enterprise-ai-azure-openai-model-retirement-upgrade-gate.webp
  alt: "Header card titled 'Surviving Azure OpenAI model retirements' with four steps: Inventory (11 deployments, 3 on a model retiring in 38 days), Pin (upgrade policy NoAutoUpgrade on all prod), Eval gate (312-case golden set, old vs new version, pass at least 98 percent), Canary (APIM 5 to 50 to 100 percent behind one header). Footer: 0 silent regressions over two retirement cycles, 1 upgrade held back by the gate."
---

Azure OpenAI model versions have a shelf life. Every version gets a retirement date, and a deployment left on its default upgrade policy will switch to the new version on that date whether or not anyone is in the room. We learned this the way most teams do: a ticket summariser started returning slightly different JSON on a Tuesday, nobody had deployed anything, and it took half a day to notice the model version in the response headers had changed.

This post is what we do now instead. It is three small pieces - an inventory script, an eval gate and a canary - and it has carried us through two retirement cycles with zero silent regressions. It follows on from our [governance](/posts/enterprise-ai-governance-azure-openai/) and [prompt testing](/posts/testing-llm-prompts-dotnet/) posts; if you already have a golden set from the second one, you are most of the way there.

## Step 1: know what you are running

The first problem is that nobody could answer "which deployments are affected?" from memory. Across four accounts and two regions we had eleven deployments, and the version and upgrade policy for each lived only in the portal.

`aoai-inventory.sh` walks every Azure OpenAI account in a subscription with `az cognitiveservices account deployment list`, joins the result against the published retirement dates, and prints one row per deployment. It exits non-zero when any production deployment either auto-upgrades or retires inside sixty days, so it runs in a nightly pipeline and pages the on-call channel instead of being something somebody remembers to look at.

![Terminal running aoai-inventory.sh against the prod-eu subscription. A table lists 11 deployments across four Azure OpenAI accounts with columns for account, deployment, model, version, upgrade policy, retirement date and days remaining. Three rows are highlighted in red because they use the OnceNewDefaultVersion policy and retire in 38 days: chat-legacy and summarise-tickets on gpt-4 turbo-2024 and classify-emails on gpt-35-turbo 0125. A summary reports 3 production deployments retiring in under 45 days, 3 with an auto-upgrade policy, and a version mismatch for chat-default between prod and dev. The script exits with code 2.](/assets/img/posts/ai/azure-openai-deployment-inventory-retirement-dates.webp){: width="1400" height="900" }

The first run was the uncomfortable one. Three production deployments were on `OnceNewDefaultVersion`, which means Azure would have moved them to whatever the new default was on the retirement date. One of them was the ticket summariser from the Tuesday incident; we had fixed the prompt but never the policy.

The other finding we did not expect: `chat-default` ran a different model version in dev than in prod. Every "works on my machine" prompt complaint for the previous month suddenly had an explanation.

## Step 2: pin everything in production

The policy change itself is one line per deployment, and we put it in the Bicep so it cannot drift back:

```bicep
resource chatDefault 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: account
  name: 'chat-default'
  sku: { name: 'GlobalStandard', capacity: 150 }
  properties: {
    model: { format: 'OpenAI', name: 'gpt-4o', version: '2024-08-06' }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}
```

`NoAutoUpgrade` means the deployment stops working on the retirement date rather than silently changing behaviour. That sounds worse, and for a hobby project it is. For a system that produces invoices it is the right default: a loud failure with a known date beats a quiet one with no date. The inventory script's sixty-day window exists precisely so the loud failure never actually happens.

We also added an Azure Policy audit rule for `versionUpgradeOption != 'NoAutoUpgrade'` on anything tagged `env=prod`, using the same pattern as our [governance-as-code post](/posts/enterprise-ai-azure-policy-governance-as-code-azure-openai/). The Bicep stops it drifting from our side; the policy catches anyone clicking in the portal.

## Step 3: gate the upgrade on your own data

Pinning only moves the problem: now somebody has to do the upgrade on purpose. The question is whether the new version behaves the same on *our* prompts, and the only honest answer comes from running both versions over the same cases and comparing.

`ModelUpgradeGate` is a small .NET console that takes a baseline version, a candidate version and a JSONL file of cases. Each case has a prompt, an expected result and a scorer: exact match for classification, JSON Schema validation for structured output, and an LLM judge with a rubric for summaries. It runs each case against both versions at temperature 0 with a fixed seed, in parallel, and prints a per-suite pass rate with the gate threshold.

```csharp
var results = await Parallel.ForEachAsync(cases, new ParallelOptions { MaxDegreeOfParallelism = 8 },
    async (c, ct) =>
    {
        var baseline  = await Run(c, opts.Baseline, ct);
        var candidate = await Run(c, opts.Candidate, ct);
        return new CaseResult(c.Id, c.Suite,
            Score(c, baseline), Score(c, candidate),
            baseline.Usage, candidate.Usage, baseline.Latency, candidate.Latency);
    });

foreach (var suite in results.GroupBy(r => r.Suite))
{
    var passRate = suite.Average(r => r.CandidateScore);
    var verdict  = passRate >= opts.Gate ? "PASS" : "FAIL";
    Console.WriteLine($"{suite.Key,-22}{suite.Count(),5}  {passRate:P1}  {verdict}");
}
```

The gate is 98 % per suite, not overall. An overall number would let a big suite hide a small one, and it was the small one that mattered:

![Terminal running the ModelUpgradeGate tool comparing gpt-4o version 2024-08-06 against 2024-11-20 on a 312-case golden set. Three suites pass: extract-invoices 99.0 percent, summarise-tickets 96.3 percent judge-scored, classify-emails 100 percent. The chat-default-schema suite fails at 93.8 percent, down 6.2 points, with four failing cases listed: two where the candidate returned the total as a string with a thousands separator instead of a number, and two where it added a currency_symbol field not permitted by the schema. A cost and latency table shows the candidate using 11.7 percent more output tokens but 22 percent lower p50 and 27 percent lower p95 latency at 16 percent lower cost. Verdict: BLOCKED, chat-default stays pinned to 2024-08-06, ticket AI-412 opened.](/assets/img/posts/ai/azure-openai-model-upgrade-eval-gate-report.webp){: width="1400" height="900" }

The candidate was faster and cheaper and three of four suites got better. It also started formatting currency totals as `"1,240.00"` strings in a schema that says `number`, and added a `currency_symbol` field the schema does not allow. In a chat window nobody would notice. In the pipeline that writes those totals into a ledger it would have been a rounding of exactly 100 % of every invoice over a thousand.

The fix was a sentence in the system prompt and switching that call to [strict structured outputs](/posts/structured-outputs-azure-openai-dotnet/), which makes the schema a constraint rather than a suggestion. With that change the suite went to 100 % and the upgrade went through a week later. The point is not that the new version was bad; it is that *we* found out, on our data, before customers did.

## Step 4: canary behind the gateway

Passing the gate earns the candidate a canary, not a cutover. Because all traffic already goes through API Management (see the [model routing post](/posts/enterprise-ai-model-routing-azure-openai-apim/)), the canary is a policy fragment that rewrites the deployment name for a percentage of calls and stamps the version it chose into a response header:

```xml
<choose>
  <when condition="@(new Random().Next(100) < int.Parse(context.Variables["canaryPercent"]))">
    <rewrite-uri template="/openai/deployments/chat-default-v2/chat/completions" />
    <set-variable name="servedVersion" value="2024-11-20" />
  </when>
  <otherwise>
    <set-variable name="servedVersion" value="2024-08-06" />
  </otherwise>
</choose>
<set-header name="x-model-version" exists-action="override">
  <value>@((string)context.Variables["servedVersion"])</value>
</set-header>
```

`canaryPercent` is a named value, so moving from 5 to 50 to 100 is a change in APIM with no deploy. The header lands in our OpenTelemetry spans, which means the dashboards from the [observability post](/posts/enterprise-llm-observability-opentelemetry-dotnet/) can split error rate, latency and schema-validation failures by model version for free. We hold each step for a working day.

## What it costs and what it bought

The whole thing is about 400 lines: a shell script, a console app, a Bicep property and an APIM fragment. Running the 312-case gate costs a few dollars and four minutes. Per deployment, an upgrade now takes an engineer about 23 minutes of attention spread across a week, most of it reading the failure list.

Over two retirement cycles and eleven deployments: zero regressions reached production, one upgrade was blocked by the gate for a real schema defect, and the version mismatch between dev and prod is gone because the inventory script fails the build when it comes back. The Tuesday incident has not recurred, which is the only metric the ticket summariser's users care about.

If you have one Azure OpenAI deployment, pin it and put the retirement date in your calendar. If you have more than three, write the inventory script this week; the first run will tell you something you did not know.

## Related posts

- [Enterprise AI: Multi-Region Failover for Azure OpenAI with APIM Backend Pools and Circuit Breakers](/posts/enterprise-ai-azure-openai-multi-region-failover-apim/)
- [Enterprise AI: Model Routing for Azure OpenAI - Cheap Model First, Escalate Only When Needed](/posts/enterprise-ai-model-routing-azure-openai-apim/)
