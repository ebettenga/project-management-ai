"""SQLAlchemy models."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .base import Base


class User(Base):
    """Core user model."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slack_user_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_preferences: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    management_platform_links: Mapped[list["UserManagementPlatform"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"User(id={self.id!r}, slack_user_id={self.slack_user_id!r})"
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


class ManagementPlatform(Base):
    """Platform configuration that users can opt into (e.g., Jira, Asana)."""

    __tablename__ = "management_platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    user_links: Mapped[list["UserManagementPlatform"]] = relationship(
        back_populates="platform",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"ManagementPlatform(id={self.id!r}, slug={self.slug!r})"


class UserManagementPlatform(Base):
    """Association between users and their chosen management platforms."""

    __tablename__ = "user_management_platforms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    management_platform_id: Mapped[int] = mapped_column(
        ForeignKey("management_platforms.id", ondelete="CASCADE"),
        nullable=False,
    )
    platform_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    user: Mapped[User] = relationship(back_populates="management_platform_links")
    platform: Mapped[ManagementPlatform] = relationship(back_populates="user_links")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            "UserManagementPlatform("
            f"user_id={self.user_id!r}, platform_id={self.management_platform_id!r}, "
            f"platform_user_id={self.platform_user_id!r})"
        )
