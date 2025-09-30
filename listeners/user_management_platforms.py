"""Utility helpers for per-user management platform data."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from db.models import ManagementPlatform, User, UserManagementPlatform
from db.session import get_session


@dataclass(frozen=True)
class UserPlatformSelection:
    """Representation of a user's management platform mapping."""

    slug: str
    display_name: str | None
    platform_user_id: str | None


def get_user_management_platforms(slack_user_id: str | None) -> list[UserPlatformSelection]:
    """Return the management platform choices for the given Slack user."""

    if not slack_user_id:
        return []

    with get_session() as session:
        stmt = (
            select(
                ManagementPlatform.slug,
                ManagementPlatform.display_name,
                UserManagementPlatform.platform_user_id,
            )
            .join(UserManagementPlatform, ManagementPlatform.id == UserManagementPlatform.management_platform_id)
            .join(User, User.id == UserManagementPlatform.user_id)
            .where(User.slack_user_id == slack_user_id)
        )

        rows = session.execute(stmt).all()

    selections: list[UserPlatformSelection] = []
    for slug, display_name, platform_user_id in rows:
        slug_value = (slug or "").strip()
        if not slug_value:
            continue
        display_value = (display_name or "").strip() or None
        selections.append(
            UserPlatformSelection(
                slug=slug_value,
                display_name=display_value,
                platform_user_id=platform_user_id,
            )
        )

    return selections


def list_management_platforms() -> list[ManagementPlatform]:
    """Return all management platforms configured in the system."""

    with get_session() as session:
        stmt = select(ManagementPlatform).order_by(ManagementPlatform.display_name)
        return list(session.scalars(stmt))
