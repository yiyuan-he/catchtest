"""Tests for diff_extractor module."""

from catchtest.core.diff_extractor import (
    _extract_changed_functions,
    _infer_language,
    _parse_hunks,
)


class TestInferLanguage:
    def test_python(self):
        assert _infer_language("src/main.py") == "python"

    def test_javascript(self):
        assert _infer_language("app/index.js") == "javascript"

    def test_typescript(self):
        assert _infer_language("src/utils.ts") == "typescript"

    def test_tsx(self):
        assert _infer_language("components/App.tsx") == "typescript"

    def test_java(self):
        assert _infer_language("Main.java") == "java"

    def test_unknown(self):
        assert _infer_language("data.csv") == "unknown"


class TestParseHunks:
    def test_single_hunk(self):
        diff = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def hello():
-    return "hello"
+    return "world"
+    # extra line"""

        hunks = _parse_hunks(diff, "foo.py")
        assert len(hunks) == 1
        assert '-    return "hello"' in hunks[0]
        assert '+    return "world"' in hunks[0]

    def test_multiple_hunks(self):
        diff = """\
diff --git a/foo.py b/foo.py
@@ -1,3 +1,3 @@
 def a():
-    return 1
+    return 2
@@ -10,3 +10,3 @@
 def b():
-    return 3
+    return 4"""

        hunks = _parse_hunks(diff, "foo.py")
        assert len(hunks) == 2

    def test_wrong_file(self):
        diff = """\
diff --git a/foo.py b/foo.py
@@ -1,3 +1,3 @@
-old
+new"""

        hunks = _parse_hunks(diff, "bar.py")
        assert len(hunks) == 0


class TestExtractChangedFunctions:
    def test_python_functions(self):
        hunks = [
            "@@ -1,5 +1,5 @@\n def my_function():\n-    return 1\n+    return 2",
            "@@ -10,5 +10,5 @@\n async def async_handler():\n-    pass\n+    return None",
        ]
        functions = _extract_changed_functions(hunks, "python")
        assert "my_function" in functions
        assert "async_handler" in functions

    def test_javascript_functions(self):
        hunks = [
            "@@ -1,3 +1,3 @@\n function processData() {\n-    return null;\n+    return [];\n }",
        ]
        functions = _extract_changed_functions(hunks, "javascript")
        assert "processData" in functions

    def test_unknown_language(self):
        hunks = ["@@ -1,3 +1,3 @@\n-old\n+new"]
        functions = _extract_changed_functions(hunks, "unknown")
        assert functions == []
