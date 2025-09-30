from __future__ import annotations

from logging import Logger

from slack_bolt import Ack

from sqlalchemy import select

from db.models import ManagementPlatform, User, UserManagementPlatform
from db.session import get_session


async def set_management_platforms(logger: Logger, ack: Ack, body: dict):
    """Persist selected management platforms for the Slack user."""

    await ack()

    try:
        slack_user_id = body.get("user", {}).get("id")
        if not slack_user_id:
            raise ValueError("Missing Slack user id in action payload")

        action_payload = next(iter(body.get("actions", [])), {})
        selected_options = action_payload.get("selected_options", [])
        selected_slugs = {
            (option.get("value") or "").strip().lower()
            for option in selected_options
            if option.get("value")
        }

        with get_session() as session:
            user = User.create_if_not_exists(session, slack_user_id=slack_user_id)

            # Load all platform definitions matching the selected slugs
            platforms_stmt = select(ManagementPlatform).where(
                ManagementPlatform.slug.in_(selected_slugs)
            )
            platform_by_slug = {
                platform.slug.lower(): platform for platform in session.scalars(platforms_stmt)
            }

            existing_links = {
                link.platform.slug.lower(): link
                for link in user.management_platform_links
            }

            # Add new selections
            for slug, platform in platform_by_slug.items():
                if slug not in existing_links:
                    session.add(
                        UserManagementPlatform(
                            user=user,
                            platform=platform,
                        )
                    )

            # Remove deselected links
            for slug, link in list(existing_links.items()):
                if slug not in selected_slugs:
                    session.delete(link)

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.exception("Failed to update management platforms: %s", exc)
