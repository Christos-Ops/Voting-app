"""Add election events and scope candidates and votes.

Revision ID: 20261002_01
Revises:
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect, text


revision = "20261002_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" not in tables:
        from app.extensions import db
        from app import models

        db.metadata.create_all(bind=bind)
        return

    op.create_table(
        "elections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="DRAFT"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'CLOSED')", name="ck_elections_status"),
    )

    candidate_count = bind.execute(text("SELECT count(*) FROM candidates")).scalar_one() if "candidates" in tables else 0
    vote_count = bind.execute(text("SELECT count(*) FROM votes")).scalar_one() if "votes" in tables else 0
    legacy_election_id = None
    if candidate_count or vote_count:
        legacy_name = os.getenv("LEGACY_ELECTION_NAME", "").strip()
        if not legacy_name:
            raise RuntimeError(
                "Set LEGACY_ELECTION_NAME to migrate existing candidates or votes into a closed legacy election."
            )
        if len(legacy_name) > 160:
            raise RuntimeError("LEGACY_ELECTION_NAME must be at most 160 characters.")
        legacy_election_id = bind.execute(
            text(
                "INSERT INTO elections (name, description, status, created_at) "
                "VALUES (:name, 'Migrated legacy voting data', 'CLOSED', CURRENT_TIMESTAMP) RETURNING id"
            ),
            {"name": legacy_name},
        ).scalar_one()

    if "candidates" in tables:
        for constraint in inspect(bind).get_unique_constraints("candidates"):
            if constraint.get("column_names") == ["name"]:
                op.drop_constraint(constraint["name"], "candidates", type_="unique")
        op.add_column("candidates", sa.Column("election_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_candidates_election_id_elections", "candidates", "elections", ["election_id"], ["id"], ondelete="CASCADE")
        if candidate_count:
            bind.execute(text("UPDATE candidates SET election_id = :election_id"), {"election_id": legacy_election_id})
        op.alter_column("candidates", "election_id", nullable=False)
        op.create_index("ix_candidates_election_id", "candidates", ["election_id"])
        op.create_unique_constraint("uq_candidates_election_name", "candidates", ["election_id", "name"])
        op.create_unique_constraint("uq_candidates_id_election", "candidates", ["id", "election_id"])

    if "votes" in tables:
        op.add_column("votes", sa.Column("election_id", sa.Integer(), nullable=True))
        op.create_foreign_key("fk_votes_election_id_elections", "votes", "elections", ["election_id"], ["id"], ondelete="RESTRICT")
        if vote_count:
            bind.execute(
                text(
                    "UPDATE votes SET election_id = candidates.election_id "
                    "FROM candidates WHERE votes.candidate_id = candidates.id"
                )
            )
        op.alter_column("votes", "election_id", nullable=False)
        op.create_index("ix_votes_election_id", "votes", ["election_id"])
        for constraint in inspect(bind).get_foreign_keys("votes"):
            if constraint.get("constrained_columns") == ["candidate_id"]:
                op.drop_constraint(constraint["name"], "votes", type_="foreignkey")
        op.create_foreign_key(
            "fk_votes_candidate_election",
            "votes",
            "candidates",
            ["candidate_id", "election_id"],
            ["id", "election_id"],
            ondelete="RESTRICT",
        )
        for constraint in inspect(bind).get_unique_constraints("votes"):
            if constraint.get("column_names") == ["user_id"]:
                op.drop_constraint(constraint["name"], "votes", type_="unique")
        op.create_unique_constraint("uq_votes_user_election", "votes", ["user_id", "election_id"])


def downgrade():
    raise RuntimeError("This election migration is intentionally irreversible because votes may exist in multiple elections.")