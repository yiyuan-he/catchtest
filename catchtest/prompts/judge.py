"""Prompt for LLM-as-judge assessment of weak catches."""

SYSTEM_PROMPT = """\
You are a senior software engineer reviewing a test failure. Your job is to determine \
whether the failure reveals an unexpected bug in a code change, or whether the failure \
is expected/acceptable given the intent of the change."""

USER_PROMPT_TEMPLATE = """\
A test was generated that PASSES on the original code but FAILS on the proposed change.

## Diff
```
{diff_text}
```

## Inferred intent of the change
{intent}

## Test code
```
{test_code}
```

## Failure output
{failure_message}

## Failure traceback
{failure_traceback}

## Task
Determine whether this test failure reveals an UNEXPECTED bug in the code change, \
or whether the failure is expected/acceptable given the intent of the change.

Respond with EXACTLY this JSON format (no markdown fences):
{{
  "classification": "HIGH",
  "is_unexpected": true,
  "explanation": "Brief explanation of why this failure is or isn't a real bug",
  "behavior_change_summary": "One sentence describing what changed in plain English"
}}

Classification guide:
- HIGH: The failure clearly reveals an unintended side effect or bug
- MEDIUM: The failure is suspicious but could be intentional
- LOW: The failure is almost certainly due to an expected behavior change
"""


def build_judge_prompt(
    diff_text: str,
    intent: str,
    test_code: str,
    failure_message: str,
    failure_traceback: str,
    production_impact: str = "",
) -> tuple[str, list[dict]]:
    """Build the system prompt and messages for LLM judge assessment."""
    user_content = USER_PROMPT_TEMPLATE.format(
        diff_text=diff_text,
        intent=intent,
        test_code=test_code,
        failure_message=failure_message or "No failure message captured",
        failure_traceback=failure_traceback or "No traceback captured",
    )
    if production_impact:
        user_content += "\n\n## Production Impact\n" + production_impact

    return SYSTEM_PROMPT, [{"role": "user", "content": user_content}]
