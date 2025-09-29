from __future__ import annotations

from logging import Logger

from slack_bolt import Ack
from slack_sdk import WebClient
from sqlalchemy import select

from db.models import User
from db.session import get_session
from listeners.events.app_home_opened import build_app_home_view


async def set_user_profile_field(
    logger: Logger, ack: Ack, body: dict, client: WebClient
):
    """Update the stored first or last name for the Slack user."""

    await ack()

    try:
        slack_user_id = body.get("user", {}).get("id")
        if not slack_user_id:
            raise ValueError("Missing Slack user id in action payload")

        action = next(iter(body.get("actions", [])), None)
        if not action:
            raise ValueError("No action payload received")

        action_id = action.get("action_id") or ""
        raw_value = (action.get("value") or "").strip()
        normalized_value = raw_value or None

        field_map = {
            "set_user_first_name": "first_name",
            "set_user_last_name": "last_name",
        }

        field_name = field_map.get(action_id)
        if not field_name:
            raise ValueError(f"Unsupported action id: {action_id}")

        with get_session() as session:
            user = (
                session.execute(select(User).where(User.slack_user_id == slack_user_id))
                .scalar_one_or_none()
            )

            if user is None:
                user = User(slack_user_id=slack_user_id)
                session.add(user)
                session.flush()

            setattr(user, field_name, normalized_value)

        view = build_app_home_view(slack_user_id)
        await client.views_publish(user_id=slack_user_id, view=view)

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to update user profile field: %s", exc)
