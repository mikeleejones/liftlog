"""Add the singleton AI program-builder draft.

Revision ID: 20260828_02
Revises: 20260827_01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260828_02"
down_revision = "20260827_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program_draft",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("messages_json", sa.Text(), nullable=False),
        sa.Column("program_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.CheckConstraint("id = 1"),
    )


def downgrade() -> None:
    op.drop_table("program_draft")
