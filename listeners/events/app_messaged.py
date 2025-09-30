from __future__ import annotations

from collections.abc import Iterable
from logging import Logger
from typing import Any

from slack_bolt import Say
from slack_sdk import WebClient

from ai.agents.react_agents.all_tools import ask_agent
from ai.agents.react_agents.thread_state import get_or_create_thread_id
from ai.prompts import get_default_dm_prompt
from listeners.agent_interrupts import (
    build_agent_response_blocks,
    extract_last_ai_text,
    handle_agent_interrupt,
)
from listeners.agent_interrupts.common import SlackContext
from listeners.user_preferences import (
    build_rules_system_message,
    build_user_metadata_message,
    get_user_rules,
)

from ..listener_utils.listener_constants import DEFAULT_LOADING_TEXT

"""Handle direct messages sent to the bot, mirroring the agent workflow used elsewhere."""


async def app_messaged_callback(client: WebClient, event: dict, logger: Logger, _say: Say):
    channel_id = event.get("channel")
    user_id = event.get("user")
    thread_ts = event.get("thread_ts")
    event_ts = event.get("ts")
    raw_text = event.get("text", "")

    if not channel_id or not user_id or not event_ts:
        logger.error("Missing required Slack event fields: %s", event)
        return

    cleaned_text = raw_text.strip()
    display_prompt = cleaned_text or "(no prompt provided)"

    if not thread_ts:
        thread_ts = event_ts

    if not cleaned_text:
        cleaned_text = get_default_dm_prompt()

    waiting_message: dict[str, Any] | None = None

    try:
        context_messages = await _gather_dm_context_messages(
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
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
        )

        slack_context = SlackContext(
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
            thread_id=thread_id,
        )

        rules = get_user_rules(user_id)
        messages = []

        metadata_message = build_user_metadata_message(user_id)
        if metadata_message:
            messages.append(metadata_message)

        rules_message = build_rules_system_message(rules)
        if rules_message:
            messages.append(rules_message)

        messages.append({"role": "user", "content": prompt})

        agent_payload = {"messages": messages}

        response = await ask_agent(
            agent_payload,
            thread_id=thread_id,
            slack_context=slack_context,
        )

        if "__interrupt__" in response:
            if waiting_message:
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

        if waiting_message:
            await client.chat_update(
                channel=channel_id,
                ts=waiting_message["ts"],
                blocks=build_agent_response_blocks(display_prompt, text),
                text=text,
            )
        else:  # pragma: no cover - defensive guard
            await client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                blocks=build_agent_response_blocks(display_prompt, text),
                text=text,
            )

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Error handling app_messaged event: %s", exc)
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


async def _gather_dm_context_messages(
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
        limit=20,
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
