"""LLM configuration models."""

from __future__ import annotations

from pydantic import BaseModel


class LLMConfig(BaseModel):
    """Resolved model configuration for a single LLM request path."""

    provider: str = "openai"
    model: str = "gpt-5"
    temperature: float = 0.0
    max_tokens: int = 4096
