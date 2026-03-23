from __future__ import annotations

import logging

from src.config import settings
from src.models.state import Phase, ProjectState
from src.sandbox.executor import SandboxExecutor

logger = logging.getLogger(__name__)


async def run_tests(state: ProjectState) -> dict:
    """Write files into a sandbox, run linters and tests."""
    logger.info("Tester: running tests for task %s", state.task_id)

    if not state.project_plan:
        return {
            "phase": Phase.DELIVERING,
            "tests_passed": True,
            "test_results": "No project plan — skipping tests",
        }

    executor = SandboxExecutor()

    try:
        await executor.setup(state.project_plan, state.task_id)
        await executor.write_files(state.generated_files)

        # Run linters
        lint_passed, lint_errors = await executor.run_lint(
            state.project_plan.lint_commands
        )

        # Run tests
        tests_passed, test_output = await executor.run_tests(
            state.project_plan.test_commands
        )

        all_passed = lint_passed and tests_passed

        if not all_passed and state.review_iteration < settings.max_review_iterations:
            logger.info("Tester: failures detected, sending back to Coder")
            return {
                "phase": Phase.CODING,
                "tests_passed": False,
                "test_results": test_output,
                "lint_errors": lint_errors,
            }

        return {
            "phase": Phase.DELIVERING,
            "tests_passed": all_passed,
            "test_results": test_output,
            "lint_errors": lint_errors,
        }

    except Exception as e:
        logger.error("Tester: sandbox execution failed: %s", e)
        return {
            "phase": Phase.DELIVERING,
            "tests_passed": False,
            "test_results": f"Sandbox error: {e}",
            "errors": state.errors + [f"Test sandbox error: {e}"],
        }
    finally:
        await executor.teardown()
