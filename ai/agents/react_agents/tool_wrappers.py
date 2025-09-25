"""Utilities for wrapping tools with additional agent behaviour."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Callable, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, tool as create_tool
from langgraph.types import interrupt


def _ensure_tool_instance(tool: Callable | BaseTool) -> BaseTool:
    """Return a `BaseTool` instance for the provided callable/tool."""

    if isinstance(tool, BaseTool):
        return tool

    # Wrap plain callables so we can treat everything uniformly.
    return create_tool(tool)


def _dump_tool_args(tool_args: dict) -> str:
    """Produce a stable string representation for tool arguments."""

    try:
        return json.dumps(tool_args, sort_keys=True, default=_fallback_json_encoder)
    except TypeError:
        return str(tool_args)


def _fallback_json_encoder(value):  # type: ignore[no-untyped-def]
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return repr(value)


def tool_approve(
    tool: Callable | BaseTool,
    *,
    summary: Optional[str] = None,
    context: Optional[str] = None,
    allow_edit: bool = False,
    allow_reject: bool = True,
) -> BaseTool:
    """Wrap a tool so that executions require a human approval interrupt.

    Parameters
    ----------
    tool:
        The tool (callable or BaseTool) to wrap.
    summary:
        Optional human-facing summary explaining why the tool is being invoked.
    context:
        Optional additional context that will be shown during review.
    allow_edit:
        Whether reviewers may edit the tool arguments before approval.
    allow_reject:
        Whether reviewers may reject the tool call. If false, they can only approve.
    """

    base_tool = _ensure_tool_instance(tool)

    if summary is None:
        summary = f"Approve running tool `{base_tool.name}`?"

    @create_tool(
        base_tool.name,
        description=base_tool.description,
        args_schema=base_tool.args_schema,
        return_direct=getattr(base_tool, "return_direct", False),
        response_format=getattr(base_tool, "response_format", "content"),
    )
    def call_tool_with_approval(config: RunnableConfig, **tool_input):
        call_representation = f"{base_tool.name}({ _dump_tool_args(tool_input) })"

        approval_payload = {
            "type": "approval_request",
            "summary": summary,
            "command": call_representation,
            "additional_context": context,
            "approval_options": {
                "allow_approve": True,
                "allow_edit": allow_edit,
                "allow_reject": allow_reject,
            },
        }

        resume_value = interrupt(approval_payload)

        if not isinstance(resume_value, dict):
            raise ValueError(
                "tool_approve expected a dictionary response from the approval interrupt"
            )

        decision = resume_value.get("status")

        if decision == "approved":
            return base_tool.invoke(tool_input, config=config)

        if decision == "rejected":
            reviewer_id = resume_value.get("reviewer_id")
            notes = resume_value.get("notes")
            reviewer_label = f"<@{reviewer_id}>" if reviewer_id else "the reviewer"
            if notes:
                return f"Tool `{base_tool.name}` call denied by {reviewer_label}: {notes}"
            return f"Tool `{base_tool.name}` call denied by {reviewer_label}."

        if decision == "edited":
            # If edits are allowed, fall back to original logic by reusing the notes
            # field to convey updated arguments in JSON form (if provided).
            edited_args = resume_value.get("notes")
            if isinstance(edited_args, dict):
                tool_input = edited_args
                return base_tool.invoke(tool_input, config=config)
            raise ValueError(
                "tool_approve received an edit response without updated arguments"
            )

        raise ValueError(
            f"Unsupported approval decision `{decision}` for tool `{base_tool.name}`"
        )

    # Ensure the wrapped tool retains the original metadata for discovery.
    # Preserve metadata that the decorator does not copy automatically.
    call_tool_with_approval.metadata = getattr(base_tool, "metadata", None)
    call_tool_with_approval.tags = getattr(base_tool, "tags", None)
    call_tool_with_approval.callbacks = getattr(base_tool, "callbacks", None)

    return call_tool_with_approval
