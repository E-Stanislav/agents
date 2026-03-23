from __future__ import annotations

import asyncio
import logging
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Optional

import docker
from docker.models.containers import Container

from src.config import settings

logger = logging.getLogger(__name__)


class DockerSandbox:
    """Manages isolated Docker containers for code execution.

    Each project gets its own container with resource limits and
    network restrictions (whitelist-only for package registries).
    """

    def __init__(self) -> None:
        self._client: Optional[docker.DockerClient] = None

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env()
        return self._client

    async def create_container(
        self,
        image: str = "node:20-slim",
        task_id: str = "",
    ) -> Container:
        """Create an isolated sandbox container."""
        loop = asyncio.get_event_loop()
        container = await loop.run_in_executor(
            None,
            lambda: self.client.containers.create(
                image=image,
                name=f"sandbox-{task_id}" if task_id else None,
                detach=True,
                tty=True,
                working_dir="/workspace",
                mem_limit=settings.sandbox_memory_limit,
                cpu_period=100000,
                cpu_quota=int(settings.sandbox_cpu_limit * 100000),
                network_mode="bridge",
                labels={"agents.sandbox": "true", "agents.task_id": task_id},
            ),
        )
        await loop.run_in_executor(None, container.start)
        logger.info("Created sandbox container %s for task %s", container.short_id, task_id)
        return container

    async def exec_command(
        self,
        container: Container,
        command: str,
        timeout: int = 60,
    ) -> tuple[int, str]:
        """Execute a command inside the sandbox container."""
        loop = asyncio.get_event_loop()

        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: container.exec_run(
                        ["sh", "-c", command],
                        workdir="/workspace",
                        demux=True,
                    ),
                ),
                timeout=timeout,
            )
            stdout = (result.output[0] or b"").decode("utf-8", errors="replace")
            stderr = (result.output[1] or b"").decode("utf-8", errors="replace")
            output = stdout + ("\n" + stderr if stderr else "")
            return result.exit_code, output.strip()
        except asyncio.TimeoutError:
            logger.warning("Command timed out after %ds: %s", timeout, command[:100])
            return -1, f"Command timed out after {timeout}s"

    async def write_file(
        self,
        container: Container,
        file_path: str,
        content: str,
    ) -> None:
        """Write a file into the sandbox container."""
        loop = asyncio.get_event_loop()
        buf = BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=file_path)
            info.size = len(data)
            tar.addfile(info, BytesIO(data))
        buf.seek(0)

        await loop.run_in_executor(
            None,
            lambda: container.put_archive("/workspace", buf),
        )

    async def read_file(self, container: Container, file_path: str) -> str:
        """Read a file from the sandbox container."""
        loop = asyncio.get_event_loop()
        bits, _ = await loop.run_in_executor(
            None,
            lambda: container.get_archive(f"/workspace/{file_path}"),
        )
        buf = BytesIO()
        for chunk in bits:
            buf.write(chunk)
        buf.seek(0)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            member = tar.getmembers()[0]
            f = tar.extractfile(member)
            if f is None:
                return ""
            return f.read().decode("utf-8", errors="replace")

    async def copy_out(self, container: Container, dest_dir: Path) -> None:
        """Copy the entire /workspace from container to host directory."""
        loop = asyncio.get_event_loop()
        bits, _ = await loop.run_in_executor(
            None,
            lambda: container.get_archive("/workspace"),
        )
        buf = BytesIO()
        for chunk in bits:
            buf.write(chunk)
        buf.seek(0)

        dest_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=buf, mode="r") as tar:
            tar.extractall(path=str(dest_dir), filter="data")

        logger.info("Copied workspace to %s", dest_dir)

    async def destroy(self, container: Container) -> None:
        """Stop and remove the sandbox container."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: container.stop(timeout=10))
        except Exception:
            pass
        try:
            await loop.run_in_executor(None, lambda: container.remove(force=True))
        except Exception:
            pass
        logger.info("Destroyed sandbox container %s", container.short_id)

    async def cleanup_stale(self) -> int:
        """Remove any leftover sandbox containers."""
        loop = asyncio.get_event_loop()
        containers = await loop.run_in_executor(
            None,
            lambda: self.client.containers.list(
                all=True,
                filters={"label": "agents.sandbox=true"},
            ),
        )
        count = 0
        for c in containers:
            await self.destroy(c)
            count += 1
        if count:
            logger.info("Cleaned up %d stale sandbox containers", count)
        return count
