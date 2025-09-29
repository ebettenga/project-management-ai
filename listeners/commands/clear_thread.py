from logging import Logger

from slack_bolt import Ack, BoltContext, Say
from slack_sdk import WebClient

from ai.agents.react_agents.thread_state import (
    clear_thread_history,
    get_or_create_thread_id,
    rotate_thread_id,
)


async def clear_thread_command(
    client: WebClient,
    ack: Ack,
    command,
    _say: Say,
    logger: Logger,
    context: BoltContext,
):
    await ack()

    channel_id = command.get("channel_id")
    user_id = command.get("user_id")
    if not channel_id or not user_id:
        logger.error("/clear command missing required identifiers: %s", command)
        return

    thread_ts = (
        command.get("thread_ts")
        or context.get("thread_ts")
        or command.get("message_ts")
    )

    current_thread_id = get_or_create_thread_id(
        channel_id=channel_id,
        user_id=user_id,
        thread_ts=thread_ts,
    )

    await clear_thread_history(current_thread_id)
    old_thread_id, new_thread_id = rotate_thread_id(
        channel_id=channel_id,
        user_id=user_id,
        thread_ts=thread_ts,
    )

    logger.info(
        "Cleared LangGraph thread %s and rotated to %s for /clear command",
        old_thread_id,
        new_thread_id,
    )

    confirmation = (
        "Cleared the stored agent history for this conversation. "
        "I'll treat future messages here as a new thread."
    )

    await client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text=confirmation,
        thread_ts=thread_ts,
    )
