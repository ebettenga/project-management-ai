"""Helpers for managing LangGraph thread identifiers and persistence."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

import psycopg
from langchain_core.tools import StructuredTool

if TYPE_CHECKING:  # pragma: no cover
    from listeners.agent_interrupts.common import SlackContext


logger = logging.getLogger(__name__)

_STATE_FILE = Path("data/langgraph_threads.json")


def _load_state() -> dict[str, str]:
    if not _STATE_FILE.exists():
        return {}

    try:
        with _STATE_FILE.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to load thread state file: %s", exc)
    return {}


def _save_state(state: dict[str, str]) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _STATE_FILE.open("w", encoding="utf-8") as handle:
            json.dump(state, handle)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to persist thread state file: %s", exc)


def _thread_key(channel_id: str, user_id: str, thread_ts: Optional[str]) -> str:
    base_thread = thread_ts or "root"
    return f"{channel_id}:{base_thread}:{user_id}"


def _default_thread_id(channel_id: str, user_id: str, thread_ts: Optional[str]) -> str:
    if thread_ts:
        return f"{user_id}-{channel_id}-{thread_ts}"
    return f"{user_id}-{channel_id}"


def get_or_create_thread_id(
    *, channel_id: str, user_id: str, thread_ts: Optional[str]
) -> str:
    """Return the LangGraph thread id used for the Slack context, creating one if missing."""

    state = _load_state()
    key = _thread_key(channel_id, user_id, thread_ts)
    thread_id = state.get(key)
    if thread_id:
        return thread_id

    thread_id = _default_thread_id(channel_id, user_id, thread_ts)
    state[key] = thread_id
    _save_state(state)
    return thread_id


def rotate_thread_id(
    *, channel_id: str, user_id: str, thread_ts: Optional[str]
) -> Tuple[str, str]:
    """Rotate the LangGraph thread identifier for the Slack context.

    Returns a tuple of (old_thread_id, new_thread_id).
    """

    state = _load_state()
    key = _thread_key(channel_id, user_id, thread_ts)
    default_id = _default_thread_id(channel_id, user_id, thread_ts)

    old_thread_id = state.get(key, default_id)
    new_thread_id = f"{default_id}-{uuid.uuid4().hex[:8]}"

    state[key] = new_thread_id
    _save_state(state)

    return old_thread_id, new_thread_id


async def clear_thread_history(thread_id: Optional[str]) -> None:
    """Remove any persisted LangGraph checkpoints for the provided thread id."""

    if not thread_id:
        return

    conn_str = os.getenv("POSTGRES_URL")
    if not conn_str:
        logger.debug("POSTGRES_URL not configured; skipping thread history clear.")
        return

    try:
        conn = await psycopg.AsyncConnection.connect(conn_str)
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to connect to Postgres for thread clear: %s", exc)
        return

    try:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT table_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND column_name = 'thread_id'
                """
            )
            tables = [row[0] for row in await cur.fetchall()]

            for table in tables:
                try:
                    await cur.execute(
                        f'DELETE FROM "{table}" WHERE thread_id = %s', (thread_id,)
                    )
                except Exception as table_exc:  # pragma: no cover - defensive logging
                    logger.debug(
                        "Skipping deletion from table %s due to error: %s", table, table_exc
                    )

        await conn.commit()
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.warning("Failed to clear LangGraph checkpoints for %s: %s", thread_id, exc)
    finally:
        try:
            await conn.close()
        except Exception:  # pragma: no cover - defensive guard
            pass


def create_clear_thread_tool(
    slack_context: Optional["SlackContext"],
) -> StructuredTool:
    """Create a tool that clears the LangGraph thread for the provided Slack context."""

    async def _clear_thread_async() -> str:
        if not slack_context:
            raise ValueError("Slack context is required to clear the thread.")

        channel_id = slack_context.channel_id
        user_id = slack_context.user_id
        thread_ts = slack_context.thread_ts

        current_thread_id = get_or_create_thread_id(
            channel_id=channel_id, user_id=user_id, thread_ts=thread_ts
        )

        await clear_thread_history(current_thread_id)

        old_thread_id, new_thread_id = rotate_thread_id(
            channel_id=channel_id, user_id=user_id, thread_ts=thread_ts
        )

        logger.info(
            "LangGraph thread rotated from %s to %s for channel %s",
            old_thread_id,
            new_thread_id,
            channel_id,
        )

        return (
            "Cleared the stored conversation history for this Slack thread. "
            "Future interactions will start fresh."
        )

    def _clear_thread_sync() -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(_clear_thread_async())

        result: dict[str, str] = {}
        error: dict[str, BaseException] = {}

        def _runner() -> None:
            try:
                result["value"] = asyncio.run(_clear_thread_async())
            except Exception as exc:  # pragma: no cover - defensive guard
                error["error"] = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()

        if error:
            raise error["error"]

        return result.get("value", "")

    return StructuredTool.from_function(
        func=_clear_thread_sync,
        coroutine=_clear_thread_async,
        name="clear_langgraph_thread",
        description=(
            "Clear the stored LangGraph conversation state for the current Slack thread so "
            "future messages start with no prior context."
        ),
    )
