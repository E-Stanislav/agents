from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DependencyNode(BaseModel):
    """A node in the file dependency graph."""

    file_path: str
    depends_on: list[str] = Field(default_factory=list)
    priority: int = 0  # lower = generate first


class FileSpec(BaseModel):
    """Specification for a single file to generate."""

    path: str
    description: str = ""
    content: str = ""
    language: str = ""
    dependencies: list[str] = Field(default_factory=list)
    generated: bool = False
    reviewed: bool = False
    review_passed: bool = False


class ArchitectureDecision(BaseModel):
    """A single architectural decision."""

    area: str  # e.g. "database", "auth", "frontend"
    choice: str
    rationale: str


class ProjectPlan(BaseModel):
    """Full project plan produced by the Architect agent."""

    project_name: str = ""
    description: str = ""
    tech_stack: dict[str, str] = Field(default_factory=dict)
    architecture_decisions: list[ArchitectureDecision] = Field(default_factory=list)
    files: list[FileSpec] = Field(default_factory=list)
    dependency_graph: list[DependencyNode] = Field(default_factory=list)
    package_dependencies: dict[str, list[str]] = Field(default_factory=dict)
    docker_base_image: str = "node:20-slim"
    setup_commands: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    lint_commands: list[str] = Field(default_factory=list)
