"""Shared helpers for Slack-facing agent interrupt flows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable
from typing_extensions import Optional
from langchain_core.messages import AIMessage
from langchain_core.messages.base import BaseMessage


@dataclass(frozen=True)
class SlackContext:
    """Slack context passed to the agent for tool calls."""

    channel_id: str
    user_id: str
    thread_ts: Optional[str]
    thread_id: Optional[str]

    def as_json(self) -> str:
        return json.dumps(
            {
                "channel_id": self.channel_id,
                "user_id": self.user_id,
                "thread_ts": self.thread_ts,
                "thread_id": self.thread_id,
            }
        )


def sanitize_text(value: str | None, fallback: str) -> str:
    trimmed = (value or "").strip()
    return trimmed if trimmed else fallback


def build_agent_response_blocks(prompt: str, response_text: str) -> list[dict[str, Any]]:
    safe_prompt = sanitize_text(prompt, "(no prompt provided)")
    safe_response = sanitize_text(response_text, "(no response returned)")

    return [
        {
            "type": "rich_text",
            "elements": [
                {
                    "type": "rich_text_quote",
                    "elements": [{"type": "text", "text": safe_prompt}],
                },
                {
                    "type": "rich_text_section",
                    "elements": [
                        {
                            "type": "text",
                            "text": safe_response,
                        }
                    ],
                },
            ],
        }
    ]


def extract_last_ai_text(messages: Iterable[BaseMessage]) -> str:
    """Return the newest non-empty AI message text from the conversation."""

    for message in reversed(list(messages)):
        content = message.content

        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        elif isinstance(content, list):
            text_chunks: list[str] = []
            for chunk in content:
                if isinstance(chunk, str):
                    text_chunks.append(chunk)
                elif isinstance(chunk, dict) and chunk.get("type") == "text":
                    text_chunks.append(chunk.get("text", ""))

            text = "\n".join(part for part in text_chunks if part.strip())
            if text.strip():
                return text

    return ""
