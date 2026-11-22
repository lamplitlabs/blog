---
layout: post
title: "AI SDLC: Agent-Written Go Tests vs Mutation Testing, Measured - Same 97.3% Score, 15 or 19 Bugs Caught"
date: 2026-11-22 10:00:00 +0000
categories: ai
tags: [ai, ai-sdlc, sdlc, agents, go, testing, mutation-testing, ci, benchmark]
author: manishtiwari25
description: "12 agent-written Go test suites scored 92-97% on mutation testing and caught 15-19 of 26 seeded bugs. Two suites at the same 97.3% caught 15 and 19."
image:
  path: /assets/img/headers/ai/ai-sdlc-agent-written-tests-mutation-testing.webp
  alt: "Scatter chart of mutation score against seeded defects caught for 13 Go test suites: the hand-written suite scores 73.3% and catches 12 of 26; agents told to write unit tests score 96% and catch 17-18; agents told to reach 90% coverage score 92-94.7% and catch 17-18; agents told to kill the hand suite's surviving mutants score 97.3% and catch 15; agents told to kill an agent suite's surviving mutants score 97.3% and catch 18-19"
---

An earlier post here measured [LLM-generated .NET tests with Stryker](/posts/llm-test-generation-mutation-testing-dotnet/): line coverage said 94%, the mutation score said 41%, and a review loop raised it to 83%. That post treats mutation score as the honest number. I wanted to check that claim on a different stack. Is a higher mutation score a better test suite, measured by the bugs it actually stops?

So I needed a second, independent measure of "better", and I already had one. The [AI code review gates post](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/) built a 282-line Go service and 26 seeded agent-style defects for it: silent errors, off-by-ones, weakened tests, hallucinated APIs, races and security slips. A test suite is only useful if `go test` fails when one of those lands. That gives two scores per suite: the mutation score and the number of seeded defects it catches.

Short version: on 13 suites the two scores did not agree. Every agent-written suite scored 92-97.3%, and the extra mutation score did not buy extra caught bugs. Two arms ended at exactly 97.3%: one caught 15 of 26, the other 18-19. The difference was where the agent started, not what the mutation tool told it.

## The setup

Everything ran locally on an Apple M2 Pro with Go 1.27.4. The scripts and raw results are in the repository under `scripts/agent-tests-mutation/` and `scripts/data/agent-tests-mutation-go.json`.

**The service.** `scripts/ai-review-gates/svc`: a token-budget ledger, an HTTP spend handler, config loading from the environment, a pagination helper, a tenant directory with a SQL usage query, and an upstream LLM client. It ships with an 18-test hand-written suite.

**The mutation tester.** Go has no Stryker that I could run offline here, so I wrote a small one, `gomut`, with the standard library only. It parses the package with `go/ast` and makes one mutant per site and operator: flipped and off-by-one comparisons, `+`/`-` swaps, `&&`/`||` swaps, removed `!`, removed statements (assignments, calls, `defer`), and `return err` replaced by `return nil`. Each mutant runs through `go test -overlay`, so the source tree is never edited. On this service it made 81 mutants, and 6 of them do not compile. It reports a mutant as:

- **killed** if a test fails or times out;
- **lived** if the suite still passes;
- **not covered** if the line never runs (counted as lived);
- **not viable** if it does not compile (left out of the score).

**The defect check.** For each suite, every one of the 26 seeded defects is applied to the source and the suite runs twice, as `go test` and as `go test -race`. Test-file edits in the defect patches are dropped, so a defect can't weaken the suite it is being measured by. Five behaviour-preserving changes from the same corpus check the other direction: a suite that fails on them is brittle. The whole measurement ran twice per suite. A defect counts as caught only if both runs caught it.

**The agents.** Each run was a fresh coding agent with shell tools, locked to one workspace that held the service source, `go.mod` and a `TASK.md`. It never saw the defect corpus or the hand-written tests, except in the arm that starts from them. There were five arms:

| Arm | Starts from | TASK.md asks for |
|---|---|---|
| hand | - | the existing hand-written suite, no agent |
| plain (x3) | source only | "Write unit tests for this package" |
| 90% cov (x3) | source only | the same, plus "CI fails below 90% statement coverage" |
| mutants/hand (x3) | the hand-written suite + `MUTANTS.md` | "add or fix tests so these mutants are killed" |
| mutants/plain (x3) | plain run N's suite + its `MUTANTS.md` | the same |

`MUTANTS.md` is gomut's survivor list: one row per mutant that lived or was not covered, with file, line, operator and source line. This is what a CI job would post back to the agent.

## The results

| Suite | Tests | Statement coverage | Mutation score | Defects caught (of 26) | Agent time |
|---|---|---|---|---|---|
| hand-written | 18 | 89.1% | 73.3% | 12 | - |
| plain r1 / r2 / r3 | 36 / 33 / 29 | 99.0% | 96.0% | 18 / 18 / 17 | 94-101 s |
| 90% cov r1 / r2 / r3 | 24 / 25 / 23 | 99.0% | 92.0 / 94.7 / 94.7% | 18 / 18 / 17 | 70-77 s |
| mutants/hand r1 / r2 / r3 | 36 / 39 / 32 | 99.0% | 97.3% | 15 / 15 / 15 | 123-224 s |
| mutants/plain r1 / r2 / r3 | 37 / 34 / 30 | 99.0% | 97.3% | 19 / 19 / 18 | 40-54 s |

"Defects caught" counts a failure in `go test` or in `go test -race`. "Agent time" is the wall time the agent runner reported. The mutants/plain runs only had to add to an existing suite, which is why they were the fastest.

Four things stand out.

**1. Above about 90%, mutation score stopped ranking the suites.** Every agent suite landed between 92% and 97.3%. In that band, the suites that caught the most bugs (18-19) and the fewest (15) had the same 97.3%. The 90% coverage prompt produced smaller suites (23-25 tests against 29-36) with a lower mutation score than the plain prompt. They caught the same 17-18 defects.

**2. An agent told to kill mutants kills those mutants and stops.** The mutants/hand agents did their job well. All three killed 18 of the 20 listed survivors. All three named the other two (#63 and #70) as equivalent or unreachable, and gave the correct reason. The suite went from 73.3% to 97.3% and from 12 to 15 caught defects. Those 3 new catches are exactly where the survivor list pointed: a bad `MAX_TOKENS` silently falling back to the default (D02), a discarded decode error (D03), and a response body closed only on the success path (D21). But the plain agents, starting from nothing, caught 17-18. They wrote tests that no mutant had asked for.

**3. The tests that mattered were tests of intent, not of lines.** Two defects show the gap:

- **D22** builds the usage SQL by concatenating the tenant id.
- **D08** turns `ts >= $2` into `ts > $2`.

Both are edits to a string literal, and gomut, like most mutation tools, has no string-literal operators: it makes no mutant in `UsageQuery` at all, so the mutation score has nothing to say about it. The hand suite's `UsageQuery` test only checked that the query was non-empty and caught neither. Every plain and 90%-coverage agent wrote a test like this one, without being asked:

```go
func TestUsageQueryParameterised(t *testing.T) {
	since := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	evil := "x'; DROP TABLE usage; --"
	q, args := UsageQuery(evil, since)
	if strings.Contains(q, evil) || strings.Contains(q, "DROP") {
		t.Fatalf("tenant value interpolated into query: %q", q)
	}
	if !strings.Contains(q, "tenant = $1") || !strings.Contains(q, "ts >= $2") {
		t.Fatalf("query %q lacks $1/$2 placeholders", q)
	}
	// ...
}
```

The same goes for D20, a check-then-act race in `Spend`: the lock is released between the limit check and the write. Every plain and 90%-coverage suite had a "never overspends under concurrency" test. A mutation tool does not move locks, so the mutation-fed agents working from the hand suite never wrote one.

**4. Order matters more than the tool.** Give the survivor list to an agent after it has written its own suite and it adds one test: all three mutants/plain runs added a fake `RoundTripper` whose body records `Close()`. That kills #77 and catches D21, which no suite written from the source alone had caught. It took 40-54 s and 6-7 model calls. That arm caught the most defects, 18-19 of 26.

![gomut report for the hand-written suite of the Go quota service: 89.1% statement coverage, 73.3% mutation score, 55 killed, 11 lived, 9 not covered, 6 not viable; the source lines of config.go, handler.go, ledger.go, page.go and upstream.go are listed with red rows for lived mutants and yellow rows for not-covered ones, such as the removed c.UpstreamURL = u assignment, the || to && swap in the MAX_TOKENS check, the removed Content-Type header, the removed defer resp.Body.Close() and the error returns in upstream.go replaced by nil](/assets/img/posts/ai/ai-sdlc-agent-written-tests-mutation-testing-report.webp)

The screenshot above is gomut's HTML report for the hand-written suite, the list the mutants/hand agents worked from. Each red row is a mutant the suite let through. It is a good list of missing tests, and the agents treated it as the whole job.

## Which defects got through

![Matrix of 26 seeded defects by 13 test suites, green where go test fails and blue where only go test -race fails: 12 defects are caught by every suite, including the SpendAll races mostly through -race; D02 and D03 by every agent suite but not the hand-written one; D08 usage window and D22 SQL concatenation only by the plain and 90% coverage suites; D20 check-then-act by the plain and coverage suites only; D21 body close only by the two kill-the-mutants arms; D18 by 4 suites and D26 by 2; D12, D15, D19, D23, D24 and D25 by no suite; totals 12, 18, 18, 17, 18, 18, 17, 15, 15, 15, 19, 19, 18](/assets/img/posts/ai/ai-sdlc-agent-written-tests-mutation-testing-matrix.webp)

Read across the rows rather than down the columns:

- **Caught by all 13 suites (12 defects):** two silent errors (D01, D04), the boundary bugs a mutation operator would also make (`>` vs `>=` on the limit, the last-page slice, the 1-based page), three of the weak-test defects (D09-D11), both hallucinated-API defects and the two `SpendAll` races. D13 doesn't compile. D14 fails because `go test` runs a subset of `go vet`, and its `printf` check catches the swapped `fmt.Errorf` arguments. The other two silent errors (D02, D03) were caught by every agent suite but not by the hand suite.
- **Mostly only with `-race` (D16):** an unguarded counter in `SpendAll` passed plain `go test` reliably in 12 of 13 suites and failed every `-race` run. If CI runs tests without `-race`, it ships.
- **Caught by no suite (6 defects):**
  - a discarded context `cancel` (D19), which `go vet`'s `lostcancel` check catches, but `go test` does not run that check;
  - three security slips: a hard-coded fallback API key, the `Authorization` header in a log line, and TLS verification switched off (D23-D25);
  - a new `Refund` method that shipped with its own happy-path test (D12);
  - a duplicate pagination helper nothing calls yet (D15).

  A test suite for the old code can't see these.
- **Caught by only a few suites:** a mutex copied by a value receiver (D18, 4 suites) and the removed request-size limit (D26, 2 suites). Every 90% coverage suite sent a 128 KiB body, but only the two that checked the error text noticed it was rejected for a different reason. They belong to [the other CI gates](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/) and to review.
- **Brittleness:** none of the 13 suites failed on any of the 5 behaviour-preserving changes (a rename, `min` in `Page`, a new method with a test, an extra log line, `errors.New`). At this size, the extra agent tests cost nothing in false alarms.

## What it costs

On this service, `go test` takes 0.5-1.2 s. gomut takes 13-24 s with 4 parallel `go test` runs, because each of up to 75 viable mutants needs its own build. Three or four mutants per run hang (a removed `Unlock` or `wg.Done`), and the 5-second test timeout counts them as killed. The 12 agent runs took 19 minutes and 77 model calls in total. The full measurement of one suite, gomut plus 31 changes × 2 test modes, takes about 2 minutes.

## What I would do with this

- **Use mutation score as a floor, not a target.** Under about 90% it finds real gaps: the hand suite's 73.3% pointed at untested config validation, a missing `Content-Type` and the unclosed body. Above 90% it did not rank these suites. Don't make an agent chase the last points of it, and don't compare agent suites by it.
- **Ask for behaviour tests first, then feed back the survivors.** Asking for tests first and then giving back the mutation survivors scored best here (18-19 of 26), and the second step was the cheapest agent run in the experiment. Giving the survivor list to an agent as its only brief narrowed what it tested.
- **Say what the code must never do.** The tests that caught D08, D20 and D22 checked rules: values go in as parameters, the window includes its start, concurrent spends never overspend. Mutation tools can't create those tests, and coverage numbers don't ask for them. Put them in the task as one line each.
- **Keep `-race`, `go vet` and the security gates in CI.** Six of 26 defects got through all 13 suites, and one more got through 12 of them without `-race`. No test prompt will close that gap.
- **Check equivalent-mutant claims, but expect them to be right.** All 6 mutation-fed agents correctly identified #63 (`end > len` vs `>=`, where both branches assign the same value) and #70 (an error from `json.Marshal` of a `map[string]string`, which can't fail) as unkillable.

## Limits

- **One small service.** It is 282 lines with 26 defects written by hand to look like agent mistakes. Defect classes the corpus doesn't have, and a larger codebase, would move these numbers.
- **One agent family for every run, 3 runs per arm.** The mutation scores were identical inside most arms. The defect counts moved by 1 within an arm, so differences of 1 are noise. The 15 vs 18-19 gap held in all six runs.
- **gomut is small.** It has no string-literal, constant or lock-movement operators. A richer tool would rank suites differently, and part of finding 3 is about the operator set. Still, Stryker and PIT don't ship operators that check SQL text against its parameters either.
- **The hand-written suite is not a real team's suite.** It was written for the gates post. It is the arm's starting point, not a human baseline to beat.

Pulse, Lamplit Labs' self-improving automation product ([coming soon](/posts/pulse-internal-rsi-tool/)), uses the same pattern for its own work: a measured check decides, not a single score. This post is one more data point for why.

## Reproduce it

```bash
W=.tmp/atm
python3 scripts/agent-tests-mutation/harness.py human $W           # hand-written suite: coverage, gomut, 26 defects x (test, race)
python3 scripts/agent-tests-mutation/harness.py setup $W plain-r1 plain
python3 scripts/agent-tests-mutation/harness.py prompt $W plain-r1  # run any coding agent with this prompt
python3 scripts/agent-tests-mutation/harness.py measure $W plain-r1
python3 scripts/agent-tests-mutation/harness.py setup $W plainmut-r1 mutants plain-r1   # survivors -> MUTANTS.md
# ... agent, then measure; repeat a measurement with: measure $W <run> 2
python3 scripts/agent-tests-mutation/summarise.py $W                # -> scripts/data/agent-tests-mutation-go.json
BROWSER_PATH=<chrome-headless-shell> bash scripts/agent-tests-mutation/shots.sh $W
python3 scripts/agent-tests-mutation/gen_images.py $W
```

gomut on its own: `go run ./scripts/agent-tests-mutation/gomut -dir <package dir> -j 4 -json out.json -html out.html`. It needs only Go. The agents themselves are not scripted. Log their model calls and wall time in `<work>/agent_runs.tsv` (columns `run arm model_calls tool_steps seconds`), and `summarise.py` adds them to the data file.

## Related

- [LLM-Generated Unit Tests in .NET: Why Coverage Lies and How Mutation Testing Keeps Them Honest](/posts/llm-test-generation-mutation-testing-dotnet/): the earlier mutation-testing post this one checks.
- [AI SDLC: AI Code Review Gates in CI, Measured on a Go Service](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/): the service and the 26 seeded defects.
- [AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It](/posts/ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules/): the weak-test defects (D09-D12).
- [AI SDLC: The Agent-Written Code Review Loop, Measured](/posts/ai-sdlc-agent-code-review-loop-measured/): review as the gate for what tests miss.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/)
