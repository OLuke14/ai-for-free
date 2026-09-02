"""
Thin wrapper around the local `git` CLI for staging, committing, and pushing.

Deliberately uses subprocess + the git binary (not the GitHub API) so this
works on any local repo you already have cloned and authenticated (SSH key
or a credential helper using GITHUB_TOKEN).
"""
from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    pass


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError(f"`{' '.join(args)}` failed:\n{result.stderr.strip()}")
    return result.stdout.strip()


def is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def get_status(path: Path) -> str:
    return _run(["git", "status", "--short"], cwd=path)


def get_diff(path: Path, staged: bool = False) -> str:
    args = ["git", "diff"]
    if staged:
        args.append("--cached")
    return _run(args, cwd=path)


def stage_all(path: Path) -> None:
    _run(["git", "add", "-A"], cwd=path)


def commit(path: Path, message: str) -> str:
    return _run(["git", "commit", "-m", message], cwd=path)


def push(path: Path, remote: str = "origin", branch: str | None = None) -> str:
    args = ["git", "push", remote]
    if branch:
        args.append(branch)
    return _run(args, cwd=path)


def current_branch(path: Path) -> str:
    return _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=path)


def find_repo_root(path: Path) -> Path:
    """Walk upward from `path` to find the enclosing git repo root."""
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    return Path(result)


def list_branches(path: Path) -> list[str]:
    output = _run(["git", "branch", "--list"], cwd=path)
    return [line.lstrip("* ").strip() for line in output.splitlines() if line.strip()]


def branch_exists(path: Path, name: str) -> bool:
    return name in list_branches(path)


def create_branch(path: Path, name: str, from_branch: str | None = None) -> str:
    """Create a new branch and switch to it. Optionally base it off `from_branch`."""
    args = ["git", "checkout", "-b", name]
    if from_branch:
        args.append(from_branch)
    return _run(args, cwd=path)


def checkout_branch(path: Path, name: str) -> str:
    return _run(["git", "checkout", name], cwd=path)


def merge_branch(path: Path, source_branch: str, no_ff: bool = False) -> str:
    """
    Merge `source_branch` into the current branch.

    Does NOT raise on conflicts (git exits non-zero for those but it's an
    expected, recoverable state) — only raises for real failures (e.g.
    unknown branch, dirty tree). Callers should check has_merge_conflicts()
    after calling this.
    """
    args = ["git", "merge", source_branch]
    if no_ff:
        args.append("--no-ff")

    result = subprocess.run(args, cwd=path, capture_output=True, text=True)
    if result.returncode != 0 and "CONFLICT" not in result.stdout:
        raise GitError(f"`{' '.join(args)}` failed:\n{result.stderr.strip()}")
    return result.stdout.strip() or result.stderr.strip()


def has_merge_conflicts(path: Path) -> bool:
    status = get_status(path)
    return any(line.startswith(("UU", "AA", "DD", "UA", "AU", "UD", "DU")) for line in status.splitlines())


def abort_merge(path: Path) -> str:
    return _run(["git", "merge", "--abort"], cwd=path)


def is_working_tree_clean(path: Path) -> bool:
    return get_status(path) == ""
