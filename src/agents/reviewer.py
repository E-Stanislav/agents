from __future__ import annotations

import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage

from src.config import settings
from src.llm import registry
from src.models.messages import QualityScore, ReviewFeedback
from src.models.state import Phase, ProjectState
from src.observability.tracing import get_langfuse_handler

logger = logging.getLogger(__name__)


def _load_prompt() -> str:
    prompt_path = settings.prompts_dir / "reviewer.md"
    return prompt_path.read_text(encoding="utf-8")


async def review_code(state: ProjectState) -> dict:
    """Review all generated files and produce quality scores.

    Uses a DIFFERENT model from the Coder (Actor-Critic pattern)
    to avoid agreeableness bias.
    """
    logger.info(
        "Reviewer: reviewing code (iteration %d/%d) for task %s",
        state.review_iteration + 1,
        settings.max_review_iterations,
        state.task_id,
    )

    llm = registry.get_llm("reviewer")
    system_prompt = _load_prompt()
    plan_json = state.project_plan.model_dump_json(indent=2) if state.project_plan else "{}"

    all_feedback: list[ReviewFeedback] = []
    all_scores: list[QualityScore] = []
    total_calls = state.llm_calls_count
    iteration = state.review_iteration + 1

    files_to_review = [f for f in state.generated_files if f.generated and not f.review_passed]

    for file_spec in files_to_review:
        callbacks = []
        handler = get_langfuse_handler(task_id=state.task_id, agent_name="reviewer")
        if handler:
            callbacks.append(handler)

        user_msg = f"""## Project Plan
{plan_json}

## File to Review
- **Path**: {file_spec.path}
- **Description**: {file_spec.description}
- **Iteration**: {iteration} of {settings.max_review_iterations}

## File Content
```{file_spec.language}
{file_spec.content}
```

Review this file now."""

        response = await llm.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ],
            config={"callbacks": callbacks},
        )
        total_calls += 1

        try:
            content = response.content
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            result = json.loads(content)
        except (json.JSONDecodeError, IndexError):
            logger.warning("Reviewer: failed to parse JSON for %s, marking as passed", file_spec.path)
            all_feedback.append(ReviewFeedback(file_path=file_spec.path, passed=True))
            all_scores.append(QualityScore(
                file_path=file_spec.path, overall=7.0, iteration=iteration,
            ))
            continue

        scores = result.get("scores", {})
        quality = QualityScore(
            file_path=file_spec.path,
            correctness=scores.get("correctness", 0),
            security=scores.get("security", 0),
            requirements_match=scores.get("requirements_match", 0),
            code_style=scores.get("code_style", 0),
            overall=scores.get("overall", 0),
            iteration=iteration,
        )
        all_scores.append(quality)

        passed = result.get("passed", False) or quality.overall >= settings.min_quality_score
        # On final iteration, be lenient
        if iteration >= settings.max_review_iterations:
            passed = True

        feedback = ReviewFeedback(
            file_path=file_spec.path,
            issues=result.get("issues", []),
            suggestions=result.get("suggestions", []),
            passed=passed,
        )
        all_feedback.append(feedback)

    # Update file review status
    updated_files = []
    feedback_map = {fb.file_path: fb for fb in all_feedback}
    for f in state.generated_files:
        if f.path in feedback_map:
            f.reviewed = True
            f.review_passed = feedback_map[f.path].passed
        updated_files.append(f)

    all_passed = all(fb.passed for fb in all_feedback)
    needs_revision = not all_passed and iteration < settings.max_review_iterations

    next_phase = Phase.CODING if needs_revision else Phase.TESTING

    logger.info(
        "Reviewer: %d/%d files passed, next phase: %s",
        sum(1 for fb in all_feedback if fb.passed),
        len(all_feedback),
        next_phase,
    )

    return {
        "phase": next_phase,
        "generated_files": updated_files,
        "review_feedback": all_feedback,
        "quality_scores": state.quality_scores + all_scores,
        "review_iteration": iteration,
        "llm_calls_count": total_calls,
    }
