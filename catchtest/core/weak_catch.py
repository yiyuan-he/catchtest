"""Data models for test results and weak catches."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GeneratedTest:
    test_code: str
    target_risk: str
    target_file: str
    workflow: str  # "intent" or "dodgy"


@dataclass
class TestResult:
    test: GeneratedTest
    passed_on_parent: bool
    passed_on_child: bool
    parent_output: str
    child_output: str
    failure_message: str | None = None
    failure_traceback: str | None = None


@dataclass
class WeakCatch:
    """A test that passed on the parent but failed on the child."""
    test: GeneratedTest
    result: TestResult  # always: passed_on_parent=True, passed_on_child=False
