from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings

from src.llm.config_models import LLMConfigFile, ProviderConfig
from src.llm.factory import create_chat_model, create_embedding_model

logger = logging.getLogger(__name__)


class LLMRegistry:
    """Central registry that maps agent names to configured LLM instances.

    Reads ``llm_config.yaml``, builds LangChain chat models with the
    correct ``base_url`` / ``api_key`` / parameters, and wires up
    fallback chains via ``with_fallbacks()``.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config_path = config_path
        self._config: Optional[LLMConfigFile] = None
        self._cache: dict[str, BaseChatModel] = {}
        self._embedding_cache: Optional[Embeddings] = None

    def _load_config(self) -> LLMConfigFile:
        if self._config is not None:
            return self._config

        path = self._config_path
        if path is None:
            import os
            path = os.environ.get("LLM_CONFIG_PATH", "llm_config.yaml")

        config_file = Path(path)
        if not config_file.exists():
            logger.warning("LLM config not found at %s, using empty config", path)
            self._config = LLMConfigFile()
            return self._config

        with open(config_file) as f:
            raw = yaml.safe_load(f)

        self._config = LLMConfigFile.model_validate(raw)
        logger.info(
            "Loaded LLM config: %d providers, %d agents",
            len(self._config.providers),
            len(self._config.agents),
        )
        return self._config

    def _get_provider(self, name: str) -> ProviderConfig:
        cfg = self._load_config()
        if name not in cfg.providers:
            raise KeyError(
                f"Provider '{name}' not found in llm_config.yaml. "
                f"Available: {list(cfg.providers.keys())}"
            )
        return cfg.providers[name]

    def get_llm(self, agent_name: str) -> BaseChatModel:
        """Return a configured chat model for the given agent.

        If a fallback is defined, wraps the primary model with
        ``with_fallbacks()`` so it automatically retries on the
        fallback provider.
        """
        if agent_name in self._cache:
            return self._cache[agent_name]

        cfg = self._load_config()
        if agent_name not in cfg.agents:
            raise KeyError(
                f"Agent '{agent_name}' not found in llm_config.yaml. "
                f"Available: {list(cfg.agents.keys())}"
            )

        agent_cfg = cfg.agents[agent_name]
        provider_cfg = self._get_provider(agent_cfg.provider)

        primary = create_chat_model(
            provider_cfg=provider_cfg,
            model=agent_cfg.model,
            temperature=agent_cfg.temperature,
            max_tokens=agent_cfg.max_tokens,
        )

        if agent_cfg.fallback:
            try:
                fb_provider = self._get_provider(agent_cfg.fallback.provider)
                fallback_llm = create_chat_model(
                    provider_cfg=fb_provider,
                    model=agent_cfg.fallback.model,
                    temperature=agent_cfg.temperature,
                    max_tokens=agent_cfg.max_tokens,
                )
                primary = primary.with_fallbacks([fallback_llm])
                logger.info(
                    "Agent '%s': %s/%s -> fallback %s/%s",
                    agent_name,
                    agent_cfg.provider,
                    agent_cfg.model,
                    agent_cfg.fallback.provider,
                    agent_cfg.fallback.model,
                )
            except Exception:
                logger.warning(
                    "Failed to configure fallback for agent '%s', using primary only",
                    agent_name,
                    exc_info=True,
                )
        else:
            logger.info(
                "Agent '%s': %s/%s (no fallback)",
                agent_name,
                agent_cfg.provider,
                agent_cfg.model,
            )

        self._cache[agent_name] = primary
        return primary

    def get_embedding_model(self) -> Embeddings:
        """Return the configured embedding model for RAG."""
        if self._embedding_cache is not None:
            return self._embedding_cache

        cfg = self._load_config()
        if cfg.embedding is None:
            raise RuntimeError("No embedding config in llm_config.yaml")

        provider_cfg = self._get_provider(cfg.embedding.provider)
        primary = create_embedding_model(provider_cfg, cfg.embedding.model)

        self._embedding_cache = primary
        return primary

    def reload(self) -> None:
        """Force reload of config and clear caches."""
        self._config = None
        self._cache.clear()
        self._embedding_cache = None
        logger.info("LLM registry reloaded")


registry = LLMRegistry()
