from __future__ import annotations

import logging
from typing import Optional

from src.config import settings

logger = logging.getLogger(__name__)

_langfuse_handler = None


def setup_tracing() -> None:
    """Initialize Langfuse tracing if credentials are configured."""
    global _langfuse_handler

    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.info("Langfuse credentials not set, tracing disabled")
        return

    try:
        from langfuse.callback import CallbackHandler

        _langfuse_handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse tracing initialized at %s", settings.langfuse_host)
    except Exception:
        logger.warning("Failed to initialize Langfuse tracing", exc_info=True)


def get_langfuse_handler(
    task_id: str = "",
    agent_name: str = "",
) -> Optional[object]:
    """Return a Langfuse callback handler scoped to a task/agent."""
    if _langfuse_handler is None:
        return None

    try:
        from langfuse.callback import CallbackHandler

        return CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            trace_name=f"{agent_name}:{task_id}" if agent_name else task_id,
            tags=[agent_name] if agent_name else [],
            metadata={"task_id": task_id, "agent": agent_name},
        )
    except Exception:
        return _langfuse_handler
