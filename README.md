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

**From GitHub:**
```bash
pip install "catchtest @ git+https://github.com/yourorg/catchtest.git"

# With Amazon Bedrock support:
pip install "catchtest[bedrock] @ git+https://github.com/yourorg/catchtest.git"

# Update to the latest version:
pip install --upgrade "catchtest[bedrock] @ git+https://github.com/yourorg/catchtest.git"
```

**For development (editable install):**
```bash
git clone https://github.com/yourorg/catchtest.git
cd catchtest
pip install -e ".[bedrock]"
# Then just `git pull` to get updates
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

# Output as JSON or Markdown (useful for CI / reports)
catchtest run --format json
catchtest run --format markdown

# Use runtime telemetry to improve risk analysis (see Telemetry section below)
catchtest run --telemetry-db /path/to/telemetry.db
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

## Runtime telemetry integration

CatchTest can use production telemetry data to improve its risk analysis and bug classification. When provided with a telemetry database, the LLM gets runtime context like traffic volume, exception rates, latency, and incident history for the functions being changed — signals that static analysis alone cannot provide.

```bash
catchtest run --base HEAD~1 --target HEAD --telemetry-db /path/to/telemetry.db
```

The telemetry database is a SQLite file with tables for function mappings, call metrics, endpoint traffic, and incident snapshots. This data can be populated from ADOT/Application Signals auto-instrumentation or any OpenTelemetry-compatible pipeline.

In our benchmarks, adding telemetry context (~0.4% of the input token budget) improved bug detection precision from 44% to 67% and reduced cost per catch by 27%.

## Development

```bash
pip install -e ".[dev]"
pytest
```
