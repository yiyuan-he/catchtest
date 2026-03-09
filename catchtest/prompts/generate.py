"""Prompts for test generation."""

SYSTEM_PROMPT = """\
You are an expert test engineer. You write precise, minimal tests that target \
specific behavioral risks in code changes. Your tests are designed to PASS on the \
original code but FAIL if a specific risk materializes."""

INTENT_AWARE_TEMPLATE = """\
Generate tests for the following code change. Each test should target a specific risk \
and be designed to PASS on the original code but FAIL if the described risk materializes.

## Original Code (parent version)
File: {file_path}
```{language}
{parent_content}
```

## Identified Risks
{risks}

## Test Framework: {framework}

## Instructions
- Generate one test function per risk
- Each test must be self-contained and runnable
- Import only from the module being tested and standard library
- Include any necessary setup/fixtures inline
- Do NOT use mocks unless absolutely necessary
- The test should verify the ORIGINAL behavior, so it passes on the parent code
- If the risk materializes in the changed code, the test should FAIL

Respond with EXACTLY this JSON format (no markdown fences):
{{
  "tests": [
    {{
      "risk": "The risk this test targets",
      "test_code": "Complete, runnable test code including imports"
    }},
    ...
  ]
}}
"""

DODGY_DIFF_TEMPLATE = """\
Here is the original code and a modified version. Generate tests that distinguish \
between the two — tests that PASS on the original but FAIL on the modified version.

## Original Code (parent version)
File: {file_path}
```{language}
{parent_content}
```

## Modified Code (child version)
```{language}
{child_content}
```

## Diff
```
{diff_text}
```

## Test Framework: {framework}

## Instructions
- Generate tests that verify the original behavior
- Each test should pass on the original code and fail on the modified code
- Focus on behavioral differences, not implementation details
- Tests should be self-contained and runnable

Respond with EXACTLY this JSON format (no markdown fences):
{{
  "tests": [
    {{
      "risk": "Brief description of what behavioral change this test detects",
      "test_code": "Complete, runnable test code including imports"
    }},
    ...
  ]
}}
"""


def build_intent_aware_prompt(
    file_path: str,
    language: str,
    parent_content: str,
    risks: list[str],
    framework: str,
) -> tuple[str, list[dict]]:
    """Build prompt for intent-aware test generation."""
    risks_text = "\n".join(f"- {risk}" for risk in risks)
    user_content = INTENT_AWARE_TEMPLATE.format(
        file_path=file_path,
        language=language,
        parent_content=parent_content,
        risks=risks_text,
        framework=framework,
    )
    return SYSTEM_PROMPT, [{"role": "user", "content": user_content}]


def build_dodgy_diff_prompt(
    file_path: str,
    language: str,
    parent_content: str,
    child_content: str,
    diff_text: str,
    framework: str,
) -> tuple[str, list[dict]]:
    """Build prompt for dodgy diff test generation."""
    user_content = DODGY_DIFF_TEMPLATE.format(
        file_path=file_path,
        language=language,
        parent_content=parent_content,
        child_content=child_content,
        diff_text=diff_text,
        framework=framework,
    )
    return SYSTEM_PROMPT, [{"role": "user", "content": user_content}]
