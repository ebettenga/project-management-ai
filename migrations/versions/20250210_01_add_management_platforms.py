"""add management platform tables

Revision ID: 20250210_01
Revises: 20250208_01
Create Date: 2025-02-10 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250210_01"
down_revision = "20250208_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "management_platforms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.UniqueConstraint("slug", name="uq_management_platforms_slug"),
    )

    op.create_table(
        "user_management_platforms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("management_platform_id", sa.Integer(), nullable=False),
        sa.Column("platform_user_id", sa.String(length=128), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["management_platform_id"], ["management_platforms.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id",
            "management_platform_id",
            name="uq_user_management_platforms_user_platform",
        ),
    )

    op.drop_column("users", "management_platform_user_id")

    platform_table = sa.table(
        "management_platforms",
        sa.column("slug", sa.String(length=64)),
        sa.column("display_name", sa.String(length=128)),
    )

    op.bulk_insert(
        platform_table,
        [
            {"slug": "jira", "display_name": "Jira"},
            {"slug": "asana", "display_name": "Asana"},
        ],
    )


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("management_platform_user_id", sa.String(length=64), nullable=True),
    )
    op.drop_table("user_management_platforms")
    op.drop_table("management_platforms")
