"""Tests for rule-based assessment patterns."""

from unittest.mock import MagicMock

from catchtest.assess.rule_based import assess_rule_based
from catchtest.core.weak_catch import GeneratedTest, TestResult, WeakCatch


def _make_catch(
    test_code: str = "def test_foo(): pass",
    child_output: str = "",
    commit_message: str = "update code",
) -> tuple[WeakCatch, MagicMock]:
    test = GeneratedTest(
        test_code=test_code,
        target_risk="test risk",
        target_file="src/main.py",
        workflow="intent",
    )
    result = TestResult(
        test=test,
        passed_on_parent=True,
        passed_on_child=False,
        parent_output="1 passed",
        child_output=child_output,
        failure_message=None,
        failure_traceback=None,
    )
    catch = WeakCatch(test=test, result=result)

    diff_context = MagicMock()
    diff_context.commit_message = commit_message

    return catch, diff_context


class TestFalsePositivePatterns:
    def test_broken_mock(self):
        catch, ctx = _make_catch(
            test_code="from unittest.mock import MagicMock\ndef test_foo(): pass",
            child_output="MagicMock object is not callable",
        )
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "broken_mock"

    def test_type_mismatch(self):
        catch, ctx = _make_catch(child_output="TypeError: expected str, got int")
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "type_mismatch"

    def test_not_implemented(self):
        catch, ctx = _make_catch(child_output="NotImplementedError")
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "not_implemented"

    def test_infrastructure_error(self):
        catch, ctx = _make_catch(child_output="ConnectionRefusedError: connection refused")
        score, pattern = assess_rule_based(catch, ctx)
        assert score == -1.0
        assert pattern == "infrastructure_error"

    def test_undefined_variable(self):
        catch, ctx = _make_catch(child_output="NameError: name 'x' is not defined")
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "undefined_variable"

    def test_reflection_brittle(self):
        catch, ctx = _make_catch(test_code="def test_foo(): hasattr(obj, '_private')")
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "reflection_brittle"

    def test_implementation_detail(self):
        catch, ctx = _make_catch(test_code="def test_foo(): mock.assert_called()")
        score, pattern = assess_rule_based(catch, ctx)
        assert score < 0
        assert pattern == "implementation_detail"


class TestTruePositivePatterns:
    def test_refactor_behavior_change(self):
        catch, ctx = _make_catch(commit_message="refactor: clean up auth module")
        score, pattern = assess_rule_based(catch, ctx)
        assert score > 0
        assert pattern == "refactor_behavior_change"

    def test_dead_code_removal(self):
        catch, ctx = _make_catch(commit_message="remove unused helper functions")
        score, pattern = assess_rule_based(catch, ctx)
        assert score > 0
        assert pattern == "dead_code_removal_side_effect"

    def test_no_signal(self):
        catch, ctx = _make_catch()
        score, pattern = assess_rule_based(catch, ctx)
        assert score == 0.0
        assert pattern is None
