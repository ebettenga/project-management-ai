from __future__ import annotations

from logging import Logger
from typing import Any, Optional
import json

from slack_bolt import Ack
from slack_sdk import WebClient

from ai.agents.react_agents.all_tools import SlackContext, ask_agent
from langgraph.errors import GraphInterrupt
from langgraph.types import Command
from listeners.listener_utils.approvals import (
    build_agent_response_blocks,
    extract_last_ai_text,
)
from listeners.listener_utils.interrupts import handle_agent_interrupt
from listeners.listener_utils.listener_constants import (
    APPROVAL_ACTION_APPROVE,
    APPROVAL_ACTION_EDIT,
    APPROVAL_ACTION_REJECT,
    APPROVAL_EDIT_MODAL_CALLBACK,
)
from state_store.approval_requests import delete_request, load_request


async def approve_request(logger: Logger, ack: Ack, body: dict, client: WebClient):
    await ack()
    await _process_decision(
        logger=logger,
        body=body,
        client=client,
        decision="approved",
    )


async def reject_request(logger: Logger, ack: Ack, body: dict, client: WebClient):
    await ack()
    await _process_decision(
        logger=logger,
        body=body,
        client=client,
        decision="rejected",
    )


async def start_edit_request(logger: Logger, ack: Ack, body: dict, client: WebClient):
    await ack()  # always ack quickly

    try:
        interrupt_id = body["actions"][0]["value"]
        request = load_request(interrupt_id)
        if not request:
            await _notify_missing_request(client, body)
            return

        modal_view = {
            "type": "modal",
            "callback_id": APPROVAL_EDIT_MODAL_CALLBACK,
            "private_metadata": json.dumps({"interrupt_id": interrupt_id}),
            "title": {"type": "plain_text", "text": "Provide more info"},
            "submit": {"type": "plain_text", "text": "Submit"},
            "close": {"type": "plain_text", "text": "Cancel"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*Command*\n```{request['command']}```",
                    },
                },
                {
                    "type": "input",
                    "block_id": "notes_block",
                    "label": {"type": "plain_text", "text": "Add context or edits"},
                    "element": {
                        "type": "plain_text_input",
                        "action_id": "notes_input",
                        "multiline": True,
                    },
                },
            ],
        }

        # Correct way for message buttons
        await client.views_open(trigger_id=body["trigger_id"], view=modal_view)

    except Exception as error:
        logger.error("Failed to open edit modal: %s", error)
async def submit_edit_request(logger: Logger, ack: Ack, body: dict, client: WebClient):
    await ack()
    try:
        metadata = json.loads(body["view"]["private_metadata"])
    except (KeyError, json.JSONDecodeError) as error:
        logger.error("Invalid modal metadata: %s", error)
        return

    interrupt_id = metadata.get("interrupt_id")
    if not interrupt_id:
        logger.error("Interrupt id missing from modal metadata")
        return

    request = load_request(interrupt_id)
    if not request:
        await _notify_missing_request(client, body)
        return

    notes = (
        body["view"]["state"]["values"].get("notes_block", {})
        .get("notes_input", {})
        .get("value")
    )

    await _process_decision(
        logger=logger,
        body=body,
        client=client,
        decision="edited",
        notes=notes,
        interrupt_id_override=interrupt_id,
    )


async def _process_decision(
    *,
    logger: Logger,
    body: dict,
    client: WebClient,
    decision: str,
    notes: Optional[str] = None,
    interrupt_id_override: Optional[str] = None,
) -> None:
    try:
        action = body.get("actions", [{}])[0]
        interrupt_id = interrupt_id_override or action.get("value")
        if not interrupt_id:
            logger.error("No interrupt_id found in action payload")
            return

        request = load_request(interrupt_id)
        if not request:
            await _notify_missing_request(client, body)
            return

        reviewer_id = body.get("user", {}).get("id")
        await _update_approval_message(
            client=client,
            request=request,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
        )

        await _resume_agent(
            client=client,
            request=request,
            interrupt_id=interrupt_id,
            decision=decision,
            reviewer_id=reviewer_id,
            notes=notes,
            logger=logger,
        )

        delete_request(interrupt_id)
    except Exception as error:  # pragma: no cover - defensive guard
        logger.error("Failed to process approval decision: %s", error)


async def _resume_agent(
    *,
    client: WebClient,
    request: dict,
    interrupt_id: str,
    decision: str,
    reviewer_id: Optional[str],
    notes: Optional[str],
    logger: Logger,
) -> None:
    slack_context = SlackContext(
        channel_id=request["channel_id"],
        user_id=request["requester_user_id"],
        thread_ts=request["thread_ts"],
        thread_id=request["thread_id"],
    )

    resume_value: dict[str, Any] = {
        "status": decision,
        "command": request.get("command"),
        "thread_id": request.get("thread_id"),
    }
    if reviewer_id:
        resume_value["reviewer_id"] = reviewer_id
    if notes:
        resume_value["notes"] = notes

    if notes:
        reviewer_label = f"<@{reviewer_id}>" if reviewer_id else "a reviewer"
        await client.chat_postMessage(
            channel=request["channel_id"],
            thread_ts=request["thread_ts"],
            text=f"Additional context from {reviewer_label}:\n{notes}",
        )

    try:
        response = await ask_agent(
            Command(resume=resume_value),
            thread_id=request["thread_id"],
            slack_context=slack_context,
        )
    except GraphInterrupt as interrupt:
        await handle_agent_interrupt(
            client=client,
            interrupt=interrupt,
            channel_id=request["channel_id"],
            user_id=request["requester_user_id"],
            thread_ts=request["thread_ts"],
            thread_id=request["thread_id"],
            prompt=request.get("prompt", request.get("summary", "")),
            logger=logger,
        )
        return

    text = extract_last_ai_text(response["messages"])
    if not text:
        text = "(agent did not return text)"
    await client.chat_postMessage(
        channel=request["channel_id"],
        thread_ts=request["thread_ts"],
        blocks=build_agent_response_blocks(
            request.get("prompt", request.get("summary", "")),
            text,
        ),
    )


async def _update_approval_message(
    *,
    client: WebClient,
    request: dict,
    decision: str,
    reviewer_id: Optional[str],
    notes: Optional[str],
) -> None:
    channel_id = request["channel_id"]
    approval_ts = request["approval_message_ts"]

    parts = {
        "approved": ":white_check_mark: Approved",
        "rejected": ":x: Rejected",
        "edited": ":memo: Edited",
    }

    decision_text = parts.get(decision, decision.capitalize())
    if reviewer_id:
        decision_text = f"{decision_text} by <@{reviewer_id}>"

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": decision_text,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Command*\n```{request['command']}```",
            },
        },
    ]

    if notes:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Reviewer notes*\n{notes}",
                },
            }
        )

    summary = request.get("summary")
    if summary:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"_{summary}_"}],
            }
        )

    await client.chat_update(channel=channel_id, ts=approval_ts, blocks=blocks)


async def _notify_missing_request(client: WebClient, body: dict) -> None:
    channel_id = body.get("channel", {}).get("id")
    user_id = body.get("user", {}).get("id")
    if channel_id and user_id:
        await client.chat_postEphemeral(
            channel=channel_id,
            user=user_id,
            text="This approval request could not be found or was already handled.",
        )
