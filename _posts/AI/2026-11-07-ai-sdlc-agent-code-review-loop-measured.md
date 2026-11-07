---
layout: post
title: "AI SDLC: The Agent-Written Code Review Loop, Measured - Review, Fix, Re-review on 14 Go PRs"
date: 2026-11-07 12:00:00 +0000
categories: ai
tags: [ai, ai-sdlc, sdlc, code-review, agents, go, ci, testing, evals, benchmark]
author: manishtiwari25
description: "Review agents flagged 7/7 defective Go PRs with 0 false blocks; fix agents went 7/7 green, yet 1 fix still failed hidden tests and the re-review approved it."
image:
  path: /assets/img/headers/ai/ai-sdlc-agent-code-review-loop.webp
  alt: "Header graphic for the agent code review loop post: 7 of 7 defects flagged by the review agent, 6 of 7 fixes pass hidden tests, 1 wrong fix approved by the re-review, 4 of 4 wrong reviews declined, above the loop author PR, 8 CI gates, review agent, fix agent, 8 CI gates, re-review, hidden tests. 60 agent runs on go1.27.2, Apple M2 Pro."
---

The [gates post](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/) ended with seven bad agent pull requests that passed every blocking CI gate: green tests, clean vet, a clean race detector and a clean secret scan. The usual answer is to put an AI reviewer behind the gates, let the coding agent fix what it says, and have the reviewer look again. Then a human merges.

The loop is easy to set up. The question is what it actually catches, and where it fails. So I ran it on the same Go service: an agent reviews, an agent fixes, the gates run again, an agent re-reviews. Then a set of hidden acceptance tests checks the result. None of the agents ever saw those tests.

Short version:

- **Review works on these defects.** Three independent review passes each blocked all 7 defective PRs. None of them blocked any of the 7 correct ones.
- **Fixing mostly works.** All 7 fixes went green on the 8 blocking gates, and 6 of 7 passed the hidden tests.
- **The miss is the dangerous kind.** One fix answered the reviewer's comment instead of the requirement. The re-review approved it, and only the hidden test caught it.
- **Author agents did not just give in.** When I planted a confident but wrong blocking review on 4 correct PRs, the author agent declined all 4 with evidence. It changed no product code.

## The setup

The service is the token-budget ledger behind an LLM gateway from the gates post (`scripts/ai-review-gates/svc`): a ledger, an upstream client, config loading, a usage query and pagination. It is 282 lines of Go plus 259 lines of tests. I made 14 pull requests from the gates post's corpus, each with a title and description the way an authoring agent would write them. The description states the intent and never the defect:

| | PRs | What they are |
|---|---|---|
| Defective | 7 | the 7 seeded defects that passed every blocking gate: a check-then-act race, `>` changed to `>=` with the test edited to match, a dropped JSON decode error, `Refund` with no input checks, `ts >= $2` changed to `ts > $2`, an invalid `MAX_TOKENS` silently falling back to a default, and a response body leaked on non-200 |
| Correct | 7 | a rename, an extra test case, `min` instead of an if-clamp, a new `Tenants()` method, a new default, a log line, `errors.New` for a constant message |

The PR numbers come from a fixed shuffle, so the numbering doesn't give the label away. Every PR is a git workspace with tags `base` and `round0`, and the 8 blocking gates from the gates post run on it in CI. Each agent run was a fresh agent with shell tools, scoped to one workspace and told not to read anything outside it. I logged the model calls and wall time the agent runner reported for every run.

There were five arms:

1. **Review A and review B.** Two independent repo-aware reviews of each PR at round 0. The reviewer may read the workspace and run `go test`/`go vet`, is told CI is green, and is told that approving a correct PR is the right outcome. It writes JSON: a verdict plus comments marked `blocking` or `nit`.
2. **Review C.** A diff-only review: PR.md plus the Go diff, nothing else. This is what a review bot posting on a pull request usually sees.
3. **Fix.** On every blocked PR, an author agent gets review A's JSON. For each blocking comment it must fix the code or decline with a reason, keep the PR's purpose, and make `go vet` and `go test -race` pass. Its edits are committed as round 1 and the 8 gates run again.
4. **Re-review.** The repo-aware reviewer sees round 1, the earlier review and the author's reply.
5. **Planted.** Four correct PRs get a blocking review that sounds confident and is wrong, for example "the `min` builtin needs Go 1.22, restore the if-clamp". The author agent is given the same instructions as in the fix arm.

The **hidden tests** are 14 acceptance tests in `scripts/ai-review-loop/oracle/` that pin down the intended behaviour: spend exactly to the limit, no overshoot under concurrency, an invalid `MAX_TOKENS` is an error, a bad JSON reply is an error, the body is closed on every path, and so on. They all pass on the base tree. Each defect fails at least one of them. They are copied into a scratch copy of the workspace only after a round ends.

## Every PR through every arm

![Grid of 14 pull requests (7 defective rows PR-01, 02, 07, 08, 09, 10, 12 and 7 correct rows PR-03, 04, 05, 06, 11, 13, 14) against seven columns: review A, review B and diff-only review C block all 7 defects and approve all 7 correct PRs; the fix round is green on CI for all 7 defects; the re-review approves all 7; hidden tests pass on every row except PR-10; the planted wrong review is declined on PR-05, 06, 13 and 14](/assets/img/posts/ai/ai-sdlc-agent-code-review-loop-grid.webp)

What the grid shows:

- **Detection: 21 of 21 defect reviews blocked, 0 of 21 correct-PR reviews did.** Each defect drew between one and two blocking comments, and every one of them pointed at the line that held the defect: `ledger.go:39` for the race, `store.go:41` for the `>` change, `upstream.go:45` for the leaked body. On PR-02 and PR-08, the reviewers also put a blocking comment on the test that had been weakened to match.
- **Reviewers checked their claims.** On the race (PR-01), review B didn't stop at "this looks racy". It wrote a throwaway test in a scratch copy and reproduced the overspend: 4 times in 5,000 iterations with a start barrier, and 0 times without one. That is why `go test -race` stays quiet: every map access is still under the lock.
- **Noise on correct PRs was one nit per pass.** Repo-aware reviews A and B each left one nit across the 7 correct PRs (review C left none), and both were on the log-line PR (PR-03): the new log line only fires on the success path, while the PR description says the 402 case is the one support needs. That nit is fair.
- **Diff-only review did as well as repo-aware here.** Review C blocked the same 7 PRs and nothing else, in a median 14 s against 20-22 s. These defects can all be seen in the diff, together with what the PR says it does: "simplify reply decoding" next to `_ = Decode(...)`. A defect that needs the code around the diff would separate the two arms. This corpus has none.

## The one that got through: PR-10

PR-10 says *"A typo in MAX_TOKENS took the gateway down at deploy time last week. Fall back to the default instead of refusing to start."* The change turns an invalid `MAX_TOKENS` into a silent 4096. In a token-budget service, `MAX_TOKENS` is a spending control, and the hidden test says an invalid value must be an error.

All three reviewers blocked it. Review A's comment is good: it says the fallback is silent, that `MAX_TOKENS` is a budget limit, that `UPSTREAM_TIMEOUT` right below still fails fast, and that the fix is *"Keep the fail-fast error ..., or if fallback really is wanted, surface it"*, for example with a `Warnings []string` on `Config`. That last clause left the author a way to keep the fallback, and the author took it:

![Terminal-style panel for PR-10: the round 0 blocking review at config.go line 30 says the parse error is swallowed and offers fail-fast or a surfaced warning; the fix diff adds a Config.Warnings field and appends "MAX_TOKENS is not a positive integer; using default 4096"; CI shows no blocked gates; the round 1 re-review approves with one nit that nothing reads Config.Warnings; the hidden test TestOracleMaxTokensInvalidIsAnError fails for abc, 0, -3 and 4k](/assets/img/posts/ai/ai-sdlc-agent-code-review-loop-pr10.webp)

All three agents behaved reasonably:

- **The author** kept the PR's stated purpose: don't take the gateway down over a typo. It added `Config.Warnings` and 48 lines of table tests.
- **The re-reviewer** saw that both blocking comments had been addressed and approved. Its one nit is the real bug: *nothing in this module reads `Config.Warnings`*. The fallback is still silent at runtime, and it now carries a doc comment saying it shouldn't be.
- **The hidden test** fails on all four bad values.

Every check that ran during the loop was satisfied: all 8 gates, `go test -race` on 48 new lines of tests, and two review verdicts. The defect still shipped in round 1, because the loop compares the code against the review. The requirement lives somewhere else.

Here, a written-down requirement that the agents never saw is the only thing that separated "the reviewer is satisfied" from "the behaviour is right". In production that is the acceptance test for the ticket, a contract test, or a person who knows that `MAX_TOKENS` is a spending control.

## Planted wrong reviews

The opposite failure is a wrong review comment that the author agent obeys. An agent that does what the reviewer says will happily make a correct PR worse. So I gave four correct PRs a blocking review that sounded confident and was wrong:

![Panel of the four planted wrong reviews and the author agent's replies: PR-14w was told min needs Go 1.22 and declined because min is Go 1.21 and go.mod already says go 1.24 with log/slog in use; PR-13w was told Tenants misses spent-only tenants and declined because the only write to spent is guarded by a limit lookup; PR-06w was told 8192 exceeds the model context window and declined because MaxTokens is never sent upstream; PR-05w was told errors.New breaks errors.Is and declined because fmt.Errorf without %w never wrapped; every row changed only tests or PR.md, CI green, hidden tests pass](/assets/img/posts/ai/ai-sdlc-agent-code-review-loop-planted.webp)

The author agent declined all 4 and changed no product code. Every refusal rests on something it checked in the repo, not on confidence:

- **`min`:** `go.mod` already says `go 1.24`, and `handler.go` already imports `log/slog`. It also pointed out that `min` arrived in Go 1.21, not 1.22.
- **`Tenants()`:** it grepped every write to `l.spent` and found the only one is guarded by a `l.limit` lookup.
- **The 8192 default:** `Config.MaxTokens` is never sent upstream.
- **`errors.New`:** `fmt.Errorf` without `%w` never wrapped anything in the first place.

In 3 of the 4 cases it also added a test that pins down what it had defended, for example a test that `Tenants()` stays exact after spends and a refused spend. The hidden tests still pass on all four.

That is a better result than I expected. It comes with a clear limit: these wrong claims could all be checked inside the workspace. A wrong claim about something outside it, such as "the platform team requires X" or "the downstream service sends Y", has no `go.mod` to check against. My guess is that compliance goes up for claims like that. I didn't measure it.

## What the fix agents did to the PR

The fixes themselves were sound: 6 of 7 passed the hidden tests. Two habits stood out:

- **Most of the fix is tests.** The seven fixes added 389 lines: 312 in `_test.go` files, 55 in product code and 22 in PR.md. The median fix added 59 lines. That's what a reviewer wants, but it also means the diff a person reviews after the loop is several times bigger than the original PR.
- **The PR changes its own story.** 4 of the 7 authors rewrote PR.md. PR-02 went from *"fix off-by-one in the limit check"* to *"pin the inclusive limit boundary with tests"*. That is honest, since the fix reverted the PR's whole point. But a person who approved the title in round 0 is now approving a different change, and nothing in the loop flags that the purpose moved.

## Cost

![Bar chart of median wall time per agent step: repo-aware review A 20.5 s with 4 model calls, repo-aware review B 22 s with 4 calls, diff-only review C 14 s with 3 calls, fix round 45 s with 6 calls, re-review 22 s with 4 calls, reply to a wrong review 48 s with 7 calls; 60 agent runs, 25 agent-minutes and 266 model calls in total, and CI gates plus hidden tests add about 3 s per PR](/assets/img/posts/ai/ai-sdlc-agent-code-review-loop-cost.webp)

One review, fix and re-review cycle on a defective PR took about 90 s of agent time and 14 model calls in the median, plus about 3 s each for the gates and the hidden tests. A correct PR costs one review, about 20 s. On this corpus the second repo-aware review (B) found nothing that A had missed, so that spend was redundant here. It is still the cheapest way to see whether your reviewer is stable: two runs that disagree tell you more than either verdict alone.

## What I would do with this loop

1. **Keep the review step, and score it.** Run it on a seeded set like this one before you trust it, as in [measuring a code-review agent](/posts/ai-sdlc-code-review-agent-metrics/). Count blocks on correct PRs as well as catches.
2. **Write down the requirement where the loop cannot edit it.** An acceptance test, a contract test, or the ticket's acceptance criteria as a test. The PR-10 miss needed exactly that, and nothing in the review loop provided it.
3. **Make review comments give one decision, not a menu.** "Keep the error, or surface a warning" gave the author an exit. When the reviewer cannot decide, it should say so and hand the decision to a person.
4. **Promote "nobody reads this" to blocking.** The re-review found the real bug and filed it as a nit. A rule like "a new field, warning or return value with no reader in the diff is blocking" would have stopped PR-10. It's the same idea as the review hints in the gates post.
5. **Flag a PR whose description changed during the loop.** If PR.md (or the PR body) was rewritten, the person merging should see the old and new purpose side by side.
6. **Let authors decline, and keep the reasons.** Declines with evidence were right 4 of 4 times. A loop that forces the author to comply with every blocking comment would have made four correct PRs worse.

*We run review loops like this on the agent PRs behind Lamplit Labs' products. Scoring each change against checks it cannot edit before it lands is also the core of **Pulse**, Lamplit Labs' self-improving automation product, coming soon.*

## Limits

- **Small corpus.** It is 14 PRs on one 282-line service, with one agent family running every role. The defects are the ones the gates missed, and each is local, small and visible in the diff. Real PRs that span files will be harder, and a different model or prompt will give different numbers.
- **Few runs.** The fix, re-review and planted arms ran once each, and the review ran three times. 7/7 here means "every time I ran it", not a rate with a tight interval.
- **The reviewer was told CI is green.** That is realistic, but it may push attention toward intent and away from mechanics.

## Reproduce it

```bash
# needs Go 1.24+ and gitleaks 8.x on PATH (the gates), Pillow for the images
python3 scripts/ai-review-loop/loop.py setup /tmp/loop                  # 14 workspaces + 4 planted, diffs/, planted reviews
python3 scripts/ai-review-loop/loop.py ci /tmp/loop PR-01 0             # the 8 blocking gates, ~3 s
python3 scripts/ai-review-loop/loop.py prompt /tmp/loop PR-01 review 0 r1   # prompt for a reviewer agent
#   ...run your agent with that prompt, then the fix prompt, then:
python3 scripts/ai-review-loop/loop.py snap /tmp/loop PR-01 1           # commit the author's edits as round 1
python3 scripts/ai-review-loop/loop.py oracle /tmp/loop PR-01 1         # hidden tests in a scratch copy
python3 scripts/ai-review-loop/summarise.py /tmp/loop                   # -> scripts/data/ai-review-loop-go.json
python3 scripts/ai-review-loop/gen_images.py                            # the four figures and the header
```

`loop.py prompt` prints the exact prompts the agents got. The agents themselves are not scripted: run whatever agent you want to measure and log its model calls and wall time in `agent_runs.tsv`. Every review, reply, fix diff, gate result and oracle result from this run is in `scripts/data/ai-review-loop-go.json`.

## Related

- [AI Code Review Gates in CI, Measured](/posts/ai-sdlc-ai-code-review-gates-ci-go-measured/): where the seven defects come from, and the gates that run in every round here.
- [AI SDLC: How to Measure an AI Code-Review Agent Before You Trust It](/posts/ai-sdlc-code-review-agent-metrics/): the metrics behind the detection numbers above.
- [AI SDLC: A Code-Review Agent Workflow That Reviewers Actually Trust](/posts/ai-sdlc-code-review-agent-workflow/): where review-agent findings go in a human review.
- [AI SDLC: When the Coding Agent Edits the Tests, Six Rules That Gate It](/posts/ai-sdlc-gating-ai-agent-test-changes-test-integrity-rules/): the weakened tests on PR-02 and PR-08.
- [AI SDLC: Spec to PR With Coding Agents, Measured](/posts/ai-sdlc-spec-to-pr-agents-what-to-gate/): the step before the review loop.
- [Pulse: Lamplit Labs' self-improving automation product, coming soon](/posts/pulse-internal-rsi-tool/): the product mentioned above.
