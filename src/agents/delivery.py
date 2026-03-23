from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tarfile
from io import BytesIO
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.llm import registry
from src.models.project import FileSpec
from src.models.state import Phase, ProjectState
from src.observability.tracing import get_langfuse_handler

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    prompt_path = settings.prompts_dir / "delivery.md"
    return prompt_path.read_text(encoding="utf-8")


async def deliver_project(state: ProjectState) -> dict:
    """Generate delivery files (README, Dockerfile, etc.), init Git, create archive."""
    logger.info("Delivery: packaging project for task %s", state.task_id)

    llm = registry.get_llm("delivery")
    system_prompt = _load_prompt()

    callbacks = []
    handler = get_langfuse_handler(task_id=state.task_id, agent_name="delivery")
    if handler:
        callbacks.append(handler)

    plan_json = state.project_plan.model_dump_json(indent=2) if state.project_plan else "{}"
    file_list = "\n".join(f"- {f.path}" for f in state.generated_files)

    user_msg = f"""## Project Plan
{plan_json}

## Generated Files
{file_list}

## Test Results
{state.test_results or "Tests not run"}

Generate the delivery files now."""

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ],
        config={"callbacks": callbacks},
    )

    # Parse delivery files
    delivery_files: list[FileSpec] = []
    git_commits: list[str] = []

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        result = json.loads(content)

        for f in result.get("files", []):
            delivery_files.append(
                FileSpec(
                    path=f["path"],
                    content=f["content"],
                    generated=True,
                    review_passed=True,
                )
            )
        git_commits = result.get("git_commits", [])
    except (json.JSONDecodeError, IndexError):
        logger.warning("Delivery: failed to parse JSON, generating basic files")
        project_name = state.project_plan.project_name if state.project_plan else "project"
        delivery_files.append(
            FileSpec(
                path="README.md",
                content=f"# {project_name}\n\nGenerated project.\n",
                generated=True,
                review_passed=True,
            )
        )

    all_files = state.generated_files + delivery_files

    # Write to output directory
    project_name = state.project_plan.project_name if state.project_plan else "project"
    output_dir = settings.output_dir / f"{state.task_id}_{project_name}"
    output_dir.mkdir(parents=True, exist_ok=True)

    for f in all_files:
        if not f.content:
            continue
        file_path = output_dir / f.path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f.content, encoding="utf-8")

    # Initialize Git repository
    git_log = ""
    try:
        git_log = await _init_git(output_dir, git_commits)
    except Exception as e:
        logger.warning("Git init failed: %s", e)

    # Create tar.gz archive
    archive_path = settings.output_dir / f"{state.task_id}_{project_name}.tar.gz"
    await _create_archive(output_dir, archive_path)

    return {
        "phase": Phase.DONE,
        "generated_files": all_files,
        "output_path": str(output_dir),
        "archive_path": str(archive_path),
        "git_log": git_log,
        "llm_calls_count": state.llm_calls_count + 1,
    }


async def _init_git(project_dir: Path, commit_messages: list[str]) -> str:
    """Initialize a Git repo and make commits."""
    loop = asyncio.get_event_loop()

    async def run(cmd: str) -> str:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            cwd=str(project_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode() + stderr.decode()

    await run("git init")
    await run("git config user.email 'agents@generator.local'")
    await run("git config user.name 'Project Generator'")

    if commit_messages:
        await run("git add -A")
        msg = commit_messages[0] if commit_messages else "feat: initial project scaffold"
        await run(f'git commit -m "{msg}"')
    else:
        await run("git add -A")
        await run('git commit -m "feat: initial project scaffold"')

    result = await run("git log --oneline")
    return result.strip()


async def _create_archive(source_dir: Path, archive_path: Path) -> None:
    """Create a tar.gz archive of the project directory."""
    loop = asyncio.get_event_loop()

    def _tar():
        with tarfile.open(str(archive_path), "w:gz") as tar:
            tar.add(str(source_dir), arcname=source_dir.name)

    await loop.run_in_executor(None, _tar)
    logger.info("Created archive: %s", archive_path)
