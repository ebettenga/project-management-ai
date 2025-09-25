"""Helpers for handling user-question interrupts from the agent."""

from __future__ import annotations

from logging import Logger
from typing import Any
from uuid import uuid4

from langgraph.types import Interrupt
from slack_sdk import WebClient

from listeners.listener_utils.listener_constants import QUESTION_ACTION_OPEN_MODAL
from state_store.question_requests import save_request


def _sanitize_text(value: str | None, fallback: str) -> str:
    trimmed = (value or "").strip()
    return trimmed if trimmed else fallback


async def handle_question_interrupt(
    *,
    client: WebClient,
    interrupt: Interrupt,
    channel_id: str,
    user_id: str,
    thread_ts: str | None,
    thread_id: str,
    prompt: str,
    logger: Logger,
) -> None:
    question_data = interrupt.value

    if not isinstance(question_data, dict):
        logger.error(
            "Question interrupt payload was not a dictionary: %s", question_data
        )
        return

    question = _sanitize_text(question_data.get("question"), "(no question provided)")
    context = _sanitize_text(question_data.get("context"), "")
    button_text = _sanitize_text(
        question_data.get("button_text"),
        "Answer question",
    )
    modal_title = _sanitize_text(question_data.get("modal_title"), "Provide an answer")
    submit_label = _sanitize_text(question_data.get("submit_label"), "Submit")
    placeholder = _sanitize_text(
        question_data.get("placeholder"),
        "Provide any details that will help the bot.",
    )

    block_id = f"question_actions_{uuid4().hex[:8]}"

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Bolty needs your input*\n{question}",
            },
        },
    ]

    if context:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": context,
                },
            }
        )

    blocks.append(
        {
            "type": "actions",
            "block_id": block_id,
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": button_text},
                    "action_id": QUESTION_ACTION_OPEN_MODAL,
                    "value": interrupt.id,
                }
            ],
        }
    )

    post_kwargs: dict[str, Any] = {
        "channel": channel_id,
        "blocks": blocks,
    }
    if thread_ts:
        post_kwargs["thread_ts"] = thread_ts

    response = await client.chat_postMessage(**post_kwargs)

    conversation_ts = thread_ts or response["ts"]

    save_request(
        interrupt.id,
        {
            "thread_id": thread_id,
            "channel_id": channel_id,
            "thread_ts": conversation_ts,
            "question": question,
            "context": context,
            "prompt": prompt,
            "requester_user_id": user_id,
            "question_message_ts": response["ts"],
            "tool_call_id": interrupt.id,
            "tool_name": "ask_user",
            "modal_title": modal_title,
            "submit_label": submit_label,
            "placeholder": placeholder,
            "button_text": button_text,
        },
    )

    logger.info("Question request logged for interrupt %s", interrupt.id)
