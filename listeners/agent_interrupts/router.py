"""Dispatcher for agent interrupt payloads."""

from __future__ import annotations

from logging import Logger

from langgraph.types import Interrupt
from slack_sdk import WebClient

from listeners.agent_interrupts.approvals import handle_approval_interrupt
from listeners.agent_interrupts.questions import handle_question_interrupt


async def handle_agent_interrupt(
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
    payload = interrupt.value

    if not isinstance(payload, dict):
        logger.error("Interrupt payload was not a dictionary: %s", payload)
        return

    interrupt_type = payload.get("type")

    if interrupt_type == "approval_request":
        await handle_approval_interrupt(
            client=client,
            interrupt=interrupt,
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
            thread_id=thread_id,
            prompt=prompt,
            logger=logger,
        )
    elif interrupt_type == "user_question":
        await handle_question_interrupt(
            client=client,
            interrupt=interrupt,
            channel_id=channel_id,
            user_id=user_id,
            thread_ts=thread_ts,
            thread_id=thread_id,
            prompt=prompt,
            logger=logger,
        )
    else:
        logger.error("Unsupported interrupt type: %s", interrupt_type)
