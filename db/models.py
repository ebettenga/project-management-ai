"""SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy import Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    """Core user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    jira_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"User(id={self.id!r}, slack_user_id={self.slack_user_id!r}, "
            f"jira_user_id={self.jira_user_id!r})"
        )
