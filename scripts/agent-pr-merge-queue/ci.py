#!/usr/bin/env python3
"""Shared helpers: a scratch git repo with one branch per agent PR, merges, and the CI gate.

The CI gate is the one every PR passed in its own workspace: gofmt -l, go vet, go test -race.
Results are cached by git tree hash, so a tree that two policies both test runs once
(the cache records the wall time of the real run).
"""
import glob
import json
import os
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SVC = os.path.join(HERE, "..", "ai-review-gates", "svc")
PATCHES = os.path.join(HERE, os.environ.get("MQ_PATCHES", "patches"))   # or patches-split
GIT = ["git", "-c", "user.name=harness", "-c", "user.email=harness@example.invalid",
       "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "merge.conflictstyle=merge"]
ENV = dict(os.environ, GOTOOLCHAIN="local", GOFLAGS="-count=1")


def sh(cmd, cwd, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=ENV)
    if check and p.returncode:
        raise RuntimeError(f"{cmd} failed: {p.stdout}{p.stderr}")
    return p


def git(repo, *a, check=True):
    return sh(GIT + list(a), repo, check)


def tickets():
    return sorted(os.path.basename(p)[:-6] for p in glob.glob(os.path.join(PATCHES, "T*.patch")))


def short(t):
    return t[:3]


def make_repo(work):
    """base commit on main, one branch per ticket = base + that agent's patch."""
    repo = os.path.join(work, "repo")
    if os.path.exists(repo):
        shutil.rmtree(repo)
    shutil.copytree(SVC, repo)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    for t in tickets():
        git(repo, "checkout", "-q", "-b", short(t), "main")
        git(repo, "apply", "--index", os.path.join(PATCHES, t + ".patch"))
        git(repo, "commit", "-q", "-m", t)
        git(repo, "checkout", "-q", "main")
    return repo


def merge(repo, onto, branch):
    """Merge `branch` into commit `onto` without touching the worktree (git merge-tree, ort strategy,
    the same merge `git merge` does). Returns (merge commit or None, conflicted files)."""
    p = git(repo, "merge-tree", "--write-tree", "--name-only", "--no-messages", onto, branch, check=False)
    lines = p.stdout.split()
    if p.returncode == 1:
        return None, sorted(set(lines[1:]))
    if p.returncode:
        raise RuntimeError(p.stderr)
    c = git(repo, "commit-tree", lines[0], "-p", onto, "-p", branch, "-m", f"merge {branch}").stdout.strip()
    return c, []


def tree(repo, commit):
    return git(repo, "rev-parse", commit + "^{tree}").stdout.strip()


class CI:
    def __init__(self, repo, cache_path):
        self.repo = repo
        self.cache_path = cache_path
        self.cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        for r in self.cache.values():           # entries written before the classification fix
            if r["stage"] == "vet" and r["first"].startswith("vet: "):
                r["stage"] = "build"

    def run(self, commit):
        """Return {"ok", "stage", "first", "seconds", "tree"} for the tree of `commit`."""
        t = tree(self.repo, commit)
        if t in self.cache:
            return self.cache[t]
        git(self.repo, "checkout", "-q", "--detach", commit)
        t0 = time.time()
        res = {"ok": True, "stage": "green", "first": "", "tree": t}
        stages = [("gofmt", ["gofmt", "-l", "."]), ("vet", ["go", "vet", "./..."]),
                  ("test", ["go", "test", "-race", "./..."])]
        for name, cmd in stages:
            p = sh(cmd, self.repo, check=False)
            out = (p.stdout + p.stderr).strip()
            bad = p.returncode != 0 or (name == "gofmt" and out)
            if bad:
                # go vet type-checks the package and its tests first; a type error is printed
                # as "vet: ./file.go:..." and means the merged tree does not compile.
                if name == "vet" and "vet: " in out:
                    name = "build"
                lines = [l for l in out.splitlines() if l.strip() and not l.startswith(("#", "FAIL\t", "ok "))]
                res = {"ok": False, "stage": name, "first": lines[0][:200] if lines else out[:200], "tree": t,
                       "output": out[:4000]}
                break
        res["seconds"] = round(time.time() - t0, 2)
        self.cache[t] = res
        json.dump(self.cache, open(self.cache_path, "w"), indent=1)
        return res
