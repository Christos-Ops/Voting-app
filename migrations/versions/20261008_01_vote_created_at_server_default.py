"""Add database default for vote creation timestamps.

Revision ID: 20261008_01
Revises: 20261002_01
"""
import sqlalchemy as sa
from alembic import op


revision = "20261008_01"
down_revision = "20261002_01"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "votes",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=sa.func.now(),
    )


def downgrade():
    op.alter_column(
        "votes",
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        existing_nullable=False,
        server_default=None,
    )