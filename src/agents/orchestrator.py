from __future__ import annotations

import logging
import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from src.models.messages import Answer
from src.models.state import Phase, ProjectState

from src.agents.analyst import analyze_requirements
from src.agents.architect import design_architecture
from src.agents.coder import generate_code
from src.agents.reviewer import review_code
from src.agents.tester import run_tests
from src.agents.delivery import deliver_project

logger = logging.getLogger(__name__)


# ── Node wrappers ──────────────────────────────────────────────────


async def init_node(state: ProjectState) -> dict:
    """Initialize the task."""
    task_id = state.task_id or str(uuid.uuid4())[:8]
    logger.info("Orchestrator: starting task %s", task_id)
    return {"task_id": task_id, "phase": Phase.ANALYZING}


async def analyze_node(state: ProjectState) -> dict:
    """Run the Analyst agent."""
    return await analyze_requirements(state)


async def clarify_node(state: ProjectState) -> dict:
    """Interrupt the graph to ask the user clarification questions.

    Uses LangGraph's ``interrupt()`` to pause execution and wait
    for user answers via ``Command(resume=...)``.
    """
    questions_data = [q.model_dump() for q in state.clarification_questions]
    logger.info("Orchestrator: interrupting for %d clarification questions", len(questions_data))

    user_response = interrupt({
        "type": "clarification",
        "questions": questions_data,
    })

    # user_response is expected to be a list of {"question_id": ..., "answer": ...}
    answers = []
    if isinstance(user_response, list):
        answers = [Answer(**a) for a in user_response]
    elif isinstance(user_response, dict) and "answers" in user_response:
        answers = [Answer(**a) for a in user_response["answers"]]

    return {
        "user_answers": answers,
        "needs_clarification": False,
        "phase": Phase.ARCHITECTING,
    }


async def architect_node(state: ProjectState) -> dict:
    """Run the Architect agent."""
    return await design_architecture(state)


async def approve_arch_node(state: ProjectState) -> dict:
    """Interrupt to let the user approve or modify the architecture plan."""
    plan_summary = ""
    if state.project_plan:
        plan_summary = {
            "project_name": state.project_plan.project_name,
            "description": state.project_plan.description,
            "tech_stack": state.project_plan.tech_stack,
            "files_count": len(state.project_plan.files),
            "architecture_decisions": [
                d.model_dump() for d in state.project_plan.architecture_decisions
            ],
            "files": [
                {"path": f.path, "description": f.description}
                for f in state.project_plan.files
            ],
        }

    logger.info("Orchestrator: interrupting for architecture approval")

    user_response = interrupt({
        "type": "architecture_approval",
        "plan": plan_summary,
    })

    approved = False
    feedback = ""

    if isinstance(user_response, dict):
        approved = user_response.get("approved", False)
        feedback = user_response.get("feedback", "")
    elif isinstance(user_response, bool):
        approved = user_response
    elif isinstance(user_response, str):
        approved = user_response.lower() in ("yes", "true", "ok", "approve", "approved")
        if not approved:
            feedback = user_response

    if approved:
        return {
            "architecture_approved": True,
            "phase": Phase.CODING,
        }
    else:
        return {
            "architecture_approved": False,
            "architecture_feedback": feedback,
            "phase": Phase.ARCHITECTING,
        }


async def code_node(state: ProjectState) -> dict:
    """Run the Coder agent (parallel file generation)."""
    return await generate_code(state)


async def review_node(state: ProjectState) -> dict:
    """Run the Reviewer agent (Actor-Critic pattern)."""
    return await review_code(state)


async def test_node(state: ProjectState) -> dict:
    """Run the Tester agent in a Docker sandbox."""
    return await run_tests(state)


async def deliver_node(state: ProjectState) -> dict:
    """Run the Delivery agent."""
    return await deliver_project(state)


async def error_node(state: ProjectState) -> dict:
    """Handle errors."""
    logger.error("Orchestrator: task %s ended with errors: %s", state.task_id, state.errors)
    return {"phase": Phase.ERROR}


# ── Routing functions ──────────────────────────────────────────────


def route_after_analysis(state: ProjectState) -> str:
    if state.phase == Phase.CLARIFYING and state.needs_clarification:
        return "clarify"
    return "architect"


def route_after_arch_approval(state: ProjectState) -> str:
    if state.architecture_approved:
        return "code"
    return "architect"


def route_after_review(state: ProjectState) -> str:
    if state.phase == Phase.CODING:
        return "code"
    return "test"


def route_after_test(state: ProjectState) -> str:
    if state.phase == Phase.CODING:
        return "code"
    return "deliver"


def route_after_architect(state: ProjectState) -> str:
    if state.phase == Phase.ERROR:
        return "error"
    return "approve_arch"


# ── Graph construction ─────────────────────────────────────────────


def build_graph() -> StateGraph:
    """Build the main LangGraph state graph for project generation."""

    graph = StateGraph(ProjectState)

    graph.add_node("init", init_node)
    graph.add_node("analyze", analyze_node)
    graph.add_node("clarify", clarify_node)
    graph.add_node("architect", architect_node)
    graph.add_node("approve_arch", approve_arch_node)
    graph.add_node("code", code_node)
    graph.add_node("review", review_node)
    graph.add_node("test", test_node)
    graph.add_node("deliver", deliver_node)
    graph.add_node("error", error_node)

    graph.set_entry_point("init")

    graph.add_edge("init", "analyze")
    graph.add_conditional_edges("analyze", route_after_analysis, {
        "clarify": "clarify",
        "architect": "architect",
    })
    graph.add_edge("clarify", "architect")
    graph.add_conditional_edges("architect", route_after_architect, {
        "approve_arch": "approve_arch",
        "error": "error",
    })
    graph.add_conditional_edges("approve_arch", route_after_arch_approval, {
        "code": "code",
        "architect": "architect",
    })
    graph.add_edge("code", "review")
    graph.add_conditional_edges("review", route_after_review, {
        "code": "code",
        "test": "test",
    })
    graph.add_conditional_edges("test", route_after_test, {
        "code": "code",
        "deliver": "deliver",
    })
    graph.add_edge("deliver", END)
    graph.add_edge("error", END)

    return graph


def compile_graph(checkpointer=None):
    """Compile the graph with an optional checkpointer."""
    graph = build_graph()
    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


async def run_project_generation(
    md_content: str,
    task_id: str | None = None,
    thread_id: str | None = None,
) -> ProjectState:
    """Run the full project generation pipeline (non-interactive mode).

    For interactive mode (with interrupt/resume), use the compiled
    graph directly via the API layer.
    """
    app = compile_graph()
    tid = task_id or str(uuid.uuid4())[:8]
    config = {"configurable": {"thread_id": thread_id or tid}}

    initial_state = ProjectState(
        task_id=tid,
        md_content=md_content,
    )

    final_state = None
    async for event in app.astream(initial_state, config=config):
        for node_name, node_output in event.items():
            logger.info("Node '%s' completed", node_name)
            if isinstance(node_output, dict):
                final_state = node_output

    return final_state
