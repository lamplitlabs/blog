---
layout: post
title: "AI SDLC: Spec to PR With Coding Agents, Measured - What to Gate Before and After the Agent"
date: 2026-11-06 15:00:00 +0000
categories: ai
tags: [ai, ai-sdlc, sdlc, agents, code-review, testing, mutation-testing, python, enterprise, benchmark]
author: manishtiwari25
description: "24 coding-agent PRs from 6 tickets: all had green CI and full diff coverage, but 0 of 12 from one-line tickets met the spec and 12 of 12 from full specs did."
image:
  path: /assets/img/headers/ai/ai-sdlc-spec-to-pr-agents-what-to-gate.webp
  alt: "Header for the spec-to-PR agents post: 24 of 24 agent PRs had green CI, 0 of 12 thin-spec PRs were correct, 12 of 12 full-spec PRs were correct, 0 of 12 wrong PRs caught by coverage and mutation, with the gate chain spec lint, agent, own tests, scope, diff coverage, mutation, acceptance tests, human review"
---

The usual way to put a coding agent into the SDLC is "ticket in, pull request out". The usual place to put the gates is after the PR: tests, coverage, maybe mutation testing, then a human. I wanted to know how much those PR gates actually catch when the agent got the ticket wrong, and how much of that comes from the ticket itself.

So I measured it. One agent, one small repository, six tickets, each written two ways. That gave 24 real agent PRs, each run through five gates. Everything below comes from those runs, and the harness is in the repo so you can run it again.

The short version: **every one of the 24 PRs had green CI, 100% diff coverage and a passing mutation score.** All 12 PRs built from one-line tickets were still wrong against the spec the business meant. All 12 built from the full tickets were right. None of the post-PR gates told the two groups apart. The hidden acceptance tests did, and those can only be written from the full spec.

## The setup

The repository is a small invoicing library in Python 3.9, standard library only. It has `Invoice`, `LineItem`, an in-memory `InvoiceStore`, a payment client interface and a log formatter, plus 8 unit tests and an `AGENTS.md` that says how to run them and that money is `Decimal`. I wrote six tickets, each the kind of change a team hands to an agent:

| Ticket | Asks for | Thin | Full |
|---|---|---|---|
| T1 late fee | `late_fee(invoice, today)` | 25 words | 154 words |
| T2 charge retry | `charge_with_retry(...)` on the payment client | 24 | 143 |
| T3 CSV export | `export_csv(invoices)` for finance | 19 | 110 |
| T4 discount | `apply_discount(invoice, percent)` | 14 | 121 |
| T5 charge log | `log_charge(invoice_id, amount, card_number, email)` | 28 | 95 |
| T6 pagination | `InvoiceStore.list(customer, page, page_size)` | 20 | 68 |

The **thin** ticket is what often lands in a backlog: a sentence of intent, the function signature, the file. The **full** ticket adds the rules, the edge cases and errors, a couple of worked examples, and a `Scope:` line naming the files the change may touch. Here is T6 both ways:

```markdown
# T6: Paginate invoice listing                      (thin, 20 words)

Listing all invoices is slow for big customers. Add pagination:
`InvoiceStore.list(customer=None, page=1, page_size=20)` in `invoicing/store.py`.
```

```markdown
# T6: Paginate invoice listing                      (full, 68 words)

Add `InvoiceStore.list(customer=None, page=1, page_size=20) -> List[Invoice]` in
`invoicing/store.py`.

Rules:
- Order: `issued` descending (newest first), then `id` ascending.
- `customer`, when given, filters by case-insensitive exact match on `Invoice.customer`.
- `page` is 1-based; a page past the end returns `[]`.
- `page < 1`, or `page_size` outside `1..100`, raises `InvoicingError`.
- `all()` keeps its current behaviour.

Scope: `invoicing/store.py` and new tests under `tests/`.
```

Each ticket ran twice per variant, so 24 runs. Every run used a fresh copy of the repo with one base commit. The agent was a general-purpose LLM coding agent with file and shell tools, capped at 14 model calls. It got the same fixed prompt every time: read `AGENTS.md` and `TICKET.md`, implement the ticket, add tests, make the suite pass, stay inside the workspace, don't ask questions. Only `TICKET.md` changed between runs. I ran all 12 thin runs before the full tickets existed on disk, and kept the acceptance tests and my reference solution out of the clone while the agents worked.

The agents were quick and sure of themselves. Median 4 model calls and about 30 seconds per run, and every run reported its suite green. Every report also ended with a list of "assumptions where the ticket was silent". That list turns out to matter.

## The gates

Each PR met five gates, in the order a pipeline would run them:

1. **Own tests.** The suite after the agent's change: the 8 base tests plus whatever it added. This is what "CI green" means in most repos today.
2. **Scope.** Only the file the ticket allows changed (for example `invoicing/store.py` for T6), plus new test files. No existing test edited.
3. **Diff coverage of at least 90%.** Share of the added executable lines that the agent's tests run, measured with the standard library's `trace` module.
4. **Mutation score of at least 80%.** An AST mutator on the added lines only flips comparisons (`<` to `<=`, `==` to `!=`), swaps arithmetic operators and `and`/`or`, bumps integer and numeric-string constants, and drops `not`. The gate counts how many of those mutants the agent's own tests kill. Over the 24 PRs that came to 327 mutants.
5. **Acceptance.** 45 hidden tests across the six tickets, 6 to 9 each, written from the full ticket's rules and examples and checked against my reference solution first. The agent never sees them.

Gates 1 to 4 check the PR against **itself**: do the agent's tests pass, do they run the new lines, would they notice a changed line. Only gate 5 checks it against **what was asked**.

## Every PR against every gate

![Matrix of 24 agent pull requests against five gates. Top half, 12 runs from thin tickets: every run passes its own tests, scope, diff coverage 96 to 100 percent and mutation 82 to 100 percent, but every acceptance cell is red, from 3 of 6 to 8 of 9 hidden tests passed. Bottom half, 12 runs from full tickets: every gate passes, acceptance 6 of 6 to 9 of 9.](/assets/img/posts/ai/ai-sdlc-spec-to-pr-agents-what-to-gate-matrix.webp)

The top half is the thin tickets, the bottom half the full ones. The first four columns are the same in both halves: everything passes. Diff coverage is 100% in 23 of 24 runs. The one miss is an `unreachable` line after a retry loop. The median mutation score is 93% for thin PRs and 100% for full ones, and the lowest thin PR still clears the 80% bar at 82%. Only the acceptance column differs, and there it is total: 0 of 12 thin PRs pass all their acceptance tests, against 12 of 12 full ones.

Here is the raw gate output for all 24 workspaces. This is the data behind the matrix, not a mock-up:

![Terminal output of run_gates.py over 24 workspaces, one line per run with own=True, scope=True, coverage percent, mutation score with killed over total mutants and acceptance passed over total; the thin runs whose acceptance is below the total are highlighted, for example T3-csv-export.thin.r1 acc=3/6 and T6-pagination.thin.r2 acc=4/7, while every full run shows all acceptance tests passing.](/assets/img/posts/ai/ai-sdlc-spec-to-pr-agents-what-to-gate-gates-terminal.webp)

## What "wrong" looked like

None of the thin PRs were sloppy. They were careful, well-tested code that answered a different question:

- **T3 CSV export.** Both runs used the `csv` module's default CRLF line endings and kept the invoices in input order. Finance wanted LF and rows sorted by date. Both runs added a spreadsheet formula-injection guard nobody asked for, and it was a good call.
- **T6 pagination.** Both runs returned invoices in insertion order, matched the customer case-sensitively, and had no upper limit on `page_size`. All three are defensible. None is what the full spec says.
- **T1 late fee.** Both runs used calendar months rather than 30-day periods, and neither capped the fee. So a five-year-old invoice gets a 90% late fee instead of 10%.
- **T4 discount.** One run returned a new `DiscountedInvoice` type instead of an `Invoice`, and rounded on totals instead of per line, giving 27.59 where the spec's example says 27.60. The other run accepted `float` percentages in money code.
- **T5 charge log.** Here the agents did better than the ticket. The thin ticket never says "don't log the card number". Both runs masked it to the last four digits on their own, citing PCI DSS. They still logged a masked email (`j***@example.com`) rather than just the domain, and never rejected a short card number.
- **T2 charge retry.** This was the closest. Both runs retried only `TransientError`, kept the idempotency key, and used the exact 0.5/1/2 s backoff the full spec later named. They missed one test because they raised `ValueError` instead of the domain's `InvoicingError` for `max_attempts < 1`.

![Bar chart per ticket of hidden acceptance tests passed over both runs, orange for the thin ticket and green for the full ticket: T1 late fee 10 of 16 against 16 of 16, T2 charge retry 16 of 18 against 18 of 18, T3 CSV export 6 of 12 against 12 of 12, T4 discount 9 of 16 against 16 of 16, T5 charge log 9 of 14 against 14 of 14, T6 pagination 8 of 14 against 14 of 14; thin total 58 of 90 (64 percent), with the median mutation score per ticket alongside.](/assets/img/posts/ai/ai-sdlc-spec-to-pr-agents-what-to-gate-per-ticket.webp)

Two things in the chart are easy to miss. First, the misses repeat. Of the 19 distinct acceptance tests the thin PRs failed, 13 were failed by **both** runs of the same ticket. Running the agent again does not fix an under-specified ticket; you get the same plausible guess twice. Second, the mutation scores on the right look the same for wrong and right PRs. A mutation score measures whether the tests pin down the code. It cannot tell whether the code does the right thing, and a confident agent writes tests that pin down its own assumptions very well.

## The gate that helped most was the PR description

I went through each thin run's final report and matched every failed acceptance test to what the agent had said. **29 of the 32 failures were stated in plain words in the agent's own "assumptions" list**: "CRLF line endings, the RFC 4180 default", "customer must match exactly (case-sensitive)", "There is no upper limit on page_size", "No errors raised". The three it did not mention were the T1 fee cap (both runs) and one run's silence on a `today` before the issue date.

That changes what the human reviewer should read. A 140-line diff with 15 green tests invites a skim. A list of seven assumptions invites "no, sort by date". So that list should be a required, structured part of every agent PR, and the reviewer should check it against the ticket before looking at the diff. It costs nothing: the agents wrote it without being asked to.

## Gate the spec before the agent

If the PR gates can't catch a wrong reading of the ticket, the cheapest place to catch it is the ticket. I wrote a deliberately crude spec lint. It needs at least two concrete examples, something about bad or empty input, a `Scope:` line, and at least three bullet rules:

![Terminal output of spec_lint.py over the 12 ticket files: all six thin tickets fail every rule (S1 fewer than 2 concrete examples, S2 nothing on bad or empty input, S3 no Scope line, S4 fewer than 3 bullet rules); four full tickets pass and two full tickets, T2 charge retry and T6 pagination, fail only S1 for lacking concrete examples; 4 of 12 tickets ready for an agent, exit status 1.](/assets/img/posts/ai/ai-sdlc-spec-to-pr-agents-what-to-gate-spec-lint.webp)

It blocks all six thin tickets, and it fires before anyone spends an agent run or a review on them. It also blocks two full tickets, T2 and T6, for having no worked examples, even though both produced correct PRs. That is a false positive I'd keep. Examples are what you turn into acceptance tests, and a ticket without them leaves the acceptance gate to the reviewer's memory. My first version was even stricter. It counted only `->` as an example and only "raises" as error handling, and it failed four of the six full tickets on wording alone. A spec lint is a nudge to write the missing rule, not a proof that the spec is right.

## What I would gate, in order

| Stage | Gate | Blocks | What it caught here |
|---|---|---|---|
| Before the agent | **Spec lint**: examples, edge cases, scope, rules | Ticket goes back to its author | All 6 thin tickets (plus 2 full tickets with no examples) |
| Before the agent | **Acceptance tests written from the spec**, by the ticket author, kept out of the agent's workspace | Nothing yet; it is the test for later | Built the gate that caught all 12 wrong PRs |
| PR | Own tests, scope allow-list, diff coverage | PR | 0 of 12 wrong PRs; still worth running, they catch other things |
| PR | Mutation score on changed lines | PR | 0 of 12 wrong PRs; catches weak tests, not wrong intent |
| PR | **Hidden acceptance tests** | PR | 12 of 12 wrong PRs, 0 correct PRs blocked |
| Review | **Assumptions list** in the PR description, read against the ticket first | Human | 29 of 32 failures named by the agent itself |

The gates after the PR are still worth having. In our [Go code review gates measurements]({% post_url AI/2026-11-06-ai-sdlc-ai-code-review-gates-ci-go-measured %}), the same kind of pipeline blocked 19 of 26 seeded defects, and our [mutation testing post]({% post_url AI/2026-10-01-llm-test-generation-mutation-testing-dotnet %}) shows mutation scores catching agent-written tests that prove nothing. Those are defects in *how* the code was written. This experiment is about *what* was written, and that is decided before the agent starts. The [AGENTS.md post]({% post_url AI/2026-10-18-ai-sdlc-agents-md-instruction-files-coding-agents-actually-follow %}) makes the same point about repository rules: an agent follows what is written down very well and guesses the rest. And the [merge gate post]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}) is where the scope and mutation gates come from.

All five gates together took a median of 0.8 s per PR on an M2 Pro, and the mutation gate was 0.6 s of that. Gate speed is not the cost. The cost is the 50 to 130 extra words per ticket, and having somebody who knows the business write the acceptance examples.

## One thing that went wrong while measuring

My first run of the mutation gate got several mutants wrong. In one PR, four mutants the tests actually killed were counted as survivors. The mutant runner rewrote the module and ran the suite in the same second. A mutant like `==` to `!=` has the same byte size as the original, and CPython's bytecode cache validates on (mtime in whole seconds, size). So the "mutant" run quietly imported the cached original. Running mutants with `python -B` and deleting `__pycache__` before each one fixed it. One PR went from failing the mutation gate (74%) to passing (95%). If you build your own mutation gate, check that a known-bad mutant fails your suite before trusting any score.

## Limits

- Six tickets, two runs each, one agent and one small Python library. The direction is clear (0 of 12 against 12 of 12), but the exact percentages are not a general rate.
- I wrote the tickets, the hidden tests and the reference solution, and the full tickets are what the hidden tests check. That is the point: the acceptance gate can only be as good as the spec it comes from. But it does mean the full tickets were never ambiguous against their own tests.
- Several thin-ticket choices (CRLF, input order, insertion-order pagination) are not bugs in general. They are bugs against what the business wanted, which is exactly what a thin ticket does not tell the agent.

*We run agents this way on the work behind Lamplit Labs' products: a ticket that passes a lint, acceptance checks the agent cannot see, and a reviewer who reads the agent's assumptions first. Turning a goal into checked tasks and measuring each change against a baseline before it lands is also the core of [**Pulse**]({% post_url AI/2026-10-25-pulse-internal-rsi-tool %}), Lamplit Labs' self-improving automation product, coming soon.*

## Reproduce it

```bash
# Python 3.9+, standard library only; Pillow only for the images.
# Replays the 24 recorded agent changes (scripts/spec-to-pr/patches/) into fresh workspaces:
python3 scripts/spec-to-pr/setup_runs.py --out .tmp/spec-to-pr-runs --apply-patches
python3 scripts/spec-to-pr/run_gates.py --runs .tmp/spec-to-pr-runs --out .tmp/gates-raw.json | tee .tmp/gates-term.txt
python3 scripts/spec-to-pr/summarise.py --raw .tmp/gates-raw.json      # -> scripts/data/spec-to-pr-agents.json
python3 scripts/spec-to-pr/spec_lint.py scripts/spec-to-pr/specs/*.md
python3 scripts/spec-to-pr/gen_images.py --gates-term .tmp/gates-term.txt
```

To run your own agent instead of replaying ours, drop `--apply-patches`, give `scripts/spec-to-pr/agent_prompt.txt` to your agent once per workspace, and hide `acceptance/` and `reference/` from it while it works. The gate run over 24 workspaces takes about 20 seconds. Rerunning it on the same patches gives the same verdicts, mutant for mutant.
