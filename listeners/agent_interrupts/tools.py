"""Structured tool builders for agent interrupts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from langchain_core.tools import StructuredTool
from langgraph.types import interrupt

if TYPE_CHECKING:  # pragma: no cover - import for typing only
    from ai.agents.react_agents.all_tools import SlackContext


def create_approval_tool(
    slack_context: Optional["SlackContext"],
) -> StructuredTool:
    """Create a structured tool that interrupts execution pending Slack approval."""

    context_payload = slack_context.as_json() if slack_context else None

    def request_slack_approval(
        command: str,
        summary: str,
        additional_context: str | None = None,
    ) -> dict[str, Any]:
        """Request a human reviewer in Slack to approve a command before it runs."""

        approval_payload: Dict[str, Any] = {
            "type": "approval_request",
            "command": command,
            "summary": summary,
            "additional_context": additional_context,
        }

        if context_payload is not None:
            approval_payload["slack_context"] = context_payload

        resume_value = interrupt(approval_payload)

        # The resume value can be any JSON-serialisable object.
        return resume_value  # type: ignore[return-value]

    return StructuredTool.from_function(
        func=request_slack_approval,
        name="request_slack_approval",
        description=(
            "Pause execution and ask a human to approve or edit the provided command."
            "Always supply a concise summary of why approval is needed and what you are attempting to perform"
        ),
    )


def create_user_question_tool(
    slack_context: Optional["SlackContext"],
) -> StructuredTool:
    """Create a structured tool that asks a Slack user for input via an interrupt."""

    context_payload = slack_context.as_json() if slack_context else None

    def ask_user(
        question: str,
        context: str | None = None,
    ) -> str:
        """Pause execution, ask the user a question, and resume with their answer."""

        question_payload: Dict[str, Any] = {
            "type": "user_question",
            "question": question,
            "context": context,
        }

        if context_payload is not None:
            question_payload["slack_context"] = context_payload

        resume_value = interrupt(question_payload)

        if isinstance(resume_value, dict):
            answer = resume_value.get("answer")
            if isinstance(answer, str):
                return answer

        if isinstance(resume_value, str):
            return resume_value

        raise ValueError(
            "ask_user tool expected an answer string in the resume payload, "
            "but received an unsupported response."
        )

    return StructuredTool.from_function(
        func=ask_user,
        name="ask_user",
        description=(
            "Pause execution and request information from the user. "
            "Provide a concise question and optional context that will be shown in Slack."
        ),
    )
