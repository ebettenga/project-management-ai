"""Helpers to retrieve prompts from Langfuse with safe fallbacks."""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from typing import Any

try:  # pragma: no cover - graceful fallback if the SDK is missing
    from langfuse import Langfuse
except Exception:  # broad: import error or runtime issues when loading the SDK
    Langfuse = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)

_DEFAULT_AGENT_PROMPT = (
    "You are a project management assistant in a slack app. "
    "You can reach MCP tools via this environment. "
    "Never guess, always call the tool first. "
    "Store any information you receive to memory. "
    "You primary help with located things in the users preferred task management service and performing actions on their behalf. "
    "keep research brief. "
    "if something doesn't make sense or you get stuck, ask the user before proceeding. "
    "Call tools proactively whenever they can help and then explain the result succinctly. "
)

_DEFAULT_DM_PROMPT = (
    "The user sent an empty direct message. Review the recent Slack context to determine how to help. "
    "If the intent remains unclear, ask the user for clarification."
)

_DEFAULT_INFERRED_PROMPT = (
    "The user mentioned you without additional instructions. Review the recent Slack context "
    "to determine how to help. If you are unsure, ask the user for clarification."
)

_LANGFUSE_PROMPT_LABEL = os.getenv("LANGFUSE_PROMPT_LABEL")

_client: Langfuse | None = None
_client_init_failed = False


def _get_client() -> Langfuse | None:
    """Return a configured Langfuse client or ``None`` if unavailable."""

    global _client, _client_init_failed

    if _client is not None:
        return _client

    if _client_init_failed:
        return None

    if Langfuse is None:
        _client_init_failed = True
        logger.debug("Langfuse SDK not installed; falling back to local prompts")
        return None

    try:
        _client = Langfuse()
        return _client
    except Exception as exc:  # pragma: no cover - defensive logging
        _client_init_failed = True
        logger.warning(
            "Unable to initialize Langfuse client; using fallback prompts", exc_info=exc
        )
        return None


def _normalise_prompt(compiled_prompt: Any, fallback: str) -> str:
    if isinstance(compiled_prompt, str):
        return compiled_prompt

    if isinstance(compiled_prompt, list):
        try:
            return "\n".join(
                f"{item.get('role', 'unknown')}: {item.get('content', '')}"
                if isinstance(item, dict)
                else json.dumps(item)
                for item in compiled_prompt
            )
        except Exception:  # pragma: no cover - keep fallback when formatting fails
            logger.debug("Falling back after failing to normalise chat prompt", exc_info=True)

    return fallback


def _get_prompt_text(
    *,
    name: str | None,
    fallback: str,
) -> str:
    """Fetch ``name`` from Langfuse or return ``fallback`` when unavailable."""

    if not name:
        return fallback

    client = _get_client()
    if client is None:
        return fallback

    try:
        prompt = client.get_prompt(
            name,
            label=_LANGFUSE_PROMPT_LABEL,
            fallback=fallback,
        )
        compiled = prompt.compile()
        text = _normalise_prompt(compiled, fallback)
        return text or fallback
    except Exception:  # pragma: no cover - defensive fallback
        logger.warning("Using fallback prompt for '%s'", name, exc_info=True)
        return fallback


@lru_cache(maxsize=1)
def get_agent_prompt() -> str:
    """Return the agent instruction prompt."""

    return _get_prompt_text(
        name=os.getenv("LANGFUSE_AGENT_PROMPT_NAME"),
        fallback=_DEFAULT_AGENT_PROMPT,
    )


@lru_cache(maxsize=1)
def get_default_dm_prompt() -> str:
    """Return the fallback prompt for empty DM messages."""

    return _get_prompt_text(
        name=os.getenv("LANGFUSE_DM_PROMPT_NAME"),
        fallback=_DEFAULT_DM_PROMPT,
    )


@lru_cache(maxsize=1)
def get_default_inferred_prompt() -> str:
    """Return the fallback prompt for inferred mention handling."""

    return _get_prompt_text(
        name=os.getenv("LANGFUSE_INFERRED_PROMPT_NAME"),
        fallback=_DEFAULT_INFERRED_PROMPT,
    )

