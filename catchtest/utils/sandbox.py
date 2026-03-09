"""Isolated test execution environment using git worktrees."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from catchtest.utils.git import GitError, _run_git


class Worktree:
    """Manages a temporary git worktree for isolated test execution."""

    def __init__(self, ref: str, cwd: Path | None = None) -> None:
        self.ref = ref
        self.cwd = cwd
        self._worktree_path: Path | None = None

    @property
    def path(self) -> Path:
        if self._worktree_path is None:
            raise RuntimeError("Worktree not created yet. Call create() first.")
        return self._worktree_path

    def create(self) -> Path:
        """Create a temporary worktree at the given ref."""
        tmp_dir = tempfile.mkdtemp(prefix="catchtest-wt-")
        self._worktree_path = Path(tmp_dir)

        try:
            _run_git(
                "worktree", "add", "--detach", str(self._worktree_path), self.ref,
                cwd=self.cwd,
            )
        except GitError as e:
            shutil.rmtree(self._worktree_path, ignore_errors=True)
            self._worktree_path = None
            raise GitError(f"Failed to create worktree for {self.ref}: {e}")

        return self._worktree_path

    def cleanup(self) -> None:
        """Remove the worktree and its directory."""
        if self._worktree_path is None:
            return

        try:
            _run_git("worktree", "remove", "--force", str(self._worktree_path), cwd=self.cwd)
        except GitError:
            # Worktree remove failed, clean up manually
            shutil.rmtree(self._worktree_path, ignore_errors=True)
            try:
                _run_git("worktree", "prune", cwd=self.cwd)
            except GitError:
                pass

        self._worktree_path = None

    def __enter__(self) -> Worktree:
        self.create()
        return self

    def __exit__(self, *args) -> None:
        self.cleanup()


def run_test_in_worktree(
    worktree_path: Path,
    test_file_content: str,
    framework: str = "pytest",
    timeout: int = 30,
) -> tuple[bool, str, str]:
    """Write a test file to a worktree and execute it.

    Returns (passed, stdout, stderr).
    """
    test_file = worktree_path / "_catchtest_generated_test.py"
    test_file.write_text(test_file_content)

    try:
        if framework == "pytest":
            cmd = ["python", "-m", "pytest", str(test_file), "--tb=short", "--no-header", "-q"]
        elif framework == "unittest":
            cmd = ["python", "-m", "unittest", str(test_file)]
        else:
            raise ValueError(f"Unsupported test framework: {framework}")

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=worktree_path,
            timeout=timeout,
        )
        passed = result.returncode == 0
        return passed, result.stdout, result.stderr

    except subprocess.TimeoutExpired:
        return False, "", f"Test execution timed out after {timeout}s"
    finally:
        test_file.unlink(missing_ok=True)
