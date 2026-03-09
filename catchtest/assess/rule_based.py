"""Pattern-matching false positive detector."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catchtest.core.diff_extractor import DiffContext
    from catchtest.core.weak_catch import WeakCatch


def _check_broken_mock(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if any(kw in output for kw in ["MagicMock", "patch", "mock", "MockError", "StopIteration"]):
        if "mock" in catch.test.test_code.lower():
            return ("broken_mock", -0.8)
    return None


def _check_type_mismatch(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if "TypeError" in output:
        return ("type_mismatch", -0.7)
    return None


def _check_reflection_brittle(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    code = catch.test.test_code
    if any(kw in code for kw in ["hasattr", "getattr", "__dict__", "._"]):
        return ("reflection_brittle", -0.8)
    return None


def _check_not_implemented(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if "NotImplementedError" in output:
        return ("not_implemented", -0.9)
    return None


def _check_infrastructure_error(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    infra_patterns = [
        "ConnectionRefusedError", "ConnectionError", "TimeoutError",
        "FileNotFoundError", "PermissionError", "OSError",
    ]
    if any(p in output for p in infra_patterns):
        return ("infrastructure_error", -1.0)
    return None


def _check_undefined_variable(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if "NameError" in output:
        return ("undefined_variable", -0.6)
    return None


def _check_ordering_sensitive(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    code = catch.test.test_code
    output = catch.result.child_output
    # Check if test compares ordered sequences and failure looks like ordering issue
    if re.search(r"assert.*==.*\[", code) and "AssertionError" in output:
        # Check for set-like comparison patterns
        if any(kw in code for kw in ["sorted", "set(", "order"]):
            return ("ordering_sensitive", -0.5)
    return None


def _check_implementation_detail(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    code = catch.test.test_code
    if any(kw in code for kw in ["call_count", "call_args", "called_with", "assert_called"]):
        return ("implementation_detail", -0.7)
    return None


# True positive patterns

def _check_unexpected_bool_flip(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if re.search(r"assert.*(True.*False|False.*True)", output):
        return ("unexpected_bool_flip", 0.7)
    return None


def _check_null_value(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if "None" in output and "AssertionError" in output:
        return ("null_value", 0.7)
    return None


def _check_empty_container(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if re.search(r"(\[\]|set\(\)|{})\s*(!=|==)", output):
        return ("empty_container", 0.6)
    return None


def _check_refactor_behavior_change(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    msg = ctx.commit_message.lower()
    if any(kw in msg for kw in ["refactor", "clean up", "cleanup", "restructure"]):
        return ("refactor_behavior_change", 0.8)
    return None


def _check_dead_code_removal(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    msg = ctx.commit_message.lower()
    if any(kw in msg for kw in ["remove dead code", "remove unused", "delete unused"]):
        return ("dead_code_removal_side_effect", 0.8)
    return None


def _check_create_failure(catch: WeakCatch, ctx: DiffContext) -> tuple[str, float] | None:
    output = catch.result.child_output
    if any(kw in output for kw in ["__init__", "constructor", "TypeError: __init__"]):
        return ("create_failure", 0.6)
    return None


# All pattern checkers
_PATTERNS = [
    _check_broken_mock,
    _check_type_mismatch,
    _check_reflection_brittle,
    _check_not_implemented,
    _check_infrastructure_error,
    _check_undefined_variable,
    _check_ordering_sensitive,
    _check_implementation_detail,
    _check_unexpected_bool_flip,
    _check_null_value,
    _check_empty_container,
    _check_refactor_behavior_change,
    _check_dead_code_removal,
    _check_create_failure,
]


def assess_rule_based(catch: WeakCatch, diff_context: DiffContext) -> tuple[float, str | None]:
    """Run all rule-based patterns and return the strongest signal.

    Returns (score, pattern_name) where score is in [-1.0, 1.0].
    """
    results = []
    for pattern_fn in _PATTERNS:
        result = pattern_fn(catch, diff_context)
        if result:
            results.append(result)

    if not results:
        return 0.0, None

    # Return the strongest signal (highest absolute value)
    strongest = max(results, key=lambda r: abs(r[1]))
    return strongest[1], strongest[0]
