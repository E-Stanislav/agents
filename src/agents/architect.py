from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.knowledge_base.rag import KnowledgeBase
from src.llm import registry
from src.models.project import (
    ArchitectureDecision,
    DependencyNode,
    FileSpec,
    ProjectPlan,
)
from src.models.state import Phase, ProjectState
from src.observability.tracing import get_langfuse_handler

logger = logging.getLogger(__name__)

_kb = KnowledgeBase()


def _load_prompt() -> str:
    prompt_path = settings.prompts_dir / "architect.md"
    return prompt_path.read_text(encoding="utf-8")


async def design_architecture(state: ProjectState) -> dict:
    """Design the project architecture and produce a detailed plan."""
    logger.info("Architect: designing architecture for task %s", state.task_id)

    llm = registry.get_llm("architect")
    system_prompt = _load_prompt()

    callbacks = []
    handler = get_langfuse_handler(task_id=state.task_id, agent_name="architect")
    if handler:
        callbacks.append(handler)

    # Gather RAG context
    rag_context = ""
    try:
        parsed = json.loads(state.parsed_requirements) if state.parsed_requirements else {}
        tech_hints = parsed.get("tech_stack_hints", {})
        stack_values = [v for v in tech_hints.values() if v]
        if stack_values:
            templates = await _kb.search_templates(
                parsed.get("project_type", "web_app"),
                stack_values,
            )
            if templates:
                rag_context = "\n\n## Relevant Templates from Knowledge Base\n"
                for doc in templates:
                    rag_context += f"\n### {doc.metadata.get('template_name', 'template')} - {doc.metadata.get('file_path', '')}\n```\n{doc.page_content[:2000]}\n```\n"
    except Exception:
        logger.debug("RAG context retrieval failed, continuing without it", exc_info=True)

    user_msg = f"""## Requirements Analysis
{state.parsed_requirements}

## User Answers
{json.dumps([a.model_dump() for a in state.user_answers], ensure_ascii=False, indent=2) if state.user_answers else "No clarification was needed."}

{f"## User Feedback on Previous Architecture\n{state.architecture_feedback}" if state.architecture_feedback else ""}
{rag_context}"""

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ],
        config={"callbacks": callbacks},
    )

    try:
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        result = json.loads(content)
    except (json.JSONDecodeError, IndexError):
        logger.error("Architect: failed to parse JSON response")
        return {
            "phase": Phase.ERROR,
            "errors": state.errors + ["Architect failed to produce valid JSON plan"],
            "llm_calls_count": state.llm_calls_count + 1,
        }

    files = [
        FileSpec(
            path=f["path"],
            description=f.get("description", ""),
            language=f.get("language", ""),
            dependencies=f.get("dependencies", []),
        )
        for f in result.get("files", [])
    ]

    dep_graph = [
        DependencyNode(
            file_path=d["file_path"],
            depends_on=d.get("depends_on", []),
            priority=d.get("priority", 0),
        )
        for d in result.get("dependency_graph", [])
    ]

    arch_decisions = [
        ArchitectureDecision(
            area=a["area"],
            choice=a["choice"],
            rationale=a.get("rationale", ""),
        )
        for a in result.get("architecture_decisions", [])
    ]

    plan = ProjectPlan(
        project_name=result.get("project_name", "project"),
        description=result.get("description", ""),
        tech_stack=result.get("tech_stack", {}),
        architecture_decisions=arch_decisions,
        files=files,
        dependency_graph=dep_graph,
        package_dependencies=result.get("package_dependencies", {}),
        docker_base_image=result.get("docker_base_image", "node:20-slim"),
        setup_commands=result.get("setup_commands", []),
        test_commands=result.get("test_commands", []),
        lint_commands=result.get("lint_commands", []),
    )

    return {
        "phase": Phase.APPROVING_ARCH,
        "project_plan": plan,
        "llm_calls_count": state.llm_calls_count + 1,
    }
