"""create users table

Revision ID: 20250208_01
Revises: 
Create Date: 2025-02-08 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20250208_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("slack_user_id", sa.String(length=64), nullable=False),
        sa.Column("management_platform_user_id", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=128), nullable=True),
        sa.Column("last_name", sa.String(length=128), nullable=True),
        sa.Column("model_preferences", sa.JSON(), nullable=True),
        sa.UniqueConstraint("slack_user_id", name="uq_users_slack_user_id"),
    )


def downgrade() -> None:
    op.drop_table("users")
