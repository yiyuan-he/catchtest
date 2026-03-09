"""Unified LLM client abstraction for CatchTest.

Supports: anthropic, bedrock, openai, ollama.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from catchtest.config import LLMConfig


class LLMClient(ABC):
    """Unified interface for LLM calls across providers."""

    @abstractmethod
    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        """Send a completion request, return the response text."""
        ...


class AnthropicClient(LLMClient):
    """Client using the Anthropic SDK directly."""

    def __init__(self, config: LLMConfig) -> None:
        import anthropic

        api_key = os.environ.get(config.api_key_env)
        if not api_key:
            raise RuntimeError(
                f"Anthropic API key not found. Set the {config.api_key_env} "
                "environment variable."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = config.model

    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        return response.content[0].text


class BedrockClient(LLMClient):
    """Client using AWS Bedrock via boto3's converse API."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            import boto3
        except ImportError:
            raise RuntimeError(
                "boto3 is required for Bedrock provider. "
                "Install it with: pip install 'catchtest[bedrock]'"
            )

        session_kwargs: dict = {}
        if config.aws_profile:
            session_kwargs["profile_name"] = config.aws_profile
        if config.aws_region:
            session_kwargs["region_name"] = config.aws_region

        try:
            session = boto3.Session(**session_kwargs)
            self._client = session.client("bedrock-runtime")
        except Exception as e:
            raise RuntimeError(
                f"Failed to create Bedrock client: {e}\n"
                "Ensure AWS credentials are configured. Run `aws configure` "
                "or set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
            )

        self._model_id = config.model

    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        # Build converse API request
        converse_messages = []
        for msg in messages:
            converse_messages.append({
                "role": msg["role"],
                "content": [{"text": msg["content"]}],
            })

        inference_config: dict = {
            "maxTokens": max_tokens,
            "temperature": temperature,
        }

        kwargs: dict = {
            "modelId": self._model_id,
            "messages": converse_messages,
            "inferenceConfig": inference_config,
        }
        if system:
            kwargs["system"] = [{"text": system}]

        try:
            response = self._client.converse(**kwargs)
        except Exception as e:
            raise RuntimeError(f"Bedrock API call failed: {e}")

        return response["output"]["message"]["content"][0]["text"]


class OpenAIClient(LLMClient):
    """Client using the OpenAI SDK."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai package is required for OpenAI provider. "
                "Install it with: pip install openai"
            )

        api_key = os.environ.get(config.api_key_env, os.environ.get("OPENAI_API_KEY"))
        if not api_key:
            raise RuntimeError(
                "OpenAI API key not found. Set the OPENAI_API_KEY environment variable."
            )
        self._client = openai.OpenAI(api_key=api_key)
        self._model = config.model

    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content


class OllamaClient(LLMClient):
    """Client for Ollama (local LLM) via its OpenAI-compatible API."""

    def __init__(self, config: LLMConfig) -> None:
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai package is required for Ollama provider "
                "(uses OpenAI-compatible API). Install it with: pip install openai"
            )

        base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        self._client = openai.OpenAI(api_key="ollama", base_url=base_url)
        self._model = config.model

    def complete(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> str:
        oai_messages = []
        if system:
            oai_messages.append({"role": "system", "content": system})
        oai_messages.extend(messages)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=oai_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content


def create_client(config: LLMConfig) -> LLMClient:
    """Factory that returns the right client based on config.llm.provider."""
    provider = config.provider.lower()

    if provider == "anthropic":
        return AnthropicClient(config)
    elif provider == "bedrock":
        return BedrockClient(config)
    elif provider == "openai":
        return OpenAIClient(config)
    elif provider == "ollama":
        return OllamaClient(config)
    else:
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            "Supported providers: anthropic, bedrock, openai, ollama"
        )
