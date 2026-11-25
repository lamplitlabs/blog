# agent-pr-merge-queue: parallel agent PRs vs merge policy

Data and harness for the post `_posts/AI/2026-11-23-ai-sdlc-parallel-agent-prs-merge-queue-measured.md`.

- `tickets/` - twelve overlapping tickets for the quota service in `../ai-review-gates/svc`.
- `agents-md/default.md`, `agents-md/split.md` - the `AGENTS.md` each arm's agents got
  (split = "merge-friendly": new files, small edits, add exported names instead of changing them).
- `agent_prompt.txt` - the fixed prompt for every coding-agent run (`{WS}` = workspace name).
- `agent_runs.tsv`, `agent_runs_split.tsv` - model calls, tool steps and wall seconds per run.
- `patches/`, `patches-split/` - the 24 agent changes as recorded, `git diff` against the base.
- `ci.py` - scratch repo, `git merge-tree` merges, and the CI gate (gofmt, go vet, go test -race), cached by tree.
- `setup_runs.py`, `collect.py`, `matrix.py`, `simulate.py`, `summarise.py`, `transcript.py`,
  `gen_images.py` - see the post's "Reproduce it" section. From `matrix.py` on, only Go and git are needed.
