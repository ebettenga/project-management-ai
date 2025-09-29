"""Utilities for wrapping tools with additional agent behaviour."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
import threading
from dataclasses import asdict, is_dataclass
from typing import Any, Awaitable, Callable, Optional

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool, tool as create_tool
from langgraph.types import interrupt


def _ensure_tool_instance(tool: Callable | BaseTool) -> BaseTool:
    """Return a `BaseTool` instance for the provided callable/tool."""

    if isinstance(tool, BaseTool):
        return tool

    # Wrap plain callables so we can treat everything uniformly.
    return create_tool(tool)


def _fallback_json_encoder(value):  # type: ignore[no-untyped-def]
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()
    if hasattr(value, "__dict__"):
        return value.__dict__
    return repr(value)


def _humanize_tool_name(name: str) -> str:
    """Convert a tool identifier into a human-friendly label."""

    cleaned = re.sub(r"[_\s]+", " ", name or "").strip()
    if not cleaned:
        return "Tool Call"
    return cleaned[:1].upper() + cleaned[1:]


def _humanize_arg_label(value: str) -> str:
    """Convert an argument name into a human-friendly label."""

    cleaned = re.sub(r"[_\s]+", " ", value or "").strip()
    if not cleaned:
        return "Value"
    return cleaned[:1].upper() + cleaned[1:]


def _is_simple_value(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _format_argument_block(arguments: dict[str, Any]) -> str:
    """Format tool arguments as a human-readable block."""

    if not arguments:
        return "No arguments provided."

    lines: list[str] = []
    for raw_key, raw_value in arguments.items():
        label = _humanize_arg_label(str(raw_key))
        if _is_simple_value(raw_value):
            display_value = "None" if raw_value is None else str(raw_value)
            lines.append(f"{label}: {display_value}")
            continue

        try:
            serialized = json.dumps(
                raw_value,
                indent=2,
                ensure_ascii=False,
                default=_fallback_json_encoder,
            )
        except TypeError:
            serialized = str(raw_value)

        lines.append(f"{label}:\n{serialized}")

    return "\n".join(lines)


def _format_tool_call(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Generate a human-readable description of a tool call."""

    header = f"{_humanize_tool_name(tool_name)}?"
    body = _format_argument_block(tool_input)
    if body:
        return f"{header}\n\n{body}"
    return header


def tool_approve(
    tool: Callable | BaseTool,
    *,
    summary: Optional[str] = None,
    context: Optional[str] = None,
    allow_edit: bool = False,
    allow_reject: bool = True,
) -> BaseTool:
    """Wrap a tool so that executions require a human approval interrupt."""

    base_tool = _ensure_tool_instance(tool)

    if summary is None:
        summary = f"Approve running tool `{base_tool.name}`?"

    def _build_payload(tool_input: dict) -> dict[str, object]:
        call_representation = _format_tool_call(base_tool.name, tool_input)
        return {
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

    def _handle_resume(resume_value: object, tool_input: dict) -> tuple[str, object]:
        if not isinstance(resume_value, dict):
            raise ValueError(
                "tool_approve expected a dictionary response from the approval interrupt"
            )

        decision = (resume_value.get("status") or "approved").lower()

        if decision in {"approved", "edited"}:
            edited_args = resume_value.get("edited_args")
            if isinstance(edited_args, dict):
                return "execute", edited_args
            return "execute", tool_input

        if decision == "rejected":
            return "return", _format_rejection_message(base_tool.name, resume_value)

        raise ValueError(
            f"Unsupported approval decision `{decision}` for tool `{base_tool.name}`"
        )

    def call_tool_with_approval(
        config: RunnableConfig,
        **tool_input,
    ):
        resume_value = interrupt(_build_payload(tool_input))
        action, payload = _handle_resume(resume_value, tool_input)

        if action == "return":
            return _normalize_output(base_tool, payload)

        return _execute_tool_sync(base_tool, payload, config)

    async def call_tool_with_approval_async(
        config: RunnableConfig,
        **tool_input,
    ):
        resume_value = interrupt(_build_payload(tool_input))
        action, payload = _handle_resume(resume_value, tool_input)

        if action == "return":
            return _normalize_output(base_tool, payload)

        return await _execute_tool_async(base_tool, payload, config)

    wrapped_tool = StructuredTool.from_function(
        func=call_tool_with_approval,
        coroutine=call_tool_with_approval_async,
        name=base_tool.name,
        description=base_tool.description,
        args_schema=base_tool.args_schema,
        return_direct=getattr(base_tool, "return_direct", False),
        response_format=getattr(base_tool, "response_format", "content"),
    )

    wrapped_tool.metadata = getattr(base_tool, "metadata", None)
    wrapped_tool.tags = getattr(base_tool, "tags", None)
    wrapped_tool.callbacks = getattr(base_tool, "callbacks", None)

    return wrapped_tool


def _execute_tool_sync(
    base_tool: BaseTool,
    tool_input: dict,
    config: Optional[RunnableConfig],
) -> object:
    """Execute a wrapped tool within a synchronous context."""

    try:
        result = base_tool.invoke(tool_input, config=config)
    except NotImplementedError:
        coroutine_fn = getattr(base_tool, "coroutine", None)
        if coroutine_fn is not None:
            kwargs = _prepare_callable_kwargs(coroutine_fn, tool_input, config)
            result = _run_coroutine_sync(lambda: coroutine_fn(**kwargs))
        else:
            func = getattr(base_tool, "func", None)
            if func is not None:
                kwargs = _prepare_callable_kwargs(func, tool_input, config)
                result = func(**kwargs)
            else:
                raise
    return _normalize_output(base_tool, result)


def _prepare_callable_kwargs(
    callable_obj: Callable,
    tool_input: dict,
    config: Optional[RunnableConfig],
) -> dict:
    kwargs = dict(tool_input)
    signature = inspect.signature(callable_obj)
    if "config" in signature.parameters and config is not None:
        kwargs.setdefault("config", config)
    return kwargs


def _run_coroutine_sync(factory: Callable[[], Awaitable[Any]]):
    """Run an async callable from a synchronous context."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: dict[str, object] = {}
    error: dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except Exception as exc:  # pragma: no cover - defensive guard
            error["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if error:
        raise error["error"]

    return result.get("value")


def _normalize_output(base_tool: BaseTool, value: object) -> object:
    """Ensure tool output matches the wrapped tool's response format."""

    expected_format = getattr(base_tool, "response_format", "content")
    if expected_format == "content_and_artifact":
        if isinstance(value, tuple) and len(value) == 2:
            return value
        return (value, None)
    return value


def _format_rejection_message(tool_name: str, resume_value: dict) -> str:
    reviewer_id = resume_value.get("reviewer_id")
    notes = resume_value.get("notes")
    reviewer_label = f"<@{reviewer_id}>" if reviewer_id else "the reviewer"
    if notes:
        return f"Tool `{tool_name}` call denied by {reviewer_label}: {notes}"
    return f"Tool `{tool_name}` call denied by {reviewer_label}."


async def _execute_tool_async(
    base_tool: BaseTool,
    tool_input: dict,
    config: Optional[RunnableConfig],
) -> object:
    """Execute a wrapped tool within an asynchronous context."""

    try:
        result = await base_tool.ainvoke(tool_input, config=config)
    except NotImplementedError:
        coroutine_fn = getattr(base_tool, "coroutine", None)
        if coroutine_fn is not None:
            kwargs = _prepare_callable_kwargs(coroutine_fn, tool_input, config)
            result = await coroutine_fn(**kwargs)
        else:
            func = getattr(base_tool, "func", None)
            if func is not None:
                kwargs = _prepare_callable_kwargs(func, tool_input, config)
                result = func(**kwargs)
            else:
                raise

    return _normalize_output(base_tool, result)
