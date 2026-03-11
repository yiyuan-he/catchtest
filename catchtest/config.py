"""Configuration management for CatchTest."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-20250514",
    "bedrock": "us.anthropic.claude-sonnet-4-6",
    "openai": "gpt-4o",
    "ollama": "llama3",
}


@dataclass
class LLMConfig:
    provider: str = "anthropic"  # anthropic | openai | ollama | bedrock
    model: str = DEFAULT_MODELS["anthropic"]
    api_key_env: str = "ANTHROPIC_API_KEY"
    aws_region: str | None = None
    aws_profile: str | None = None


@dataclass
class TestConfig:
    language: str = "python"
    framework: str = "pytest"
    timeout_seconds: int = 30
    max_tests_per_diff: int = 10


@dataclass
class AssessmentConfig:
    enable_llm_judge: bool = True
    enable_rule_based: bool = True
    fp_threshold: float = -0.5
    tp_threshold: float = 0.5


@dataclass
class OutputConfig:
    verbosity: str = "normal"  # quiet | normal | verbose
    format: str = "terminal"  # terminal | json | markdown


@dataclass
class CatchTestConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    test: TestConfig = field(default_factory=TestConfig)
    assessment: AssessmentConfig = field(default_factory=AssessmentConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    telemetry_db: str | None = None


def _merge_dict_into_dataclass(dc: object, data: dict) -> None:
    """Merge a dict into a dataclass, only setting fields that exist."""
    for key, value in data.items():
        if hasattr(dc, key):
            setattr(dc, key, value)


def load_config(
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> CatchTestConfig:
    """Load config from YAML file and apply CLI overrides.

    Search order for config file:
    1. Explicit config_path argument
    2. .catchtest.yaml in the current directory
    3. Fall back to defaults
    """
    config = CatchTestConfig()
    yaml_set_model = False

    # Find and load YAML config
    if config_path is None:
        config_path = Path.cwd() / ".catchtest.yaml"

    if config_path.exists():
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        if "llm" in raw:
            _merge_dict_into_dataclass(config.llm, raw["llm"])
            yaml_set_model = "model" in raw["llm"]
        if "test" in raw:
            _merge_dict_into_dataclass(config.test, raw["test"])
        if "assessment" in raw:
            _merge_dict_into_dataclass(config.assessment, raw["assessment"])
        if "output" in raw:
            _merge_dict_into_dataclass(config.output, raw["output"])

    # Apply CLI overrides
    if cli_overrides:
        if "provider" in cli_overrides and cli_overrides["provider"] is not None:
            config.llm.provider = cli_overrides["provider"]
        if "model" in cli_overrides and cli_overrides["model"] is not None:
            config.llm.model = cli_overrides["model"]
        if "aws_region" in cli_overrides and cli_overrides["aws_region"] is not None:
            config.llm.aws_region = cli_overrides["aws_region"]
        if "aws_profile" in cli_overrides and cli_overrides["aws_profile"] is not None:
            config.llm.aws_profile = cli_overrides["aws_profile"]
        if "verbose" in cli_overrides and cli_overrides["verbose"]:
            config.output.verbosity = "verbose"
        if "format" in cli_overrides and cli_overrides["format"] is not None:
            config.output.format = cli_overrides["format"]

    # Auto-resolve model if provider was set but model was not explicitly chosen
    cli_set_model = cli_overrides and cli_overrides.get("model") is not None
    if not cli_set_model and not yaml_set_model:
        config.llm.model = DEFAULT_MODELS.get(
            config.llm.provider, DEFAULT_MODELS["anthropic"]
        )

    # Resolve aws_region from environment if not set
    if config.llm.provider == "bedrock" and config.llm.aws_region is None:
        config.llm.aws_region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")

    return config


DEFAULT_CONFIG_YAML = """\
# CatchTest configuration
llm:
  provider: anthropic          # anthropic | openai | ollama | bedrock
  model: claude-sonnet-4-20250514
  api_key_env: ANTHROPIC_API_KEY  # env var name containing the key
  # Bedrock-specific (only used when provider: bedrock):
  # aws_region: us-east-1
  # aws_profile: default

test:
  language: python             # python | javascript | typescript | java
  framework: pytest            # pytest | unittest | jest | vitest | junit
  timeout_seconds: 30          # per-test execution timeout
  max_tests_per_diff: 10       # cap on generated tests

assessment:
  enable_llm_judge: true
  enable_rule_based: true
  fp_threshold: -0.5           # below this score, auto-discard as false positive
  tp_threshold: 0.5            # above this score, flag as likely true positive

output:
  verbosity: normal            # quiet | normal | verbose
  format: terminal             # terminal | json | markdown
"""
