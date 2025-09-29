"""Helpers for retrieving and formatting user preference data."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from db.models import User
from db.session import get_session


def get_user_rules(slack_user_id: str) -> list[str]:
    """Return the cleaned list of rules stored for the given Slack user."""

    if not slack_user_id:
        return []

    with get_session() as session:
        result = session.execute(
            select(User).where(User.slack_user_id == slack_user_id)
        ).scalar_one_or_none()

        if result is None:
            return []

        prefs = result.model_preferences or {}
        rules = prefs.get("rules") if isinstance(prefs, dict) else None

        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            return []

        cleaned: list[str] = []
        for rule in rules:
            text = str(rule).strip()
            if text:
                cleaned.append(text)

        return cleaned


def build_rules_system_message(rules: list[str]) -> dict[str, str] | None:
    """Convert user rules into a system message for the agent payload."""

    if not rules:
        return None

    bullet_list = "\n".join(f"- {rule}" for rule in rules)
    text = (
        "The following rules are personalized instructions from the Slack user. "
        "You must follow them while generating responses.\n" + bullet_list
    )
    return {"role": "system", "content": text}
