import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import Candidate, Election, User, Vote


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []
        self.watched_key = None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def watch(self, key):
        self.watched_key = key

    def get(self, key):
        return self.client.values.get(key)

    def multi(self):
        return None

    def set(self, key, value):
        self.operations.append(("set", key, value))

    def rpush(self, key, value):
        self.operations.append(("rpush", key, value))

    def execute(self):
        for operation, key, value in self.operations:
            if operation == "set":
                self.client.values[key] = value
            else:
                self.client.lists.setdefault(key, []).append(value)
        self.operations.clear()


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}

    def pipeline(self):
        return FakePipeline(self)

    def get(self, key):
        return self.values.get(key)

    def setex(self, key, _ttl, value):
        self.values[key] = value

    def delete(self, key):
        self.values.pop(key, None)

    def ping(self):
        return True


@pytest.fixture
def client():
    fake_redis = FakeRedis()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "JWT_SECRET_KEY": "test-secret-key-at-least-32-characters-long",
        "REDIS_CLIENT": fake_redis,
    })
    with app.app_context():
        @event.listens_for(db.engine, "connect")
        def enable_sqlite_foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")

        db.create_all()
        voter = User(email="voter@example.com", password_hash=generate_password_hash("password123"))
        admin = User(email="admin@example.com", password_hash=generate_password_hash("password123"), is_admin=True)
        now = datetime.now(timezone.utc)
        elections = [
            Election(name="Student Election", status=Election.ACTIVE, start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)),
            Election(name="Department Election", status=Election.ACTIVE, start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)),
            Election(name="Draft Election", status=Election.DRAFT, start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)),
            Election(name="Scheduled Election", status=Election.SCHEDULED, start_at=now - timedelta(hours=1), end_at=now + timedelta(days=1)),
            Election(name="Future Election", status=Election.ACTIVE, start_at=now + timedelta(days=1), end_at=now + timedelta(days=2)),
            Election(name="Closed Election", status=Election.CLOSED, start_at=now - timedelta(days=2), end_at=now - timedelta(days=1)),
        ]
        db.session.add_all([voter, admin, *elections])
        db.session.flush()
        db.session.add_all([
            Candidate(election_id=elections[0].id, name="Option A"),
            Candidate(election_id=elections[0].id, name="Option B"),
            Candidate(election_id=elections[1].id, name="Option A"),
        ])
        db.session.commit()
        yield app.test_client(), fake_redis
        db.drop_all()
        db.session.remove()


def token_for(client, email):
    response = client.post("/api/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json["access_token"]


def test_registration_and_login(client):
    http, _redis = client
    assert http.post("/api/auth/register", json=[]).status_code == 400
    response = http.post("/api/auth/register", json={"email": "new@example.com", "password": "password123"})
    assert response.status_code == 201
    assert http.post("/api/auth/register", json={"email": "new@example.com", "password": "password123"}).status_code == 409
    assert http.post("/api/auth/login", json={"email": "new@example.com", "password": "incorrect"}).status_code == 401
    login = http.post("/api/auth/login", json={"email": "new@example.com", "password": "password123"})
    assert login.status_code == 200
    identity = http.get("/api/auth/me", headers={"Authorization": f"Bearer {login.json['access_token']}"})
    assert identity.json["email"] == "new@example.com"
    assert identity.json["is_admin"] is False


def test_vote_created_at_has_database_default_for_raw_sql_insert(client):
    http, _redis = client
    with http.application.app_context():
        db.session.execute(
            db.text(
                "INSERT INTO votes (user_id, election_id, candidate_id) "
                "VALUES (:user_id, :election_id, :candidate_id)"
            ),
            {"user_id": 1, "election_id": 1, "candidate_id": 1},
        )
        db.session.commit()
        created_at = db.session.scalar(
            db.select(Vote.created_at).where(Vote.user_id == 1, Vote.election_id == 1)
        )
    assert created_at is not None


def test_vote_is_unique_per_election_and_jobs_are_scoped(client):
    http, fake_redis = client
    headers = {"Authorization": f"Bearer {token_for(http, 'voter@example.com')}"}
    assert http.post("/api/elections/1/votes", json=[], headers=headers).status_code == 400
    first = http.post("/api/elections/1/votes", json={"candidate_id": 1}, headers=headers)
    second = http.post("/api/elections/1/votes", json={"candidate_id": 2}, headers=headers)
    wrong_election_candidate = http.post("/api/elections/2/votes", json={"candidate_id": 1}, headers=headers)
    another_election = http.post("/api/elections/2/votes", json={"candidate_id": 3}, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 409
    assert wrong_election_candidate.status_code == 404
    assert another_election.status_code == 202
    jobs = [json.loads(job) for job in fake_redis.lists["voting:jobs"]]
    assert jobs == [
        {"user_id": 1, "election_id": 1, "candidate_id": 1},
        {"user_id": 1, "election_id": 2, "candidate_id": 3},
    ]
    assert "voting:submitted:1:1" in fake_redis.values
    assert "voting:submitted:2:1" in fake_redis.values
    status = http.get("/api/elections", headers=headers)
    election_status = next(item for item in status.json["elections"] if item["id"] == 1)
    assert election_status["has_voted"] is True


def test_draft_scheduled_future_and_closed_elections_reject_votes(client):
    http, _redis = client
    headers = {"Authorization": f"Bearer {token_for(http, 'voter@example.com')}"}
    for election_id in (3, 4, 5, 6):
        response = http.post(f"/api/elections/{election_id}/votes", json={"candidate_id": 1}, headers=headers)
        assert response.status_code == 409


def test_admin_election_lifecycle_and_authorization(client):
    http, fake_redis = client
    voter_headers = {"Authorization": f"Bearer {token_for(http, 'voter@example.com')}"}
    admin_headers = {"Authorization": f"Bearer {token_for(http, 'admin@example.com')}"}
    assert http.get("/api/admin/elections", headers=voter_headers).status_code == 403
    assert http.post("/api/admin/elections", json={"name": "Nope"}, headers=voter_headers).status_code == 403
    now = datetime.now(timezone.utc)
    payload = {
        "name": "2026 Alumni Election",
        "description": "Alumni representatives",
        "start_at": (now - timedelta(minutes=5)).isoformat(),
        "end_at": (now + timedelta(days=1)).isoformat(),
        "status": Election.SCHEDULED,
    }
    created = http.post("/api/admin/elections", json=payload, headers=admin_headers)
    assert created.status_code == 201
    election_id = created.json["election"]["id"]
    assert http.get(f"/api/elections/{election_id}/results", headers=admin_headers).status_code == 200
    assert f"voting:results:{election_id}" in fake_redis.values
    candidate = http.post(
        f"/api/admin/elections/{election_id}/candidates",
        json={"name": "Candidate One", "description": "Profile"},
        headers=admin_headers,
    )
    assert candidate.status_code == 201
    assert f"voting:results:{election_id}" not in fake_redis.values
    candidate_id = candidate.json["candidate"]["id"]
    edited = http.patch(
        f"/api/admin/elections/{election_id}/candidates/{candidate_id}",
        json={"name": "Candidate Updated", "description": "Updated profile"},
        headers=admin_headers,
    )
    assert edited.status_code == 200
    assert edited.json["candidate"]["name"] == "Candidate Updated"
    assert http.post(f"/api/admin/elections/{election_id}/activate", headers=admin_headers).status_code == 200
    assert http.patch(
        f"/api/admin/elections/{election_id}/candidates/{candidate_id}",
        json={"name": "Too Late"},
        headers=admin_headers,
    ).status_code == 409
    assert http.post(f"/api/admin/elections/{election_id}/close", headers=admin_headers).json["election"]["status"] == Election.CLOSED
    assert http.post(f"/api/admin/elections/{election_id}/close", headers=admin_headers).status_code == 200


def test_election_results_are_isolated_and_cached_per_election(client):
    http, fake_redis = client
    admin_headers = {"Authorization": f"Bearer {token_for(http, 'admin@example.com')}"}
    with http.application.app_context():
        db.session.add_all([
            Vote(user_id=1, election_id=1, candidate_id=1),
            Vote(user_id=1, election_id=2, candidate_id=3),
        ])
        db.session.commit()
    assert http.get("/api/elections/1").status_code == 200
    assert http.get("/api/elections/1/results").status_code == 403
    first = http.get("/api/elections/1/results", headers=admin_headers)
    second = http.get("/api/elections/2/results", headers=admin_headers)
    assert first.json["results"][0]["votes"] == 1
    assert second.json["results"][0]["votes"] == 1
    assert "voting:results:1" in fake_redis.values
    assert "voting:results:2" in fake_redis.values


def test_database_enforces_one_vote_per_user_per_election(client):
    from sqlalchemy.exc import IntegrityError

    http, _redis = client
    with http.application.app_context():
        db.session.add(Vote(user_id=1, election_id=1, candidate_id=3))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.add(Vote(user_id=1, election_id=1, candidate_id=1))
        db.session.commit()
        db.session.add(Vote(user_id=1, election_id=1, candidate_id=2))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        db.session.add(Vote(user_id=1, election_id=2, candidate_id=3))
        db.session.commit()


def test_results_cache_and_admin_access(client):
    http, fake_redis = client
    admin_headers = {"Authorization": f"Bearer {token_for(http, 'admin@example.com')}"}
    results = http.get("/api/elections/1/results", headers=admin_headers)
    assert results.status_code == 200
    assert results.json["results"][0]["votes"] == 0
    assert "voting:results:1" in fake_redis.values

    voter_headers = {"Authorization": f"Bearer {token_for(http, 'voter@example.com')}"}
    assert http.get("/api/admin/stats", headers=voter_headers).status_code == 403
    stats = http.get("/api/admin/stats", headers=admin_headers)
    assert stats.status_code == 200
    assert stats.json["total_users"] == 2
    assert stats.json["total_elections"] == 6
    created = http.post(
        "/api/admin/elections/1/candidates",
        json={"name": "Option C"},
        headers=admin_headers,
    )
    assert created.status_code == 409


def test_health_reports_dependencies(client):
    http, _redis = client
    assert http.get("/api/health").json == {"status": "ok"}