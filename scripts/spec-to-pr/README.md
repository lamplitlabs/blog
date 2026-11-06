# spec-to-pr: thin vs full tickets through five PR gates

Data and harness for the post `_posts/AI/2026-11-06-ai-sdlc-spec-to-pr-agents-what-to-gate.md`.

- `base/` - the invoicing library every workspace starts from (8 tests, `AGENTS.md`).
- `specs/` - six tickets, each as `*.thin.md` and `*.full.md`.
- `agent_prompt.txt` - the fixed prompt each coding-agent run got (`{WS}` = workspace name).
- `agent_runs.tsv` - model calls, tool steps and wall seconds per run, from the agent runner.
- `patches/` - the 24 agent changes as recorded, `git diff` against the base commit.
- `acceptance/` - hidden acceptance tests (never in a workspace while the agent ran).
- `reference/` - reference solution the acceptance tests were checked against.
- `assumptions_coded.tsv` - each failed acceptance test matched by hand to the agent's report.
- `setup_runs.py`, `run_gates.py`, `summarise.py`, `spec_lint.py`, `gen_images.py` - see the post's
  "Reproduce it" section.
