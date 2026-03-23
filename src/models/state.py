from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Optional

from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from src.models.project import FileSpec, ProjectPlan
from src.models.messages import Question, Answer, ReviewFeedback, QualityScore


class Phase(str, Enum):
    INIT = "init"
    ANALYZING = "analyzing"
    CLARIFYING = "clarifying"
    ARCHITECTING = "architecting"
    APPROVING_ARCH = "approving_architecture"
    CODING = "coding"
    REVIEWING = "reviewing"
    TESTING = "testing"
    DELIVERING = "delivering"
    DONE = "done"
    ERROR = "error"


class ProjectState(BaseModel):
    """Central state object that flows through the LangGraph graph."""

    task_id: str = ""
    phase: Phase = Phase.INIT

    # Input
    md_content: str = ""
    user_answers: list[Answer] = Field(default_factory=list)
    architecture_approved: bool = False
    architecture_feedback: str = ""

    # Analysis
    parsed_requirements: str = ""
    clarification_questions: list[Question] = Field(default_factory=list)
    needs_clarification: bool = False

    # Architecture
    project_plan: Optional[ProjectPlan] = None

    # Code generation
    generated_files: list[FileSpec] = Field(default_factory=list)
    current_file_index: int = 0
    files_in_progress: list[str] = Field(default_factory=list)

    # Review
    review_feedback: list[ReviewFeedback] = Field(default_factory=list)
    quality_scores: list[QualityScore] = Field(default_factory=list)
    review_iteration: int = 0

    # Testing
    test_results: str = ""
    tests_passed: bool = False
    lint_errors: list[str] = Field(default_factory=list)

    # Delivery
    output_path: str = ""
    archive_path: str = ""
    git_log: str = ""

    # Tracking
    llm_calls_count: int = 0
    total_cost_usd: float = 0.0
    errors: list[str] = Field(default_factory=list)

    # Messages for LangGraph (chat history)
    messages: Annotated[list, add_messages] = Field(default_factory=list)
