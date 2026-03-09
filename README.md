# CatchTest

A CLI tool that generates tests designed to catch unintended behavior changes in your code.

## How it works

```
git diff → generate failing tests → filter false positives → surface likely bugs
```

1. **Extract the diff** between two commits
2. **Ask an LLM** to identify risks and generate tests that verify the original behavior
3. **Run tests** against both the old and new code in isolated git worktrees
4. **Assess** each failure using rule-based patterns and an LLM judge
5. **Report** likely bugs, uncertain cases, and false positives

## Installation

```bash
pip install -e "."

# If using Amazon Bedrock as your LLM provider:
pip install -e ".[bedrock]"
```

## Setup

### LLM credentials

CatchTest needs an LLM provider. Pick one:

**Anthropic:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Amazon Bedrock:**
```bash
# Via AWS CLI:
aws configure

# Or via environment variables:
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

**OpenAI:**
```bash
export OPENAI_API_KEY=sk-...
```

### Configuration (optional)

Run `catchtest init` to create a `.catchtest.yaml` config file in your repo root. This lets you set defaults for provider, model, test framework, and more.

## Usage

Run from inside a git repository with at least 2 commits.

```bash
# Test the most recent commit (diffs HEAD~1 vs HEAD)
catchtest run

# Generate tests without executing them (good for a first try)
catchtest run --dry-run

# Use a specific provider and model
catchtest run --provider bedrock --model us.anthropic.claude-sonnet-4-20250514-v1:0
catchtest run --provider anthropic --model claude-sonnet-4-20250514

# Test a specific commit range
catchtest run --base HEAD~3 --target HEAD

# Only look at changes in one file
catchtest run --file src/auth/login.py

# Use the simpler "dodgy diff" workflow (more tests, more noise)
catchtest run --workflow dodgy

# Verbose output with full test code and tracebacks
catchtest run --verbose

# Output as JSON (useful for CI)
catchtest run --format json
```

### Bedrock-specific options

```bash
catchtest run --provider bedrock --aws-region us-west-2 --aws-profile my-profile
```

## Example output

```
CatchTest found 3 potential issue(s)

============================================================

BUG  LIKELY BUG (score: 0.82) -- src/auth/login.py
   Risk: The grace period for expired tokens may have been removed
   Token validation now rejects all expired tokens immediately,
   but the previous behavior allowed a 5-minute grace period.

???  UNCERTAIN (score: 0.31) -- src/api/handler.py
   Risk: Response status code may have changed
   The response status code changed from 200 to 201 for create operations.

OK   LIKELY FALSE POSITIVE (score: -0.61) -- src/utils/cache.py
   Risk: Cache key ordering may have changed
   The cache key ordering changed. [rule: ordering_sensitive]

============================================================
Summary: 1 likely bug(s), 1 uncertain, 1 false positive(s)
Run with --verbose to see test code and full failure traces.
```

## Test generation workflows

**Intent-aware** (default, `--workflow intent`): Three LLM calls — infer what the change is trying to do, identify risks, then generate targeted tests. Higher quality, fewer false positives.

**Dodgy diff** (`--workflow dodgy`): One LLM call — show the LLM the before/after code and ask it to write tests that distinguish them. More tests, but noisier.

**Both** (`--workflow both`): Run both workflows and combine results.

## Supported providers

| Provider | Flag | Auth |
|----------|------|------|
| Anthropic | `--provider anthropic` | `ANTHROPIC_API_KEY` env var |
| Amazon Bedrock | `--provider bedrock` | AWS CLI credentials / env vars / IAM role |
| OpenAI | `--provider openai` | `OPENAI_API_KEY` env var |
| Ollama | `--provider ollama` | Local, no auth needed |

## Development

```bash
pip install -e ".[dev]"
pytest
```
