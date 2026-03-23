from __future__ import annotations

import json
import logging
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.llm import registry
from src.models.messages import Question
from src.models.state import Phase, ProjectState
from src.observability.tracing import get_langfuse_handler

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    prompt_path = settings.prompts_dir / "analyst.md"
    return prompt_path.read_text(encoding="utf-8")


async def analyze_requirements(state: ProjectState) -> dict:
    """Analyze the MD requirements and produce clarification questions."""
    logger.info("Analyst: analyzing requirements for task %s", state.task_id)

    llm = registry.get_llm("analyst")
    system_prompt = _load_prompt()

    callbacks = []
    handler = get_langfuse_handler(task_id=state.task_id, agent_name="analyst")
    if handler:
        callbacks.append(handler)

    user_context = state.md_content
    if state.user_answers:
        answers_text = "\n".join(
            f"Q: {a.question_id} -> A: {a.answer}" for a in state.user_answers
        )
        user_context += f"\n\n## User Answers to Previous Questions\n{answers_text}"

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_context),
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
        logger.error("Analyst: failed to parse JSON response")
        return {
            "phase": Phase.ARCHITECTING,
            "parsed_requirements": response.content,
            "needs_clarification": False,
            "clarification_questions": [],
            "llm_calls_count": state.llm_calls_count + 1,
        }

    questions = [
        Question(
            id=q.get("id", f"q{i}"),
            question=q["question"],
            context=q.get("context", ""),
            options=q.get("options", []),
        )
        for i, q in enumerate(result.get("questions", []))
    ]

    needs_clarification = result.get("needs_clarification", False) and len(questions) > 0

    return {
        "phase": Phase.CLARIFYING if needs_clarification else Phase.ARCHITECTING,
        "parsed_requirements": json.dumps(result, ensure_ascii=False, indent=2),
        "needs_clarification": needs_clarification,
        "clarification_questions": questions,
        "llm_calls_count": state.llm_calls_count + 1,
    }
