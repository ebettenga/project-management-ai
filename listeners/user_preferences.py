"""Helpers for retrieving and formatting user preference data."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.models import ManagementPlatform, User, UserManagementPlatform
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


def build_user_metadata_message(slack_user_id: str) -> dict[str, str] | None:
    """Return a system message describing the Slack user's metadata for the model."""

    if not slack_user_id:
        return None

    with get_session() as session:
        stmt = (
            select(User)
            .options(
                selectinload(User.management_platform_links)
                .selectinload(UserManagementPlatform.platform)
            )
            .where(User.slack_user_id == slack_user_id)
        )
        user = session.execute(stmt).scalar_one_or_none()

    if user is None:
        return None

    lines: list[str] = ["User Metadata:"]

    def add_line(label: str, value: str | None) -> None:
        if value:
            lines.append(f"- {label}: {value}")

    add_line("Slack User ID", user.slack_user_id)
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    add_line("Full Name", full_name.strip() or None)
    add_line("First Name", (user.first_name or "").strip() or None)
    add_line("Last Name", (user.last_name or "").strip() or None)

    platform_lines: list[str] = []
    for link in user.management_platform_links:
        platform: ManagementPlatform | None = link.platform
        slug = platform.slug if platform else None
        display = platform.display_name if platform else None
        name = display or slug
        if not name:
            continue
        platform_line = f"  - {name}"
        if link.platform_user_id:
            platform_line += f" (platform_user_id: {link.platform_user_id})"
        platform_lines.append(platform_line)

    if platform_lines:
        lines.append("- Management Platforms:")
        lines.extend(platform_lines)

    if len(lines) == 1:
        return None

    text = "\n".join(lines)
    return {"role": "system", "content": text}
