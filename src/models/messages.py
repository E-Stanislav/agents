from __future__ import annotations

from pydantic import BaseModel, Field


class Question(BaseModel):
    """A clarification question from the Analyst agent."""

    id: str
    question: str
    context: str = ""
    options: list[str] = Field(default_factory=list)


class Answer(BaseModel):
    """User's answer to a clarification question."""

    question_id: str
    answer: str


class ReviewFeedback(BaseModel):
    """Feedback from the Reviewer agent on a specific file."""

    file_path: str
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    passed: bool = False


class QualityScore(BaseModel):
    """Quality assessment from the Reviewer agent."""

    file_path: str
    correctness: float = 0.0
    security: float = 0.0
    requirements_match: float = 0.0
    code_style: float = 0.0
    overall: float = 0.0
    iteration: int = 0
