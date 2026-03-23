from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://agents:agents@postgres:5432/agents"
    redis_url: str = "redis://redis:6379/0"
    chromadb_host: str = "chromadb"
    chromadb_port: int = 8000  # порт HTTP внутри контейнера Chroma (см. CHROMADB_INTERNAL_PORT)
    langfuse_host: str = "http://langfuse:3000"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    llm_config_path: str = "/app/llm_config.yaml"
    log_level: str = "INFO"
    max_concurrent_tasks: int = 5

    # Sandbox limits
    sandbox_cpu_limit: float = 2.0
    sandbox_memory_limit: str = "2g"
    sandbox_disk_limit: str = "1g"
    sandbox_network_whitelist: list[str] = [
        "registry.npmjs.org",
        "pypi.org",
        "files.pythonhosted.org",
        "deb.debian.org",
        "archive.ubuntu.com",
    ]

    # Timeouts (seconds)
    timeout_analysis: int = 120
    timeout_architecture: int = 180
    timeout_code_per_file: int = 300
    timeout_testing: int = 600
    timeout_total: int = 1800

    # Project limits
    max_files_per_project: int = 50
    max_project_size_kb: int = 500
    max_llm_calls_per_task: int = 100
    max_budget_per_task_usd: float = 5.0

    # Review
    max_review_iterations: int = 3
    min_quality_score: float = 7.0

    base_dir: Path = Path("/app")

    @property
    def tasks_dir(self) -> Path:
        return self.base_dir / "tasks"

    @property
    def output_dir(self) -> Path:
        return self.base_dir / "output"

    @property
    def templates_dir(self) -> Path:
        return self.base_dir / "templates"

    @property
    def prompts_dir(self) -> Path:
        return self.base_dir / "src" / "prompts"

    model_config = {"env_prefix": "", "case_sensitive": False}


def get_settings() -> Settings:
    return Settings()


settings = get_settings()
