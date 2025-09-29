"""SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from .base import Base


class User(Base):
    """Core user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    management_platform_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"User(id={self.id!r}, slack_user_id={self.slack_user_id!r}, "
            f"management_platform_user_id={self.management_platform_user_id!r})"
        )

    @classmethod
    def create_if_not_exists(cls, session: Session, slack_user_id: str) -> "User":
        """Return the existing user or create a new record for the Slack ID."""

        user = session.query(cls).filter_by(slack_user_id=slack_user_id).one_or_none()
        if user is not None:
            return user

        user = cls(slack_user_id=slack_user_id)
        session.add(user)
        session.flush()  # ensure `id` is populated for downstream callers
        return user
