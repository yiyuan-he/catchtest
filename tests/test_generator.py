"""Tests for test_generator module."""

from unittest.mock import MagicMock

from catchtest.core.test_generator import _parse_json_response, _syntax_check


class TestParseJsonResponse:
    def test_plain_json(self):
        result = _parse_json_response('{"key": "value"}')
        assert result == {"key": "value"}

    def test_json_with_code_fences(self):
        text = '```json\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}

    def test_json_with_plain_fences(self):
        text = '```\n{"key": "value"}\n```'
        result = _parse_json_response(text)
        assert result == {"key": "value"}


class TestSyntaxCheck:
    def test_valid_code(self):
        assert _syntax_check("def foo():\n    return 1") is True

    def test_invalid_code(self):
        assert _syntax_check("def foo(\n    return 1") is False

    def test_empty_code(self):
        assert _syntax_check("") is True
