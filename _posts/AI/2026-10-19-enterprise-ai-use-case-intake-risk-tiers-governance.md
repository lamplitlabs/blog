---
layout: post
title: "Enterprise AI: A Use-Case Intake Form and Three Risk Tiers So Governance Scales With Risk, Not Headcount"
date: 2026-10-19 16:00:00 +0530
categories: ai enterprise-ai
tags: ai enterprise-ai governance risk-tiers intake compliance azure-openai llm
description: "A 12-question intake form scores each LLM use case into one of three risk tiers with a fixed control list, so a chatbot is not reviewed like a loan decision."
image:
  path: /assets/img/headers/ai/enterprise-ai-use-case-intake-risk-tiers.webp
  alt: "Header card reading Enterprise AI: Use-Case Intake and Risk Tiers, with three tier cards - Tier 1 internal no personal data, Tier 2 customer-facing or personal data, Tier 3 legal or financial effect"
---

After the [shadow-AI inventory](/posts/enterprise-ai-shadow-ai-llm-usage-register-governance/) we had a register of 44 governed LLM use cases and a problem we had created ourselves: every new request went through the same review. A team wanting an internal meeting summariser waited the same fifteen days as a team wanting to let a model draft collections letters. The review board became the bottleneck, teams learned to describe everything as "an internal pilot", and the [six governance controls](/posts/enterprise-ai-governance-azure-openai/) were applied either to everything (slow) or to nothing (unsafe).

This post is the fix: a short intake form, a scoring rule that puts each use case into one of three tiers, and a fixed control list per tier. The design goal is that the tier is **computed, not negotiated**, and that Tier 1 needs no human approval at all.

![Flow from intake form to auto-score to tier controls to review to register entry, with a scoring table (personal data +3, external users +2, no human in the loop +3, legal or financial effect +4, new RAG data source +1) and tier thresholds 0-2, 3-6, 7 or more](/assets/img/posts/ai/enterprise-ai-use-case-intake-risk-tier-flow.webp)
_The intake pipeline. The scoring table is an excerpt; the real file has twelve questions._

## Why one review queue fails

Three things went wrong with a single queue:

1. **Latency was uniform.** The median time from request to approval was 15 working days whatever the risk. Low-risk teams routed around it; the usage register started drifting again within a quarter.
2. **Reviewers were reading the wrong things.** Board time went to arguing about whether a summariser needed content filtering, while the one use case that produced customer-facing financial figures got the same 30-minute slot.
3. **"Risk" was an opinion.** The requester said low, the reviewer said high, and the outcome depended on who was in the meeting.

A tiering scheme fixes the first two only if it fixes the third. So the form had to be answerable by the requesting team without a risk specialist, and the score had to come out of a file in git.

## The intake form: twelve questions, no free text that matters

The form is a YAML file the team commits next to their use case entry in the register repo. Free text is allowed for context but never scored. The scored questions are all closed:

```yaml
# usecases/collections-letter-drafts/intake.yaml
use_case: collections-letter-drafts
owner: finance-ops@contoso.example
model: gpt-4o                       # from the approved model list
questions:
  personal_data_in_prompt_or_output: yes      # +3
  users: external                             # internal 0 / partner +1 / external +2
  output_acted_on_without_human: no           # +3 if yes
  legal_financial_or_safety_effect: yes       # +4, and forces tier 3
  new_rag_data_source: no                     # +1
  writes_to_system_of_record: no              # +2
  prompt_contains_credentials_or_secrets: no  # +4, forces tier 3
  model_outside_approved_list: no             # +2
  cross_border_data_flow: no                  # +2, see residency checklist
  user_can_see_raw_model_output: yes          # +1
  fine_tuning_on_company_data: no             # +2
  expected_calls_per_day: 2000                # +1 above 10k
```

The scorer is ~40 lines in the register repo's CI. It writes `tier:` back into the register entry and fails the pull request if the tier field was edited by hand. That last rule mattered more than the scoring itself.

```yaml
scoring:
  thresholds: { tier1: 0, tier2: 3, tier3: 7 }
  force_tier3_if_any:
    - legal_financial_or_safety_effect
    - prompt_contains_credentials_or_secrets
```

The example above scores 3 + 2 + 4 + 1 = 10 and is forced to Tier 3 anyway by the legal-effect answer. A meeting summariser for internal staff with no personal data scores 1 (users can see raw output) and lands in Tier 1.

## What each tier has to do

The control list per tier is fixed and published. A team can read it before filling the form and know what they are signing up for. The six Azure OpenAI controls from the [earlier post](/posts/enterprise-ai-governance-azure-openai/) are all in here; the tiers decide which apply.

| Control | Tier 1 | Tier 2 | Tier 3 |
|---|:-:|:-:|:-:|
| Calls go through the APIM gateway, Entra ID only | yes | yes | yes |
| Register entry with owner and review date | yes | yes | yes |
| Content safety profile per use case | - | yes | yes |
| Prompt and completion logging to your own store ([audit trail](/posts/enterprise-ai-audit-trail-azure-openai-apim/)) | - | yes | yes |
| Data residency confirmed against the [checklist](/posts/enterprise-ai-azure-openai-data-residency-compliance-checklist/) | - | yes | yes |
| Golden-set eval with a pass threshold before go-live | - | yes | yes |
| Human review of every output with legal effect | - | - | yes |
| [Canary and automatic rollback](/posts/enterprise-ai-canary-rollout-llm-model-prompt-rollback/) for model or prompt changes | - | - | yes |
| Quarterly re-score and risk-board sign-off | - | - | yes |

Two controls everywhere, six for Tier 2, nine for Tier 3. The approval path follows the tier:

- **Tier 1** - the CI check passing *is* the approval. Nobody reads it unless an audit samples it.
- **Tier 2** - the platform team reviews the evidence links in the PR. Target five working days; mostly it is one.
- **Tier 3** - risk board, 15 working days, and the board now only sees Tier 3 cases.

## Evidence, not promises

Each control in the table is a checkbox in the register entry with a required link: the APIM product id, the Log Analytics workspace, the eval run, the residency ticket. The CI check verifies that the link resolves and, for the ones it can, that the thing behind it exists (an APIM product with the right policy, an eval run above threshold). The reviewer's job becomes reading evidence rather than interviewing the team.

```yaml
controls:
  gateway: { done: true, evidence: apim://contoso-ai/products/collections-letters }
  content_safety: { done: true, evidence: https://portal.azure.com/#@.../contentSafetyProfiles/strict-finance }
  golden_eval: { done: true, evidence: evals/collections-letters/2026-10-12.json, score: 0.93, threshold: 0.90 }
  human_review: { done: true, evidence: https://wiki.contoso.example/finance-ops/letter-review-sop }
```

## What changed after one quarter

| Measure | Single queue | Tiered intake |
|---|---|---|
| Median request-to-approval, all cases | 15 working days | 2 working days |
| Median for Tier 1 (62% of requests) | 15 | 0 (CI pass) |
| Median for Tier 3 (11% of requests) | 15 | 12 |
| Risk-board agenda items per month | 14 | 4 |
| Use cases found outside the register at re-scan | 9 | 2 |
| Tier disputes escalated | n/a | 3 (all led to a rule change, not an exception) |

The last row is the one to watch. When a team disagrees with its tier, the answer is a pull request against `scoring.yaml`, reviewed by the risk board, applied to everyone. Three rule changes in a quarter is healthy; thirty would mean the questions are wrong.

## What we got wrong first

- **Too many questions.** Version one had 31. Teams guessed at the ones they did not understand, and guessing is noise in the score. Twelve closed questions that any product owner can answer is the right size.
- **A single "sensitive data" question.** It conflated personal data, secrets and commercial confidentiality. Splitting it (and making secrets a forced Tier 3) removed most of the disputes.
- **No re-scoring trigger.** A use case tiered at 1 quietly added a RAG index over HR documents. Now any change to `intake.yaml` or the model re-runs the score, and Tier 3 entries re-score quarterly regardless.
- **Treating tiers as permanent.** A control that is demonstrably automated for every Tier 2 case (content safety via a shared APIM policy) can move down to "yes" for Tier 1 for free. The table should get cheaper over time, not heavier.

## Checklist

1. Write the control table first, three columns, and get the risk board to agree it in one sitting.
2. Write the twelve questions so that the requesting team can answer them without help.
3. Put scoring in a file in git with CI that computes the tier and rejects hand-edited tiers.
4. Make Tier 1 approval fully automatic; if it is not, teams will route around you again.
5. Require evidence links per control and verify the ones you can verify.
6. Re-score on any change and quarterly for Tier 3; publish dispute outcomes as rule changes.

## Related posts

- [Enterprise AI: Governing LLM Usage - A Shadow-AI Inventory and a Usage Register in 30 Days](/posts/enterprise-ai-shadow-ai-llm-usage-register-governance/)
- [Enterprise AI: Six Governance Controls Before Azure OpenAI Goes to Production in a Regulated Org](/posts/enterprise-ai-governance-azure-openai/)
- [Enterprise AI: Canary Deploys and Automatic Rollback for LLM Model Versions and Prompt Changes](/posts/enterprise-ai-canary-rollout-llm-model-prompt-rollback/)
