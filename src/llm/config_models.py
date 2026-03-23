from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OPENAI_COMPATIBLE = "openai_compatible"


class ProviderConfig(BaseModel):
    type: ProviderType
    base_url: str
    api_key: str = ""


class FallbackConfig(BaseModel):
    provider: str
    model: str


class AgentLLMConfig(BaseModel):
    provider: str
    model: str
    temperature: float = 0.2
    max_tokens: int = 4096
    fallback: Optional[FallbackConfig] = None


class EmbeddingConfig(BaseModel):
    provider: str
    model: str
    fallback: Optional[FallbackConfig] = None


class DefaultsConfig(BaseModel):
    timeout_seconds: int = 120
    max_retries: int = 3
    retry_delay_seconds: int = 5


class LLMConfigFile(BaseModel):
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)
    agents: dict[str, AgentLLMConfig] = Field(default_factory=dict)
    embedding: Optional[EmbeddingConfig] = None
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
