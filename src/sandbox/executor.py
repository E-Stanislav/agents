from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from docker.models.containers import Container

from src.config import settings
from src.models.project import FileSpec, ProjectPlan
from src.sandbox.docker_sandbox import DockerSandbox

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """High-level interface for running project operations in a sandbox."""

    def __init__(self) -> None:
        self.sandbox = DockerSandbox()
        self._container: Optional[Container] = None
        self._task_id: str = ""

    async def setup(self, plan: ProjectPlan, task_id: str) -> None:
        """Create a sandbox container and install dependencies."""
        self._task_id = task_id
        self._container = await self.sandbox.create_container(
            image=plan.docker_base_image,
            task_id=task_id,
        )
        for cmd in plan.setup_commands:
            exit_code, output = await self.sandbox.exec_command(
                self._container, cmd, timeout=settings.timeout_testing,
            )
            if exit_code != 0:
                logger.warning("Setup command failed: %s\n%s", cmd, output)

    async def write_files(self, files: list[FileSpec]) -> None:
        """Write generated files into the sandbox."""
        if not self._container:
            raise RuntimeError("Sandbox not initialized")
        for f in files:
            if f.content:
                parent = str(Path(f.path).parent)
                if parent and parent != ".":
                    await self.sandbox.exec_command(
                        self._container, f"mkdir -p {parent}"
                    )
                await self.sandbox.write_file(self._container, f.path, f.content)

    async def run_lint(self, commands: list[str]) -> tuple[bool, list[str]]:
        """Run lint commands and return (passed, errors)."""
        if not self._container:
            raise RuntimeError("Sandbox not initialized")
        errors: list[str] = []
        for cmd in commands:
            exit_code, output = await self.sandbox.exec_command(
                self._container, cmd, timeout=settings.timeout_testing,
            )
            if exit_code != 0:
                errors.append(f"[{cmd}] {output}")
        return len(errors) == 0, errors

    async def run_tests(self, commands: list[str]) -> tuple[bool, str]:
        """Run test commands and return (passed, output)."""
        if not self._container:
            raise RuntimeError("Sandbox not initialized")
        outputs: list[str] = []
        all_passed = True
        for cmd in commands:
            exit_code, output = await self.sandbox.exec_command(
                self._container, cmd, timeout=settings.timeout_testing,
            )
            outputs.append(f"$ {cmd}\n{output}")
            if exit_code != 0:
                all_passed = False
        return all_passed, "\n\n".join(outputs)

    async def copy_output(self, dest_dir: Path) -> None:
        """Copy workspace from sandbox to output directory."""
        if not self._container:
            raise RuntimeError("Sandbox not initialized")
        await self.sandbox.copy_out(self._container, dest_dir)

    async def teardown(self) -> None:
        """Destroy the sandbox container."""
        if self._container:
            await self.sandbox.destroy(self._container)
            self._container = None
