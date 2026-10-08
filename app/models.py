from datetime import datetime, timezone

from sqlalchemy import func

from .extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Election(db.Model):
    __tablename__ = "elections"
    __table_args__ = (db.CheckConstraint("status IN ('DRAFT', 'SCHEDULED', 'ACTIVE', 'CLOSED')", name="ck_elections_status"),)

    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    STATUSES = {DRAFT, SCHEDULED, ACTIVE, CLOSED}

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    description = db.Column(db.String(2000), nullable=False, default="")
    start_at = db.Column(db.DateTime(timezone=True), nullable=True)
    end_at = db.Column(db.DateTime(timezone=True), nullable=True)
    status = db.Column(db.String(16), nullable=False, default=DRAFT)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    candidates = db.relationship("Candidate", backref="election", cascade="all, delete-orphan")


class Candidate(db.Model):
    __tablename__ = "candidates"
    __table_args__ = (
        db.UniqueConstraint("election_id", "name", name="uq_candidates_election_name"),
        db.UniqueConstraint("id", "election_id", name="uq_candidates_id_election"),
    )

    id = db.Column(db.Integer, primary_key=True)
    election_id = db.Column(db.Integer, db.ForeignKey("elections.id", ondelete="CASCADE"), nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(500), nullable=False, default="")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))


class Vote(db.Model):
    __tablename__ = "votes"
    __table_args__ = (
        db.UniqueConstraint("user_id", "election_id", name="uq_votes_user_election"),
        db.ForeignKeyConstraint(
            ["candidate_id", "election_id"],
            ["candidates.id", "candidates.election_id"],
            name="fk_votes_candidate_election",
            ondelete="RESTRICT",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    election_id = db.Column(db.Integer, db.ForeignKey("elections.id", ondelete="RESTRICT"), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )