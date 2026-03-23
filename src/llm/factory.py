from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

from src.llm.config_models import ProviderConfig, ProviderType

logger = logging.getLogger(__name__)


def _resolve_api_key(raw_key: str) -> str:
    """Resolve ${ENV_VAR} references in api_key values."""
    import os

    if raw_key.startswith("${") and raw_key.endswith("}"):
        env_var = raw_key[2:-1]
        value = os.environ.get(env_var, "")
        if not value:
            logger.warning("Environment variable %s is not set", env_var)
        return value
    return raw_key


def create_chat_model(
    provider_cfg: ProviderConfig,
    model: str,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    **kwargs: Any,
) -> BaseChatModel:
    """Create a LangChain chat model from provider config."""
    api_key = _resolve_api_key(provider_cfg.api_key)

    if provider_cfg.type == ProviderType.OPENAI:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=provider_cfg.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    if provider_cfg.type == ProviderType.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model,
            api_key=api_key,
            base_url=provider_cfg.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    if provider_cfg.type == ProviderType.OPENAI_COMPATIBLE:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url=provider_cfg.base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    raise ValueError(f"Unknown provider type: {provider_cfg.type}")


def create_embedding_model(
    provider_cfg: ProviderConfig,
    model: str,
) -> Embeddings:
    """Create a LangChain embedding model from provider config."""
    api_key = _resolve_api_key(provider_cfg.api_key)

    if provider_cfg.type in (ProviderType.OPENAI, ProviderType.OPENAI_COMPATIBLE):
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=provider_cfg.base_url,
        )

    if provider_cfg.type == ProviderType.ANTHROPIC:
        from langchain_openai import OpenAIEmbeddings

        logger.warning(
            "Anthropic does not provide embeddings natively; "
            "falling back to OpenAI-compatible embedding endpoint at %s",
            provider_cfg.base_url,
        )
        return OpenAIEmbeddings(
            model=model,
            api_key=api_key,
            base_url=provider_cfg.base_url,
        )

    raise ValueError(f"Unknown provider type for embeddings: {provider_cfg.type}")
