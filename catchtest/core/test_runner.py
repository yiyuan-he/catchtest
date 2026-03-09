"""Execute generated tests against both parent and child revisions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from catchtest.core.weak_catch import GeneratedTest, TestResult, WeakCatch
from catchtest.utils.sandbox import Worktree, run_test_in_worktree

if TYPE_CHECKING:
    from catchtest.config import CatchTestConfig
    from catchtest.core.diff_extractor import DiffContext

logger = logging.getLogger(__name__)


def _extract_failure_info(output: str) -> tuple[str | None, str | None]:
    """Extract failure message and traceback from test output."""
    if not output:
        return None, None

    lines = output.split("\n")
    failure_msg = None
    traceback_lines: list[str] = []
    in_traceback = False

    for line in lines:
        if "FAILED" in line or "ERRORS" in line or "AssertionError" in line:
            failure_msg = line.strip()
        if "Traceback" in line or in_traceback:
            in_traceback = True
            traceback_lines.append(line)
        if line.startswith("E ") and not failure_msg:
            failure_msg = line.strip()

    traceback = "\n".join(traceback_lines) if traceback_lines else None
    return failure_msg, traceback


def run_and_find_catches(
    tests: list[GeneratedTest],
    diff_context: DiffContext,
    config: CatchTestConfig,
) -> list[WeakCatch]:
    """Run all generated tests against parent and child revisions.

    Uses git worktrees for isolation. Returns tests that passed on parent
    but failed on child (weak catches).
    """
    if not tests:
        return []

    weak_catches: list[WeakCatch] = []
    timeout = config.test.timeout_seconds

    logger.info("Running %d tests against parent (%s) and child (%s)",
                len(tests), diff_context.base_ref, diff_context.target_ref)

    try:
        with Worktree(diff_context.base_ref) as parent_wt, \
             Worktree(diff_context.target_ref) as child_wt:

            for i, test in enumerate(tests, 1):
                logger.info("Running test %d/%d targeting %s", i, len(tests), test.target_file)

                # Run on parent
                parent_passed, parent_stdout, parent_stderr = run_test_in_worktree(
                    parent_wt.path,
                    test.test_code,
                    framework=config.test.framework,
                    timeout=timeout,
                )
                parent_output = parent_stdout + "\n" + parent_stderr

                # Run on child
                child_passed, child_stdout, child_stderr = run_test_in_worktree(
                    child_wt.path,
                    test.test_code,
                    framework=config.test.framework,
                    timeout=timeout,
                )
                child_output = child_stdout + "\n" + child_stderr

                failure_msg, failure_tb = None, None
                if not child_passed:
                    failure_msg, failure_tb = _extract_failure_info(child_output)

                result = TestResult(
                    test=test,
                    passed_on_parent=parent_passed,
                    passed_on_child=child_passed,
                    parent_output=parent_output,
                    child_output=child_output,
                    failure_message=failure_msg,
                    failure_traceback=failure_tb,
                )

                # Weak catch: passed on parent, failed on child
                if parent_passed and not child_passed:
                    weak_catches.append(WeakCatch(test=test, result=result))
                    logger.info("  -> Weak catch found!")
                elif not parent_passed:
                    logger.debug("  -> Test also failed on parent, skipping")
                else:
                    logger.debug("  -> Test passed on both revisions")

    except Exception as e:
        logger.error("Error during test execution: %s", e)
        raise

    logger.info("Found %d weak catches out of %d tests", len(weak_catches), len(tests))
    return weak_catches
