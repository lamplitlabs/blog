---
layout: post
title: "AI SDLC: Flaky Agent PRs vs \"Re-run Failed Jobs\", Measured on 10,233 Go Test Runs"
date: 2026-11-11 10:00:00 +0000
categories: ai
tags: [ai, ai-sdlc, sdlc, code-review, agents, go, ci, testing, concurrency, benchmark]
author: manishtiwari25
description: "10,233 go test runs on 9 agent PRs: re-running red CI jobs merged 70% of flaky defects; one -race -shuffle -count=10 run merged none, in 54 ms."
image:
  path: /assets/img/headers/ai/ai-sdlc-flaky-agent-prs-ci-retries.webp
  alt: "Header graphic for the flaky agent PR post: 49% of defective PRs merge on one plain go test, 70% once CI re-runs red jobs up to 3 times, 0% on one go test -race -shuffle=on -count=10 run, which takes 54 ms with GORACE=atexit_sleep_ms=0. Below, four small line charts show each defect's merge chance rising with retries: F1 20% to 69%, F2 80% to 100%, F3 11% to 43%, F4 85% to 100%."
---

In the [AI code review gates post]({% post_url AI/2026-11-06-ai-sdlc-ai-code-review-gates-ci-go-measured %}) two of the 26 seeded agent defects did something the other 24 did not: plain `go test` caught them on some runs and missed them on others (2 of 5 and 3 of 5). I noted it and moved on. This post takes that up, because the usual CI answer to "the test went red once and green the next time" is the **Re-run failed jobs** button. Coding agents press that button too, without hesitating, and they have read access to the CI status.

So the question here is narrow and measurable. When an agent PR's bug only shows up some of the time, what does each CI test policy let merge? That covers one run, a re-run until green, `-shuffle`, `-race`, and repeated counts. What does each policy cost, and what does it do to correct PRs?

I ran the real test binaries **10,233 times** across 9 pull requests and 5 `go test` modes. Then I ran another 720 on a deliberately crowded runner and 1,440 for timing. After that I replayed eight CI policies on the recorded runs. There is no probability model in the numbers below. A policy "merges" a PR when the recorded runs it would have looked at were green.

![Matrix of nine pull requests (BASE, C1, C2 correct; T1, T2 nondeterministic tests; F1 to F4 defects) against six go test modes, each cell showing failing runs out of runs. Correct PRs are 0 everywhere. T1 is 0/400 on plain go test and about half red with -shuffle. F2 is 81/400 on plain go test and 150/150 with -race. F4 is 62/400 on plain go test, 107/150 with -race and 37/37 with -race -shuffle -count=10. The last column is twelve race binaries at once: T2 goes 8/80 red there.](/assets/img/posts/ai/ai-sdlc-flaky-agent-prs-ci-retries-matrix.webp){: width="1820" height="906" }

## The nine pull requests

The base tree is the same small Go token-budget service as the gates post (`scripts/ai-review-gates/svc`): a ledger with per-tenant limits, an HTTP handler, an upstream client and their 18 tests. Every PR below compiles. Each was written by hand to look like what a coding agent opens, and each one passes `go test` at least some of the time.

| ID | Kind | What the agent changed |
|----|------|------------------------|
| BASE | control | nothing |
| C1 | correct | adds `Ledger.Tenants()`, sorted, with a test |
| C2 | correct | adds the stress test an issue asked for: 50 concurrent spends of 10 against a limit of 250 must admit exactly 25 |
| T1 | nondeterministic test | handler tests now share one `*Server` "to save setup", plus a new test that only passes if the old ones ran first |
| T2 | nondeterministic test | a timeout test with 10 ms between the fake server's sleep (40 ms) and the client deadline (50 ms) |
| F1 | defect | `Ledger.Tenants()` returns map order; the new test expects sorted ids |
| F2 | defect | the `SpendAll` success counter is incremented without its mutex (D16 in the gates post) |
| F3 | defect | `wg.Add(1)` moved inside the goroutine (D17) |
| F4 | defect | the ledger lock is released between the limit check and the write, "to shorten the critical section", together with C2's stress test (D20 plus a test) |

T1 and T2 are bad tests around correct code. F1-F4 are wrong code whose tests notice only sometimes. F4 matters most. In the gates post, D20 got past every blocking gate because no test ran `Spend` concurrently against a tight limit. Here the agent was asked to add exactly that test, and it is still a coin toss.

Each PR was built once into two test binaries, `go test -c` and `go test -c -race`. A Python driver (`scripts/ai-sdlc-flaky-gates/measure.py`) then ran them in interleaved rounds:

- `plain`: `./x.test -test.count=1`, 400 runs per PR
- `shuffle`: the same with `-test.shuffle=<seed>`, 400 runs
- `race`: the race binary, 150 runs
- `race_shuffle`: the race binary with `-test.shuffle`, 150 runs
- `stress10`: the race binary with `-test.shuffle -test.count=10`, 37 runs

Shuffle seeds are 1, 2, 3 and so on, so every red run can be replayed. The host was an Apple M2 Pro (12 cores) with go1.27.2. It was not idle: the median 1-minute load was 6.6, which is about what a shared CI runner sees. The base tree and both correct PRs went **0 red in every one of their 3,411 runs**, so the red runs below come from the patches and not from the machine.

## What each mode sees

Read the matrix above row by row:

- **F1 (map order)** fails about 80% of the time in every mode, because Go randomises map iteration on purpose. Each retry gives it another roll: with up to five tries it merged 69% of the time (`retry_curve_plain` in the data file).
- **F2 (unlocked counter)** fails only **81 of 400** plain runs. Under `-race` it fails **150 of 150**. The race detector reports the write on `ledger.go:65` whether or not the lost increment happened to change the count.
- **F3 (`wg.Add` in the goroutine)** fails 89% of plain runs and 100% under `-race`. It never gets as far as the tests anyway: `go vet` in go1.27 reports `WaitGroup.Add called from inside new goroutine`, so the gates post's first gate blocks it.
- **F4 (check-then-act)** is the one to worry about. Plain `go test` catches it **62 of 400** times (16%). `-race` raises that to 71%, but the race detector never reports anything for F4 (0 race reports in 337 race-binary runs). Every access is under a lock; the bug is that the lock is taken twice. `-race` catches it more often only because its instrumentation slows the goroutines down and widens the window. Only `-count=10` made it fail every time (37 of 37).
- **T1 (shared server)** passes **400 of 400** plain runs. The new test only passes after `TestHandlerSpend` has spent 30 tokens, and Go runs tests in source order. `-shuffle` turns it red 49% of the time, with both tests failing. `-count=10` turns it red every time, because the second iteration starts with a drained ledger.
- **T2 (10 ms margin)** is green 399 of 400 plain runs on this host. When I started twelve race binaries at once (60 rounds, `contention.py`), it went red **8 of 80** times with `context deadline exceeded`. In those same crowded rounds the base tree and both correct PRs stayed **0 of 80** red.

One result I did not expect: for F4, `-race -shuffle` caught less than `-race` alone (84 of 150 against 107 of 150, and the 95% intervals only just meet). The order the tests run in changes how warm the scheduler is when the stress test starts. A race that depends on test order is not one you can make go away by picking an order.

![Terminal-style panel of the first red run of five cases, copied from the recorded output. T1 under -test.shuffle=1: TestHandlerSpendRest got remaining 30, TestHandlerSpend got remaining 0. F2 under -race: SpendAll ok = 42, want 50, then WARNING: DATA RACE with a read and a previous write at ledger.go:65. F1: Tenants = [b a]. F4 under -race -shuffle=3: SpendAll admitted 26 spends, want 25. T2 with twelve binaries at once: context deadline exceeded.](/assets/img/posts/ai/ai-sdlc-flaky-agent-prs-ci-retries-terminal.webp){: width="1500" height="802" }

`SpendAll admitted 26 spends, want 25` is the F4 bug in one line. 26 spends of 10 tokens went through against a 250-token limit. In production that is a tenant spending past its budget, which is exactly what the service exists to prevent.

## Eight CI policies, replayed on the recorded runs

A retry policy with k attempts takes consecutive, non-overlapping groups of k recorded runs in one mode. The PR merges if any run in its group is green, which is what "re-run failed jobs" does. The cost is the seconds of the attempts it used. The "every run must pass" policy is the inverse: it needs all k runs green.

![Bar chart of eight CI policies. Defects merged (mean over F1 to F4): go test one run 49%, re-run up to 3 tries 70%, go test 3 times with every run required 29%, -shuffle 50%, -race 12%, -race -shuffle 17%, -race -shuffle with re-runs 35%, -race -shuffle -count=10 0%. Nondeterministic tests let through: 100%, 100%, 100%, 75%, 99%, 74%, 93%, 47%. Correct PRs blocked: 0% for every policy. Seconds per green run: 0.01 for plain modes and about 1.1 for race modes.](/assets/img/posts/ai/ai-sdlc-flaky-agent-prs-ci-retries-policies.webp){: width="1500" height="850" }

| Policy | Defects merged (F1-F4 mean) | Flaky tests let through (T1, T2) | Correct PRs blocked |
|--------|-----------------------------:|---------------------------------:|--------------------:|
| `go test`, one run | 49% | 100% | 0% |
| `go test`, re-run failed job up to 3 tries | **70%** | 100% | 0% |
| `go test` 3 times, every run must pass | 29% | 100% | 0% |
| `go test -shuffle=on`, one run | 50% | 75% | 0% |
| `go test -race`, one run | 12% | 99% | 0% |
| `go test -race -shuffle=on`, one run | 17% | 74% | 0% |
| `-race -shuffle=on`, re-run up to 3 tries | 35% | 93% | 0% |
| `-race -shuffle=on -count=10`, one run | **0%** | 47% | 0% |

The retry button is the worst policy in the table. It took the merge rate for these defects from 49% to 70%. In 116 of the 532 three-run groups a defective PR went red, was re-run, and merged green. F4, the budget over-spend, merged **100%** of the time with three tries. That is not a flaky test being forgiven; it is a correct test reporting a real bug, and the policy throws the report away.

Retries also undo the race detector. With `-race -shuffle`, one run lets 17% of the defects through and three tries let 35% through. F2 and F3 are safe because the detector reports them every time. F1 and F4 are not data races, so `-race` only shifts their odds.

Requiring every run to pass is the honest version of running the tests more than once, and it cut defect merges to 29%. `-count=10` inside one binary does the same thing more cheaply. It runs each test ten times in one process, so shared state that leaks between iterations (T1) shows up as well. It was the only policy that merged **no** defect and caught T1 on every run, and it blocked no correct PR in 111 runs.

The only thing it missed is T2, which is a fair miss: the margin test only breaks on a crowded machine. The fix there is the test, not the policy. Give it a deadline from the test context or a fake clock, not a 10 ms margin.

## Where the race detector's second goes

Every race-mode run above costs about 1.1 s against 0.01 s for plain `go test`. That looks like the usual "race detector is 10x slower" trade, but it is not:

![Bar chart of median wall time of a green test-binary run across all nine cases: go test without the race detector 10 ms, go test -race with the default GORACE 1.08 s, go test -race with GORACE=atexit_sleep_ms=0 28 ms, and -race -shuffle -count=10 with atexit_sleep_ms=0 54 ms. Red runs per case are unchanged by removing the sleep: T1 24 vs 24, F2 40 vs 40, F4 24 vs 24.](/assets/img/posts/ai/ai-sdlc-flaky-agent-prs-ci-retries-race-timing.webp){: width="1500" height="520" }

The race runtime sleeps `atexit_sleep_ms` before it exits, **1000 ms by default**, so that reports from goroutines still running at exit get printed. On a test binary this small that sleep is 97% of the run. With `GORACE=atexit_sleep_ms=0` a green race run took **28 ms**, and the stress run with ten iterations took **54 ms**. The red-run counts with and without the sleep were the same within a run or two for every case: F2 was 40 of 40 both ways and F4 24 of 40 both ways. A race seen while a test is still running fails that test either way.

On a real service the race detector's instrumentation does cost something, usually 2x to 20x CPU. For a package of unit tests, though, much of the second you pay for `-race` is the sleep, once per test binary. Most repositories have dozens of test binaries.

## What I would run on agent PRs

1. **No automatic or agent-triggered re-runs on the PR's own tests.** If a re-run goes green, the PR is still marked as having gone red, and a person or the review agent has to say why. "Re-run failed jobs" stays available for infrastructure failures (runner lost, network), and the job has to say which kind it was.
2. **`go test -race -shuffle=on -count=10` as the test gate**, with `GORACE=atexit_sleep_ms=0` if the per-binary sleep adds up. On this corpus that one gate merged no defect and blocked no correct PR. Print the shuffle seed in the log so a red run can be replayed exactly.
3. **Treat a new test that fails some of the time as a finding about the PR.** In this set, four of the six PRs with nondeterministic results had wrong code behind them. A quarantine list is for tests that already exist, not for tests the PR just added.
4. **Ask agents for the concurrent test, and then run it more than once.** C2's stress test was the right test for F4, and it still passed 84% of single runs.
5. **Keep `go vet` in front.** It blocked F3 deterministically before any test ran.

Pick the policy you want before an agent finds the retry button. Agents keep pressing it until the build is green, and nothing in a green build tells you whether it was green on the first try.

*We gate the agent PRs behind Lamplit Labs' own products this way, and treating a red-then-green run as a signal rather than noise is part of how **Pulse**, Lamplit Labs' self-improving automation product (coming soon), decides what lands.*

## Limits

These are 9 hand-written PRs on one small service, run on one macOS laptop under background load, not a Linux CI fleet. The rates are specific to this code and this host. On a faster or idler machine F2 and F4 fail less often under plain `go test`, which makes retries even more forgiving, not less. What carries over is the shape. Retries turn "sometimes red" into "merged". `-race` only helps with real data races. Repeating tests inside one run catches order and state bugs that a single run cannot.

## Reproduce it

```bash
# needs Go 1.24+ (cgo for -race); Pillow only for the images
python3 scripts/ai-sdlc-flaky-gates/measure.py /tmp/flaky-work 400 150   # ~37 min on a loaded M2 Pro
python3 scripts/ai-sdlc-flaky-gates/contention.py /tmp/flaky-work 60 12  # ~1 min, 12 binaries at once
python3 scripts/ai-sdlc-flaky-gates/timing.py /tmp/flaky-work 40         # ~5 min, GORACE exit sleep
python3 scripts/ai-sdlc-flaky-gates/summarise.py /tmp/flaky-work         # -> scripts/data/ai-sdlc-flaky-gates-go.json
python3 scripts/ai-sdlc-flaky-gates/gen_images.py                        # the four figures and the header
```

`corpus.py` holds the patches as exact text replacements on `scripts/ai-review-gates/svc`. F2, F3 and F4 reuse D16, D17 and D20 from the gates corpus. `measure.py` is resumable: it appends one JSON line per run and skips runs already recorded. `summarise.py` refuses to write anything if the unpatched tree ever went red. The data file keeps the first failing output of every case and mode, with paths shortened.

## Related

- [AI Code Review Gates in CI, Measured: 26 Seeded Agent Defects Against a Go Pipeline](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/): the same service and the gates in front of this one.
- [AI SDLC: The Agent-Written Code Review Loop, Measured](/posts/ai-sdlc-agent-code-review-loop-measured/): what a review agent does with the findings.
- [AI SDLC: AI-Assisted Flaky Test Triage for .NET Pipelines](/posts/ai-sdlc-flaky-test-triage/): triage for tests that already exist and went flaky.
- [AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It](/posts/ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules/): rules for what an agent may do to tests.
- [Go Context Cancellation for LLM Streaming Agents](/posts/go-context-cancellation-llm-streaming-agents/): deadlines that come from the context, not from a margin.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/): the product mentioned above.
