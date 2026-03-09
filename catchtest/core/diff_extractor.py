"""Git diff parsing and context extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from catchtest.utils.git import get_changed_files, get_commit_message, get_diff, get_file_at_ref


@dataclass
class ChangedFile:
    path: str
    language: str
    diff_hunks: list[str]
    parent_content: str
    child_content: str
    changed_functions: list[str] = field(default_factory=list)


@dataclass
class DiffContext:
    base_ref: str
    target_ref: str
    diff_text: str
    changed_files: list[ChangedFile]
    commit_message: str


EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".cpp": "cpp",
    ".c": "c",
    ".cs": "csharp",
}

# Patterns to detect function definitions by language
FUNCTION_PATTERNS = {
    "python": re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE),
    "javascript": re.compile(
        r"(?:function\s+(\w+)\s*\(|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\(.*?\)\s*=>))",
        re.MULTILINE,
    ),
    "typescript": re.compile(
        r"(?:function\s+(\w+)\s*[\(<]|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\(.*?\)\s*=>))",
        re.MULTILINE,
    ),
    "java": re.compile(
        r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\(",
        re.MULTILINE,
    ),
}


def _infer_language(file_path: str) -> str:
    ext = Path(file_path).suffix
    return EXTENSION_TO_LANGUAGE.get(ext, "unknown")


def _parse_hunks(diff_text: str, file_path: str) -> list[str]:
    """Extract individual diff hunks for a specific file from unified diff output."""
    hunks: list[str] = []
    in_file = False
    current_hunk: list[str] = []

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            # Save previous hunk
            if current_hunk:
                hunks.append("\n".join(current_hunk))
                current_hunk = []
            # Check if this diff section is for our file
            in_file = file_path in line
        elif in_file and line.startswith("@@"):
            if current_hunk:
                hunks.append("\n".join(current_hunk))
            current_hunk = [line]
        elif in_file and current_hunk:
            current_hunk.append(line)

    if current_hunk:
        hunks.append("\n".join(current_hunk))

    return hunks


def _extract_changed_functions(hunks: list[str], language: str) -> list[str]:
    """Find function names touched by diff hunks."""
    pattern = FUNCTION_PATTERNS.get(language)
    if not pattern:
        return []

    functions = set()
    for hunk in hunks:
        for line in hunk.split("\n"):
            # Look at added/removed lines and context lines for function defs
            clean_line = line.lstrip("+-")
            match = pattern.search(clean_line)
            if match:
                # Get the first non-None group
                name = next((g for g in match.groups() if g is not None), None)
                if name:
                    functions.add(name)

    return sorted(functions)


def extract_diff(
    base: str,
    target: str,
    file_filter: str | None = None,
    cwd: Path | None = None,
) -> DiffContext:
    """Extract full diff context between two git refs."""
    diff_text = get_diff(base, target, file_filter, cwd=cwd)
    commit_message = get_commit_message(target, cwd=cwd)
    file_paths = get_changed_files(base, target, cwd=cwd)

    if file_filter:
        file_paths = [f for f in file_paths if file_filter in f]

    changed_files = []
    for file_path in file_paths:
        language = _infer_language(file_path)
        hunks = _parse_hunks(diff_text, file_path)
        parent_content = get_file_at_ref(base, file_path, cwd=cwd)
        child_content = get_file_at_ref(target, file_path, cwd=cwd)
        changed_functions = _extract_changed_functions(hunks, language)

        changed_files.append(ChangedFile(
            path=file_path,
            language=language,
            diff_hunks=hunks,
            parent_content=parent_content,
            child_content=child_content,
            changed_functions=changed_functions,
        ))

    return DiffContext(
        base_ref=base,
        target_ref=target,
        diff_text=diff_text,
        changed_files=changed_files,
        commit_message=commit_message,
    )
