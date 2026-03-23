from __future__ import annotations

from src.config import settings
from src.models.project import FileSpec


class ValidationError(Exception):
    pass


def validate_md_input(content: str) -> None:
    """Validate the input MD file content."""
    if not content or not content.strip():
        raise ValidationError("MD content is empty")
    if len(content) > 100_000:
        raise ValidationError("MD content exceeds 100KB limit")


def validate_project_size(files: list[FileSpec]) -> None:
    """Validate that the generated project doesn't exceed size limits."""
    if len(files) > settings.max_files_per_project:
        raise ValidationError(
            f"Project has {len(files)} files, "
            f"exceeding limit of {settings.max_files_per_project}"
        )

    total_size = sum(len(f.content.encode("utf-8")) for f in files if f.content)
    max_bytes = settings.max_project_size_kb * 1024
    if total_size > max_bytes:
        raise ValidationError(
            f"Project size {total_size // 1024}KB "
            f"exceeds limit of {settings.max_project_size_kb}KB"
        )
