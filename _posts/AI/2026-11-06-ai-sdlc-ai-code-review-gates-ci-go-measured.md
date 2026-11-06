---
layout: post
title: "AI Code Review Gates in CI, Measured: 26 Seeded Agent Defects Against a Go Pipeline"
date: 2026-11-06 09:00:00 +0100
categories: ai
tags: [ai, ai-sdlc, sdlc, code-review, go, ci, testing, security, enterprise, benchmark]
author: manishtiwari25
description: "26 agent-style defects and 8 correct changes run through 8 blocking CI gates on a Go service: 19 blocked, 7 got through, 1 correct PR blocked, 3.2 s per PR."
image:
  path: /assets/img/headers/ai/ai-sdlc-ai-code-review-gates-ci-go-measured.webp
  alt: "Header graphic for the AI code review gates post: 19 of 26 seeded agent defects blocked, 7 of 26 got past every blocking gate, 1 of 8 correct pull requests blocked, 3.2 seconds for all gates per pull request, above the ten gates in CI order from go vet to review hints. Apple M2 Pro, go1.27.2, gitleaks 8.30.1."
---

Most teams that let coding agents open pull requests already have a CI pipeline. The usual question is which gates to add before an agent PR can merge without a human reading every line. The usual answers are opinions: "turn on the race detector", "add a secret scanner", "require coverage on the diff". I wanted numbers, so I measured the gates.

I took one small Go service, wrote **26 agent-style defects** and **8 correct changes** as patches against it, and ran every patch through ten CI gates: eight that can block a merge and two that only leave a note for the reviewer. Every gate is a real tool or a short script in this blog's repository (`scripts/ai-review-gates/`), and one command reproduces the whole table.

The results:

- The eight blocking gates stopped **19 of 26** defects. **7 got through.** All seven compile, pass every test and pass every analyzer.
- **No single gate is enough.** Eight of the 19 blocked defects were caught by exactly one gate. Drop that gate and they merge.
- **The race detector added no new catches** over plain `go test`, at **3x the time** (1.65 s against 0.54 s per PR). What it did add was certainty: plain `go test` caught the two race defects on only 2 and 3 of 5 runs, and `-race` caught them on every run. Each gate was timed on its own, as CI would run it.
- The test-integrity rules caught two defects nothing else saw, but they also **blocked 1 of the 8 correct PRs** (a test refactor).
- All ten gates together cost a median **3.2 s per PR** on an M2 Pro. CI time is not a reason to skip any of them.

## The service and the seeded PRs

The base tree is a token-budget service for an LLM gateway, 282 lines of Go: a `Ledger` that charges tokens per tenant behind a mutex, a generic `Page` helper, config loading, a tenant store interface, an upstream HTTP client and one handler. It has 18 tests. The base tree passes every gate. The runner checks this before it counts anything.

Each seeded PR is a list of exact text edits in `corpus.py`. I modelled the 26 defects on the seven classes from our [review checklist of AI-generated code defects]({% post_url AI/2026-10-19-ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist %}), with the same kind of plausible mistake an agent makes when it is told to "make CI green" or "handle errors gracefully":

| Class | PRs | Example |
|---|---|---|
| Silent error fallback | D01-D04 | `DisplayName` returns `"tenant <id>"` instead of the store error |
| Boundary / off-by-one | D05-D08 | `>` became `>=` in the budget check |
| Tests that prove nothing | D09-D12 | the code broke and the test's expected value moved to match |
| Hallucinated API / argument order | D13-D14 | `time.ParseDurationStrict`, which does not exist |
| Duplicated helper | D15 | a second pagination helper with different end-of-list behaviour |
| Concurrency and resources | D16-D21 | `ok++` without the mutex, a lock released between check and write |
| Security | D22-D26 | SQL built by concatenation, `InsecureSkipVerify: true`, a key in the code |

The eight correct changes (B01-B08) are the everyday edits an agent also makes: a rename, a new test case, `min()` in place of an `if`, a new method with its test, an intended default change with its test update, a table-test refactor, an extra log line, `errors.New` in place of an argument-free `fmt.Errorf`. A gate that blocks these costs review time on every PR, so false positives count as much as catches.

To be clear about the limits: I wrote these patches by hand. They are not sampled from a model, and 26 defects is a small sample. The point is not a catch rate you can quote for your codebase. The point is which gate catches which kind of defect, and which kinds no gate catches.

## The gates

The eight blocking gates run in CI order. Each one runs on a fresh copy of the patched tree:

1. **`go vet`** with the default analyzers. It also fails if the tree does not compile.
2. **`go test`**: the service's own tests.
3. **`go test -race`**: the same tests under the race detector.
4. **Diff coverage**: `go test -coverprofile`, then the gate fails if any added non-test line sits in a block that no test ran.
5. **Extra analyzers**: `nilness`, `shadow` and `unusedwrite` from `golang.org/x/tools`. `go vet` does not run these by default. They are built into one `-vettool` binary.
6. **Policy rules P1-P4**: four house rules written as a `go/analysis` analyzer in 140 lines. They flag `InsecureSkipVerify: true`, a SQL string literal concatenated with a non-constant value, an `Authorization`/`Cookie`/`X-Api-Key` header value passed to a logger, and `json.NewDecoder(r.Body)` on an `*http.Request` without `http.MaxBytesReader`.
7. **gitleaks 8.30.1** on the added lines only, through `gitleaks stdin`.
8. **Test integrity**: the Go version of the rules from our [test-integrity gate post]({% post_url AI/2026-10-20-ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules %}). The gate blocks when a test function disappears (T01), a `t.Skip` is added (T02), or a test loses `t.Fatal`/`t.Error` calls (T03).

The two advisory gates never block a merge. They leave notes for the reviewer, who can be a human or a review agent:

- **Expected moved (T05)**: a comparison literal in a test changed in the same PR as production code.
- **Review hints H1-H4**: four diff-only patterns. A net error return removed from non-test code (H1). Lock calls added or removed (H2). A `defer ... Close()` moved (H3). A comparison flipped between `<` and `<=`, or `>` and `>=` (H4).

I would have added staticcheck too, but the newest staticcheck in my module cache was built against an `x/tools` that cannot read go1.27 export data. Every package failed with `export data version 5 is greater than maximum supported version 4`. If you pin your Go toolchain ahead of your linters, this is the failure you get. It is worth a CI step that runs the linter on an empty package and fails loudly.

## Every PR against every gate

![Matrix of 34 seeded pull requests (rows D01 to D26 and B01 to B08) against ten CI gates (columns go vet, go test, go test -race, diff coverage, x/tools analyzers, policy P1-P4, gitleaks, test integrity, expected moved, review hints) with each gate's median time per PR. Red cells mark a blocking failure and amber cells an advisory flag. D16 and D17 show 2/5 and 3/5 in the go test column because their races only sometimes lose an increment. The verdict column shows 19 defects blocked, 7 flagged only, B04 and B05 flagged, B06 blocked, and the other correct changes passing.](/assets/img/posts/ai/ai-sdlc-review-gates-matrix.webp)

Read it one column at a time:

**`go vet` caught 5, two of them alone.** D18 gave `Remaining` a value receiver, so every call copies the `sync.Mutex`. D19 dropped the `cancel` from `context.WithTimeout`. No test noticed either one, because both bugs only matter under load. `vet` also caught D14 (`fmt.Errorf("%w", ErrOverBudget, tenant)` with the arguments swapped) and D17 (`wg.Add` inside the goroutine), and both of those also failed `go test`. D14 failed it because `go test` runs a small subset of vet (including `printf`) before the tests, and D17 because the lost `wg.Add` lets `SpendAll` return early (on 3 of 5 runs). D13's hallucinated `time.ParseDurationStrict` fails at compile time, so every gate that builds the tree failed it. That matches the checklist post: hallucinated APIs cost review time, not incidents.

**`go test` caught 9.** The three boundary defects in Go code (D05-D07) failed it, and so did D01 and D04, where an error became a default value. These are the defects a good existing suite stops, because it tests the edges: the exact-limit spend, the last page, page 1. The fourth boundary defect, D08, is inside a SQL string, and no test runs that query.

**`go test -race` caught 9, the same 9 as `go test`.** In this corpus the race detector added no new defect. The two race defects (D16, unlocked `ok++`, and D17, `wg.Add` in the goroutine) make `TestSpendAll` count fewer than 50 successes on some runs, so plain `go test` already catches them sometimes. The race detector made that failure certain on every run, where plain `go test` caught D16 on 2 of 5 runs and D17 on 3 of 5. So the race detector's real value here was a reliable verdict. Under a flaky verdict, an agent that retries CI until it goes green merges the race.

**Diff coverage caught 3, one alone.** D15 is the duplicated pagination helper. Nothing calls it and no test covers it, so 13 added lines never run. That is the only signal any gate gave about a duplicated helper. Diff coverage also hit D24 and D25, because the new log call and the new TLS client were never run by a test either.

**The extra analyzers caught nothing that was not already caught.** `nilness`, `shadow` and `unusedwrite` only failed on D13, which does not compile, so the failure is the compile error and not an analyzer finding. None of the 26 defects is a nil dereference or a shadowed `err`, so this is a fact about the corpus, not about the analyzers. I kept the gate because it costs 0.16 s.

**The policy rules caught 4 security defects, two alone** (the fifth hit in the column is D13's compile error). These four rules did most of the security work. D22 (SQL concatenation) and D26 (body size limit removed) were seen by no other gate. D24 (the `Authorization` header in a `slog.Warn`) and D25 (`InsecureSkipVerify`) were also caught by diff coverage, but only by luck: if the agent had added a test that exercised the new code, coverage would pass and the policy rule would still fire.

**gitleaks caught the hard-coded key (D23)**, and nothing else did, as expected. It also made no false positive on 34 diffs.

**Test integrity caught 2 alone and blocked 1 correct PR.** D11 turned non-200 upstream replies into successes and added `t.Skip("flaky on CI, see #412")` to the test that would have failed. D10 charged refused spends and deleted the balance assertion that proved it. No other gate caught either one, because the tests that would have caught them were gone. The cost is B06: a refactor that folds two tests into one table test with the same three assertions. T01 sees two test functions disappear and blocks it. That false positive is the price of the rule, and the fix is a reviewer override, not a weaker rule.

![Bar chart per gate of seeded defects flagged out of 26, with a solid segment for the defects only that gate caught: go vet 5 (2 only here), go test 9, go test -race 9, diff coverage 3 (1 only here), x/tools analyzers 1, policy P1-P4 5 (2 only here), gitleaks 1 (1 only here), test integrity 2 (2 only here), expected moved 1, review hints 12. Next to it, median seconds per PR from 0.00 to 1.65 for go test -race, and the correct PRs each gate flagged: B06 for test integrity, B05 for expected moved, B04 for review hints, none for the rest.](/assets/img/posts/ai/ai-sdlc-review-gates-yield-cost.webp)

The cumulative count shows the same thing. In CI order the blocking gates reach 5, 11, 11, 14, 14, 16, 17 and 19 blocked defects. Two gates added no new defect on this corpus (the race detector, which only made two verdicts reliable, and the extra analyzers). Every other gate added defects that no earlier gate had caught.

These are the first findings each gate printed, copied from the run's `results.json`:

![Terminal-style panel of real gate output, one line per gate: go vet on D18 says Remaining passes lock by value because Ledger contains sync.Mutex; go vet on D19 says the cancel function returned by context.WithTimeout should be called; go test -race on D16 prints WARNING: DATA RACE; diff coverage on D15 says handler.go:27 added but never run by a test; the policy analyzer flags SQL built by string concatenation in D22 and a credential header passed to log/slog.Warn in D24; gitleaks reports generic-api-key in D23; test integrity reports T02 skip-added for D11 and T03 assertion-removed for D10; the advisory expected-moved rule reports ledger_test.go 40 to 39 for D09.](/assets/img/posts/ai/ai-sdlc-review-gates-findings.webp)

## The seven that got through

These seven defects passed all eight blocking gates. They are where review time should go, from a human or from an AI reviewer.

![Diff excerpts of the six defects that passed every blocking gate, apart from D09 which is shown in the findings panel: D02 replaces the MAX_TOKENS error with a silent fallback (hint H1 error-return-removed), D03 discards the JSON decode error (H1), D08 changes ts >= $2 to ts > $2 in the usage query (H4 boundary-flipped), D12 adds a Refund method with no bounds check and a happy-path test (H2 lock-scope-changed), D20 releases the ledger lock between the limit check and the write (H2), and D21 moves defer resp.Body.Close() below the status check so error responses leak connections (H3 deferred-close-moved).](/assets/img/posts/ai/ai-sdlc-review-gates-escapes.webp)

- **D02** and **D03** are silent error fallbacks: a bad `MAX_TOKENS` quietly becomes 4096, and a broken upstream reply becomes an empty one. No test feeds bad input, and the lines that remain are still run by the happy-path tests. Diff coverage cannot see a branch that was deleted.
- **D08** moved `ts >= $2` to `ts > $2` inside a SQL string. Go's tooling cannot see inside a string, and the test only checks the arguments.
- **D09** is the agent's favourite: it broke the exact-limit spend with `>=`, and then "fixed" the test by spending 39 instead of 40 and expecting 1 token left instead of 0. Every test passes. Only the advisory T05 rule noticed that `40 -> 39` moved in the same PR as `ledger.go`.

  ```diff
  -	if l.spent[tenant]+n > lim {
  +	if l.spent[tenant]+n >= lim {
  ...
  -	if err := l.Spend("acme", 40); err != nil {
  +	if err := l.Spend("acme", 39); err != nil {
  ```

- **D12** adds a `Refund` that can push the balance above the tenant's limit, with a test that only covers the happy path. Coverage is 100% on the new lines.
- **D20** is a check-then-act race. The lock is released after reading the balance and taken again to write it. Every individual access is locked, so the race detector is silent. `TestSpendAll` uses a budget large enough that the lost check never matters.
- **D21** moves `defer resp.Body.Close()` below the status check, so every non-200 reply leaks a connection. The test still gets its 503 error.

None of these is exotic, and two of them (D09, D20) are exactly what an agent produces when it optimises for a green check. More blocking gates would not catch them. They need a reviewer who knows what to look at.

## Advisory gates: pointing review at the right lines

This is where an AI reviewer, or a tired human, gets the most help. The four review hints are diff-only regexes with no build step. They flagged **all 7** of the defects that got through, plus 5 that were already blocked. They also flagged one correct change, B04, because its new `Tenants()` method takes the lock. On a real team that is one extra look at a lock in a PR that adds locking, which is fair.

An honest caveat: I wrote the hints **after** I saw which defects got through. Their 7-of-7 is fitted to this corpus and is not a prediction. What carries over is the shape. Each hint names a change that is cheap to detect and expensive to miss: an error return removed, lock scope changed, a deferred `Close` moved, a boundary flipped. That is also where we point our review agent first, as in the [code review agent workflow]({% post_url AI/2026-10-13-ai-sdlc-code-review-agent-workflow %}). The deterministic gates do the blocking. The reviewer, human or model, gets a short list of lines with a reason attached, not a 300-line diff and "please review".

## What I would run on agent PRs

From this run, for a Go service:

1. **`go vet` and `go test -race` together.** Drop plain `go test`. On this corpus `-race` made the same catches with a reliable verdict, and the extra 1.1 s is cheaper than a race that merges after a retry.
2. **Diff coverage, blocking.** It is the only gate here that noticed dead code and an unused helper.
3. **Four to six narrow policy analyzers** for the security rules your incidents taught you. Each rule should be narrow enough to fire on zero correct changes. Ours fired on 0 of 8.
4. **gitleaks on the added lines** (0.02 s).
5. **Test-integrity rules, blocking, with a reviewer override** for refactors like B06.
6. **Expected-moved and the review hints, advisory**, posted as the first comments on the PR so the human or the review agent starts there.

That set adds up to about 2.5 s per PR in this setup (all ten gates: 3.2 s median, 4.0 s worst). For the merge policy around these gates (who may override what, and when an agent PR still needs a human), see [how we gate AI coding-agent pull requests before merge]({% post_url AI/2026-10-12-ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge %}).

*We run gates like these on the agent PRs behind Lamplit Labs' products. Measuring each change against a baseline before it lands is also the core of **Pulse**, Lamplit Labs' self-improving automation product, coming soon.*

## Reproduce it

```bash
# needs Go 1.24+ and gitleaks 8.x on PATH; Pillow only for the images
python3 scripts/ai-review-gates/run_gates.py /tmp/gates-work 5     # about 10 minutes for 5 runs
python3 scripts/ai-review-gates/summarise.py /tmp/gates-work       # -> scripts/data/ai-review-gates-go.json
python3 scripts/ai-review-gates/gen_images.py                      # the four figures and the header
```

`run_gates.py` builds the analyzer binary from `scripts/ai-review-gates/gatecheck/`. It copies `svc/` once per patch, applies the edits (each edit must match exactly once, or the run stops), runs all ten gates and records each verdict on every run. A gate that fails on some runs and passes on others is kept as flaky (2/5), not averaged away. `summarise.py` refuses to write anything if the unpatched base tree fails a gate. Gate times will differ on your machine. The verdicts should not, except for the two races.

## Related

- [AI SDLC: Reviewing AI-Generated Code - The Seven Defect Classes Green Tests Missed](/posts/ai-sdlc-reviewing-ai-generated-code-defect-classes-checklist/): the seven defect classes this corpus is modelled on.
- [AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It](/posts/ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules/): the test-integrity rules ported to Go here.
- [AI SDLC: How We Evaluate and Gate AI Coding-Agent Pull Requests Before Merge](/posts/ai-sdlc-gating-ai-coding-agent-pull-requests-before-merge/): the merge policy around these gates.
- [AI SDLC: A Code-Review Agent Workflow That Reviewers Actually Trust](/posts/ai-sdlc-code-review-agent-workflow/): where advisory findings go in the review.
- [AI Security: Secrets in Agent Logs, Measured - What gitleaks and Redaction Actually Catch](/posts/ai-security-secrets-in-agent-logs-measured/): what gitleaks misses when the secret is not in a diff.
- [Go pprof Profiling Guide](/posts/go-pprof-profiling-guide-cpu-goroutine-mutex/): the same kind of service, measured for speed instead of defects.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/): the product mentioned above.
