"""Prompt for inferring diff intent and risks."""

SYSTEM_PROMPT = """\
You are a senior software engineer analyzing a code change to identify its intent \
and potential risks. You are precise, thorough, and focus on behavioral changes \
that could introduce bugs."""

USER_PROMPT_TEMPLATE = """\
Analyze the following code change and identify:
1. The intent of the change (what is the developer trying to accomplish?)
2. Potential risks — ways the implementation could go wrong or introduce unintended \
side effects.

## Commit Message
{commit_message}

## Changed Files
{changed_files_summary}

## Diff
```
{diff_text}
```

## File Context
{file_context}

Respond with EXACTLY this JSON format (no markdown fences):
{{
  "intent": "One paragraph describing the intent of this change",
  "risks": [
    "Risk 1: Description of a specific way the change could go wrong",
    "Risk 2: Description of another potential issue",
    ...
  ]
}}

Focus on risks that are:
- Behavioral (not stylistic or formatting)
- Testable (could be caught by a unit/integration test)
- Non-obvious (not just "the code might have a typo")
"""


def build_intent_prompt(
    commit_message: str,
    diff_text: str,
    changed_files_summary: str,
    file_context: str,
) -> tuple[str, list[dict]]:
    """Build the system prompt and messages for intent inference."""
    user_content = USER_PROMPT_TEMPLATE.format(
        commit_message=commit_message,
        changed_files_summary=changed_files_summary,
        diff_text=diff_text,
        file_context=file_context,
    )
    return SYSTEM_PROMPT, [{"role": "user", "content": user_content}]
