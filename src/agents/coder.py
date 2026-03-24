from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.knowledge_base.rag import KnowledgeBase
from src.llm import registry
from src.models.project import FileSpec
from src.models.state import Phase, ProjectState
from src.observability.tracing import get_langfuse_handler

logger = logging.getLogger(__name__)

_kb = KnowledgeBase()


def _load_prompt() -> str:
    prompt_path = settings.prompts_dir / "coder.md"
    return prompt_path.read_text(encoding="utf-8")


def _get_generation_order(state: ProjectState) -> list[list[FileSpec]]:
    """Group files by priority level for parallel generation (fan-out)."""
    if not state.project_plan:
        return []

    dep_map = {
        d.file_path: d.priority for d in state.project_plan.dependency_graph
    }

    file_map = {f.path: f for f in state.project_plan.files}
    max_priority = max(dep_map.values()) if dep_map else 0

    levels: list[list[FileSpec]] = []
    for p in range(max_priority + 1):
        level_files = [
            file_map[path]
            for path, priority in dep_map.items()
            if priority == p and path in file_map
        ]
        if level_files:
            levels.append(level_files)

    # Add any files not in the dependency graph
    graphed = set(dep_map.keys())
    ungraphed = [f for f in state.project_plan.files if f.path not in graphed]
    if ungraphed:
        if levels:
            levels[0].extend(ungraphed)
        else:
            levels.append(ungraphed)

    return levels


async def _generate_single_file(
    file_spec: FileSpec,
    state: ProjectState,
    system_prompt: str,
    generated_so_far: dict[str, str],
) -> FileSpec:
    """Generate code for a single file."""
    llm = registry.get_llm("coder")

    callbacks = []
    handler = get_langfuse_handler(task_id=state.task_id, agent_name="coder")
    if handler:
        callbacks.append(handler)

    # Gather dependency file contents
    dep_context = ""
    for dep_path in file_spec.dependencies:
        if dep_path in generated_so_far:
            dep_context += f"\n### {dep_path}\n```\n{generated_so_far[dep_path]}\n```\n"

    # RAG context for the technology
    rag_context = ""
    try:
        if state.project_plan and file_spec.language:
            stack_str = ", ".join(state.project_plan.tech_stack.values())
            docs = await _kb.search_docs(stack_str, file_spec.description[:100])
            if docs:
                rag_context = "\n\n## Релевантная документация\n"
                for doc in docs[:3]:
                    rag_context += f"\n{doc.page_content[:1500]}\n"
    except Exception:
        pass

    # Review feedback from previous iterations
    feedback_context = ""
    relevant_feedback = [
        fb for fb in state.review_feedback if fb.file_path == file_spec.path
    ]
    if relevant_feedback:
        fb = relevant_feedback[-1]
        feedback_context = f"""
## Обратная связь от ревью (итерация {state.review_iteration})
Проблемы для исправления:
{chr(10).join(f"- {issue}" for issue in fb.issues)}

Рекомендации:
{chr(10).join(f"- {s}" for s in fb.suggestions)}
"""

    plan_json = state.project_plan.model_dump_json(indent=2) if state.project_plan else "{}"

    user_msg = f"""## План проекта
{plan_json}

## Файл для генерации
- **Путь**: {file_spec.path}
- **Язык**: {file_spec.language}
- **Описание**: {file_spec.description}
- **Зависимости**: {', '.join(file_spec.dependencies) or 'нет'}

## Содержимое файлов-зависимостей
{dep_context or "Зависимостей нет."}
{rag_context}
{feedback_context}

Сгенерируй полное содержимое файла `{file_spec.path}` сейчас."""

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ],
        config={"callbacks": callbacks},
    )

    content = response.content.strip()
    # Strip markdown fences if the model wrapped the output
    if content.startswith("```"):
        lines = content.split("\n")
        lines = lines[1:]  # remove opening fence
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines)

    return FileSpec(
        path=file_spec.path,
        description=file_spec.description,
        content=content,
        language=file_spec.language,
        dependencies=file_spec.dependencies,
        generated=True,
    )


async def generate_code(state: ProjectState) -> dict:
    """Generate all project files using fan-out parallel generation."""
    logger.info("Coder: generating code for task %s", state.task_id)

    system_prompt = _load_prompt()
    levels = _get_generation_order(state)

    generated_files: list[FileSpec] = []
    generated_map: dict[str, str] = {}

    # Preserve already-generated files that passed review
    for f in state.generated_files:
        if f.review_passed:
            generated_files.append(f)
            generated_map[f.path] = f.content

    total_calls = state.llm_calls_count

    for level in levels:
        # Filter out files that already passed review
        to_generate = [f for f in level if f.path not in generated_map]
        if not to_generate:
            continue

        logger.info(
            "Coder: generating %d files in parallel (priority level)",
            len(to_generate),
        )

        tasks = [
            _generate_single_file(f, state, system_prompt, generated_map)
            for f in to_generate
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.error("Coder: file generation failed: %s", result)
                continue
            generated_files.append(result)
            generated_map[result.path] = result.content
            total_calls += 1

    return {
        "phase": Phase.REVIEWING,
        "generated_files": generated_files,
        "llm_calls_count": total_calls,
    }
