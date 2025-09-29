from __future__ import annotations

from logging import Logger

from slack_bolt import Ack
from slack_sdk import WebClient
from sqlalchemy import select

from db.models import User
from db.session import get_session
from listeners.events.app_home_opened import build_app_home_view


async def delete_user_rule(logger: Logger, ack: Ack, body: dict, client: WebClient):
    """Remove a stored rule for the Slack user and refresh the App Home view."""

    await ack()

    try:
        slack_user_id = body.get("user", {}).get("id")
        if not slack_user_id:
            raise ValueError("Missing Slack user id in action payload")

        action = next(iter(body.get("actions", [])), None)
        if not action:
            raise ValueError("No action payload present")

        raw_value = action.get("value") or ""
        rule_text = raw_value.strip()
        if not rule_text:
            raise ValueError("Missing rule text in action value")

        with get_session() as session:
            user = (
                session.execute(select(User).where(User.slack_user_id == slack_user_id))
                .scalar_one_or_none()
            )
            if user is None:
                logger.info("User %s not found while deleting rule", slack_user_id)
            else:
                preferences = dict(user.model_preferences or {})
                rules_value = preferences.get("rules")

                if isinstance(rules_value, list):
                    filtered_rules = [
                        str(item).strip()
                        for item in rules_value
                        if str(item).strip() and str(item).strip() != rule_text
                    ]
                else:
                    filtered_rules = []

                if filtered_rules:
                    preferences["rules"] = filtered_rules
                elif "rules" in preferences:
                    preferences.pop("rules", None)

                user.model_preferences = preferences

        view = build_app_home_view(slack_user_id)
        await client.views_publish(user_id=slack_user_id, view=view)

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to delete user rule: %s", exc)
