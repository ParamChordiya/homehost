"""Git-based deployment utilities for HomeHost."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git subcommand and return (returncode, stdout+stderr)."""
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        return 1, "git not found in PATH"
    except subprocess.TimeoutExpired:
        return 1, "git command timed out"


# ---------------------------------------------------------------------------
# Repository detection
# ---------------------------------------------------------------------------


def is_git_repo(path: Path) -> bool:
    """Return True if *path* is inside a git repository."""
    code, _ = _run_git(
        ["rev-parse", "--is-inside-work-tree"],
        cwd=path,
    )
    return code == 0


# ---------------------------------------------------------------------------
# Branch / commit info
# ---------------------------------------------------------------------------


def get_current_branch(path: Path) -> str:
    """Return the current git branch name, or '' if not a git repo."""
    code, output = _run_git(
        ["rev-parse", "--abbrev-ref", "HEAD"],
        cwd=path,
    )
    if code != 0:
        return ""
    return output.strip()


def get_latest_commit(path: Path) -> dict[str, str]:
    """Return info about the HEAD commit.

    Keys: ``hash``, ``message``, ``author``, ``timestamp``.
    All values are empty strings if *path* is not a git repo or has no commits.
    """
    # Pretty format: hash|subject|author name|ISO date
    code, output = _run_git(
        ["log", "-1", "--pretty=format:%H|%s|%an|%aI"],
        cwd=path,
    )
    if code != 0 or not output:
        return {"hash": "", "message": "", "author": "", "timestamp": ""}

    parts = output.split("|", 3)
    # Guard against unexpected output shape
    while len(parts) < 4:
        parts.append("")

    return {
        "hash": parts[0],
        "message": parts[1],
        "author": parts[2],
        "timestamp": parts[3],
    }


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def pull_latest(path: Path) -> tuple[bool, str]:
    """Run ``git pull`` in *path*.

    Returns ``(success, output)`` where *output* is the combined stdout +
    stderr from git.
    """
    code, output = _run_git(["pull"], cwd=path)
    return code == 0, output


def has_uncommitted_changes(path: Path) -> bool:
    """Return True if the working tree has uncommitted changes (tracked files).

    This covers both staged (index) and unstaged modifications.  Untracked
    files are not considered — use ``git status --porcelain`` for those.
    """
    # Exit code 1 → dirty; exit code 0 → clean
    code, _ = _run_git(["diff", "--quiet", "HEAD"], cwd=path)
    return code != 0
