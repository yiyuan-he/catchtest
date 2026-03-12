"""Git operations helper functions."""

from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(Exception):
    """Raised when a git command fails."""


def _run_git(*args: str, cwd: Path | None = None) -> str:
    """Run a git command and return stdout."""
    cmd = ["git"] + list(args)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"Git command timed out: {' '.join(cmd)}")

    if result.returncode != 0:
        raise GitError(
            f"Git command failed: {' '.join(cmd)}\n"
            f"stderr: {result.stderr.strip()}"
        )
    return result.stdout


def get_diff(base: str, target: str, file_filter: str | None = None, cwd: Path | None = None) -> str:
    """Get unified diff between two refs."""
    args = ["diff", base, target]
    if file_filter:
        args.extend(["--", file_filter])
    return _run_git(*args, cwd=cwd)


def get_file_at_ref(ref: str, file_path: str, cwd: Path | None = None) -> str:
    """Get file content at a specific git ref."""
    try:
        return _run_git("show", f"{ref}:{file_path}", cwd=cwd)
    except GitError:
        return ""  # File doesn't exist at this ref


def get_commit_message(ref: str, cwd: Path | None = None) -> str:
    """Get the commit message for a ref."""
    return _run_git("log", "-1", "--format=%B", ref, cwd=cwd).strip()


def get_changed_files(base: str, target: str, cwd: Path | None = None) -> list[str]:
    """Get list of files changed between two refs."""
    output = _run_git("diff", "--name-only", base, target, cwd=cwd)
    return [line for line in output.strip().split("\n") if line]


def get_current_sha(ref: str = "HEAD", cwd: Path | None = None) -> str:
    """Resolve a ref to its full SHA."""
    return _run_git("rev-parse", ref, cwd=cwd).strip()


def is_git_repo(path: Path | None = None) -> bool:
    """Check if the given path is inside a git repository."""
    try:
        _run_git("rev-parse", "--is-inside-work-tree", cwd=path)
        return True
    except GitError:
        return False


def get_remote_head(cwd: Path | None = None) -> str:
    """Resolve the remote tracking branch for the current branch (e.g. origin/feature-branch)."""
    try:
        return _run_git(
            "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}",
            cwd=cwd,
        ).strip()
    except GitError:
        raise GitError(
            "No remote tracking branch for the current branch. "
            "Push your branch or pass --base explicitly."
        )


def get_repo_root(cwd: Path | None = None) -> Path:
    """Get the root directory of the git repository."""
    root = _run_git("rev-parse", "--show-toplevel", cwd=cwd).strip()
    return Path(root)
