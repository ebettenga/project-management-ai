from __future__ import annotations

import re
from collections.abc import Iterable
from logging import Logger
from typing import Any

from slack_bolt import Say
from slack_sdk import WebClient

from ai.agents.react_agents.all_tools import ask_agent
from ai.agents.react_agents.thread_state import get_or_create_thread_id
from listeners.agent_interrupts import (
    build_agent_response_blocks,
    extract_last_ai_text,
    handle_agent_interrupt,
)
from listeners.agent_interrupts.common import SlackContext
from ..listener_utils.listener_constants import DEFAULT_LOADING_TEXT

"""
Handle Slack @mentions by gathering recent context, sending it to the agent, and returning the reply.
If the user provides no prompt, ask the agent to infer the request or ask for clarification.
"""


async def app_mentioned_callback(client: WebClient, event: dict, logger: Logger, _say: Say):
    channel_id = event.get("channel")
    user_id = event.get("user")
    thread_ts = event.get("thread_ts")
    event_ts = event.get("ts")
    raw_text = event.get("text", "")

    if not channel_id or not user_id or not event_ts:
        logger.error("Missing required Slack event fields: %s", event)
        return

    cleaned_text = _strip_bot_mention(raw_text).strip()
    display_prompt = cleaned_text or "(no prompt provided – inferring from context)"

    if not thread_ts:
        thread_ts = event_ts

    if not cleaned_text:
        cleaned_text = _DEFAULT_INFERRED_PROMPT

    waiting_message = None

    try:
        context_messages = await _gather_context_messages(
            client=client,
            channel_id=channel_id,
            event_ts=event_ts,
            thread_ts=event.get("thread_ts"),
        )

        prompt = _build_agent_prompt(
            context_messages=context_messages,
            current_user=user_id,
            current_text=cleaned_text,
        )

        waiting_message = await client.chat_postMessage(
            channel=channel_id,
            text=DEFAULT_LOADING_TEXT,
            thread_ts=thread_ts,
        )

        thread_id = get_or_create_thread_id(
            channel_id=channel_id, user_id=user_id, thread_ts=thread_ts
        )
        slack_context = SlackContext(
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
            thread_id=thread_id,
        )

        agent_payload = {"messages": [{"role": "user", "content": prompt}]}

        response = await ask_agent(
            agent_payload,
            thread_id=thread_id,
            slack_context=slack_context,
        )

        if "__interrupt__" in response:
            await client.chat_update(
                channel=channel_id,
                ts=waiting_message["ts"],
                text="Request sent for approval… check Slack for next steps.",
            )
            for interrupt in response["__interrupt__"]:
                await handle_agent_interrupt(
                    client=client,
                    interrupt=interrupt,
                    channel_id=channel_id,
                    user_id=user_id,
                    thread_ts=thread_ts,
                    thread_id=thread_id,
                    prompt=display_prompt,
                    logger=logger,
                )
            return

        text = extract_last_ai_text(response.get("messages", [])) or "(agent did not return text)"

        await client.chat_update(
            channel=channel_id,
            ts=waiting_message["ts"],
            blocks=build_agent_response_blocks(display_prompt, text),
            text=text,
        )

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Error handling app_mentioned event: %s", exc)
        error_text = f"Received an error from Bolty:\n{exc}"
        if waiting_message:
            await client.chat_update(
                channel=channel_id,
                ts=waiting_message["ts"],
                text=error_text,
            )
        else:
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=error_text,
            )


async def _gather_context_messages(
    *,
    client: WebClient,
    channel_id: str,
    event_ts: str,
    thread_ts: str | None,
) -> list[dict[str, Any]]:
    if thread_ts:
        response = await client.conversations_replies(
            channel=channel_id,
            ts=thread_ts,
            limit=50,
        )
        messages = response.get("messages", [])
        filtered = [m for m in messages if m.get("ts") != event_ts]
        return sorted(filtered, key=lambda item: float(item.get("ts", "0")))

    response = await client.conversations_history(
        channel=channel_id,
        latest=event_ts,
        inclusive=False,
        limit=10,
    )
    messages = response.get("messages", [])
    return sorted(messages, key=lambda item: float(item.get("ts", "0")))


def _build_agent_prompt(
    *,
    context_messages: Iterable[dict[str, Any]],
    current_user: str,
    current_text: str,
) -> str:
    context_lines: list[str] = []
    for message in context_messages:
        text = (message.get("text") or "").strip()
        if not text:
            continue
        author = message.get("user") or message.get("bot_id") or "unknown"
        context_lines.append(f"{author}: {text}")

    if context_lines:
        context_block = "Here is the recent Slack context:\n" + "\n".join(context_lines)
        return f"{context_block}\n\nMost recent message from {current_user}: {current_text}"

    return f"Message from {current_user}: {current_text}"


_DEFAULT_INFERRED_PROMPT = (
    "The user mentioned you without additional instructions. Review the recent Slack context "
    "to determine how to help. If you are unsure, ask the user for clarification."
)


MENTION_PREFIX_PATTERN = re.compile(r"^<@[^>]+>\s*")


def _strip_bot_mention(value: str) -> str:
    return MENTION_PREFIX_PATTERN.sub("", value or "", count=1)
