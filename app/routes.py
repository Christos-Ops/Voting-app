import json
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required
from redis.exceptions import RedisError, WatchError
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Candidate, Election, User, Vote


api_bp = Blueprint("api", __name__, url_prefix="/api")
VOTE_QUEUE_KEY = "voting:jobs"


def get_redis():
    return current_app.extensions["redis"]


def results_cache_key(election_id):
    return f"voting:results:{election_id}"


def invalidate_results_cache(election_id):
    try:
        get_redis().delete(results_cache_key(election_id))
    except RedisError:
        current_app.logger.exception("Unable to invalidate results cache for election %s", election_id)


def is_admin():
    return bool(get_jwt().get("is_admin", False))


def parse_datetime(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def election_open(election, now=None):
    now = now or datetime.now(timezone.utc)
    start_at = election.start_at
    end_at = election.end_at
    if start_at is None or end_at is None:
        return False
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    return election.status == Election.ACTIVE and start_at <= now < end_at


def election_json(election, user_id=None, include_candidates=False):
    count = db.session.scalar(
        db.select(func.count(Candidate.id)).where(Candidate.election_id == election.id)
    ) or 0
    vote_count = db.session.scalar(
        db.select(func.count(Vote.id)).where(Vote.election_id == election.id)
    ) or 0
    has_voted = False
    if user_id is not None:
        has_voted = db.session.scalar(
            db.select(Vote.id).where(Vote.election_id == election.id, Vote.user_id == user_id)
        ) is not None
        try:
            has_voted = has_voted or get_redis().get(f"voting:submitted:{election.id}:{user_id}") is not None
        except RedisError:
            current_app.logger.exception("Unable to check queued vote status")
    result = {
        "id": election.id,
        "name": election.name,
        "description": election.description,
        "start_at": election.start_at.isoformat() if election.start_at else None,
        "end_at": election.end_at.isoformat() if election.end_at else None,
        "status": election.status,
        "voting_open": election_open(election),
        "candidate_count": count,
        "vote_count": vote_count,
        "has_voted": has_voted,
    }
    if include_candidates:
        candidates = db.session.scalars(
            db.select(Candidate)
            .where(Candidate.election_id == election.id, Candidate.is_active.is_(True))
            .order_by(Candidate.id)
        ).all()
        result["candidates"] = [candidate_json(candidate) for candidate in candidates]
    return result


def candidate_json(candidate):
    return {"id": candidate.id, "election_id": candidate.election_id, "name": candidate.name, "description": candidate.description}


def result_payload(election_id):
    rows = db.session.execute(
        db.select(Candidate.id, Candidate.name, func.count(Vote.id).label("votes"))
        .outerjoin(Vote, (Vote.candidate_id == Candidate.id) & (Vote.election_id == election_id))
        .where(Candidate.election_id == election_id, Candidate.is_active.is_(True))
        .group_by(Candidate.id, Candidate.name)
        .order_by(Candidate.id)
    ).all()
    return {"election_id": election_id, "results": [{"candidate_id": row.id, "candidate": row.name, "votes": row.votes} for row in rows]}


def election_or_404(election_id):
    election = db.session.get(Election, election_id)
    if election is None:
        return None, (jsonify(error="Election not found."), 404)
    return election, None


@api_bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        get_redis().ping()
    except Exception:
        current_app.logger.exception("Health check failed")
        return jsonify(status="unhealthy"), 503
    return jsonify(status="ok")


@api_bp.get("/elections")
@jwt_required(optional=True)
def elections():
    statement = db.select(Election).order_by(Election.start_at, Election.id)
    if not is_admin():
        statement = statement.where(Election.status != Election.DRAFT)
    rows = db.session.scalars(statement).all()
    identity = get_jwt_identity()
    user_id = int(identity) if identity is not None else None
    return jsonify(elections=[election_json(row, user_id) for row in rows])


@api_bp.get("/elections/<int:election_id>")
@jwt_required(optional=True)
def election_detail(election_id):
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status == Election.DRAFT and not is_admin():
        return jsonify(error="Election not found."), 404
    identity = get_jwt_identity()
    user_id = int(identity) if identity is not None else None
    return jsonify(election=election_json(election, user_id, include_candidates=True))


@api_bp.get("/elections/<int:election_id>/results")
@jwt_required(optional=True)
def election_results(election_id):
    election, error = election_or_404(election_id)
    if error:
        return error
    if not is_admin() and election.status != Election.CLOSED:
        return jsonify(error="Results will be available after this election closes."), 403
    key = results_cache_key(election_id)
    client = get_redis()
    try:
        cached = client.get(key)
        if cached is not None:
            return jsonify(json.loads(cached))
    except (RedisError, ValueError, TypeError):
        current_app.logger.exception("Results cache read failed; falling back to PostgreSQL")
    result = result_payload(election_id)
    try:
        client.setex(key, current_app.config["RESULTS_CACHE_TTL"], json.dumps(result))
    except RedisError:
        current_app.logger.exception("Results cache write failed")
    return jsonify(result)


@api_bp.post("/elections/<int:election_id>/votes")
@jwt_required()
def submit_vote(election_id):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    candidate_id = data.get("candidate_id")
    if not isinstance(candidate_id, int) or isinstance(candidate_id, bool):
        return jsonify(error="candidate_id must be an integer."), 400
    election, error = election_or_404(election_id)
    if error:
        return error
    if not election_open(election):
        return jsonify(error="This election is not currently accepting votes."), 409
    candidate = db.session.get(Candidate, candidate_id)
    if candidate is None or candidate.election_id != election_id or not candidate.is_active:
        return jsonify(error="Candidate not found in this election."), 404

    user_id = int(get_jwt_identity())
    if db.session.scalar(db.select(Vote.id).where(Vote.user_id == user_id, Vote.election_id == election_id)):
        return jsonify(error="A vote has already been submitted for this election."), 409
    reservation_key = f"voting:submitted:{election_id}:{user_id}"
    payload = json.dumps({"user_id": user_id, "election_id": election_id, "candidate_id": candidate_id})
    client = get_redis()
    try:
        with client.pipeline() as pipe:
            for _ in range(5):
                try:
                    pipe.watch(reservation_key)
                    if pipe.get(reservation_key) is not None:
                        return jsonify(error="A vote has already been submitted for this election."), 409
                    pipe.multi()
                    pipe.set(reservation_key, "1")
                    pipe.rpush(VOTE_QUEUE_KEY, payload)
                    pipe.execute()
                    break
                except WatchError:
                    continue
            else:
                return jsonify(error="Vote submission is busy; please retry."), 503
    except RedisError:
        current_app.logger.exception("Unable to enqueue vote for user %s", user_id)
        return jsonify(error="Voting is temporarily unavailable."), 503
    return jsonify(status="queued", message="Vote submitted for processing."), 202


@api_bp.get("/admin/stats")
@jwt_required()
def admin_stats():
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    return jsonify(
        total_votes=db.session.scalar(db.select(func.count(Vote.id))) or 0,
        total_users=db.session.scalar(db.select(func.count(User.id))) or 0,
        total_elections=db.session.scalar(db.select(func.count(Election.id))) or 0,
        active_elections=db.session.scalar(db.select(func.count(Election.id)).where(Election.status == Election.ACTIVE)) or 0,
    )


@api_bp.get("/admin/elections")
@jwt_required()
def admin_elections():
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    rows = db.session.scalars(db.select(Election).order_by(Election.created_at.desc())).all()
    return jsonify(elections=[election_json(row) for row in rows])


@api_bp.post("/admin/elections")
@jwt_required()
def create_election():
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    name, description = data.get("name", ""), data.get("description", "")
    status = data.get("status", Election.DRAFT)
    start_at, end_at = parse_datetime(data.get("start_at")), parse_datetime(data.get("end_at"))
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
        return jsonify(error="Election name is required and must be at most 160 characters."), 400
    if not isinstance(description, str) or len(description) > 2000:
        return jsonify(error="Description must be a string of at most 2000 characters."), 400
    if not isinstance(status, str) or status not in {Election.DRAFT, Election.SCHEDULED}:
        return jsonify(error="New elections must be DRAFT or SCHEDULED."), 400
    if start_at is None or end_at is None or start_at >= end_at:
        return jsonify(error="Valid timezone-aware start_at and end_at values are required."), 400
    election = Election(name=name.strip(), description=description.strip(), start_at=start_at, end_at=end_at, status=status)
    db.session.add(election)
    db.session.commit()
    return jsonify(election=election_json(election)), 201


@api_bp.patch("/admin/elections/<int:election_id>")
@jwt_required()
def update_election(election_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status not in {Election.DRAFT, Election.SCHEDULED}:
        return jsonify(error="Only draft or scheduled elections can be edited."), 409
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    if "name" in data:
        name = data["name"]
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 160:
            return jsonify(error="Election name is required and must be at most 160 characters."), 400
        election.name = name.strip()
    if "description" in data:
        if not isinstance(data["description"], str) or len(data["description"]) > 2000:
            return jsonify(error="Description must be a string of at most 2000 characters."), 400
        election.description = data["description"].strip()
    if "start_at" in data:
        election.start_at = parse_datetime(data["start_at"])
    if "end_at" in data:
        election.end_at = parse_datetime(data["end_at"])
    if "status" in data:
        if not isinstance(data["status"], str) or data["status"] not in {Election.DRAFT, Election.SCHEDULED}:
            return jsonify(error="Use the activate or close action to change lifecycle state."), 400
        if election.status == Election.SCHEDULED and data["status"] == Election.DRAFT:
            return jsonify(error="A scheduled election cannot return to draft."), 409
        election.status = data["status"]
    if election.start_at is None or election.end_at is None or election.start_at >= election.end_at:
        return jsonify(error="Valid timezone-aware start_at and end_at values are required."), 400
    db.session.commit()
    return jsonify(election=election_json(election))


@api_bp.post("/admin/elections/<int:election_id>/activate")
@jwt_required()
def activate_election(election_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status != Election.SCHEDULED:
        return jsonify(error="Only scheduled elections can be activated."), 409
    if election.start_at is None or election.end_at is None or election.start_at >= election.end_at:
        return jsonify(error="Set a valid voting window before activation."), 409
    if not db.session.scalar(db.select(Candidate.id).where(Candidate.election_id == election_id)):
        return jsonify(error="Add at least one candidate before activation."), 409
    election.status = Election.ACTIVE
    db.session.commit()
    return jsonify(election=election_json(election))


@api_bp.post("/admin/elections/<int:election_id>/close")
@jwt_required()
def close_election(election_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status == Election.CLOSED:
        return jsonify(election=election_json(election))
    if election.status not in {Election.SCHEDULED, Election.ACTIVE}:
        return jsonify(error="Only scheduled or active elections can be closed."), 409
    election.status = Election.CLOSED
    db.session.commit()
    return jsonify(election=election_json(election))


@api_bp.get("/admin/elections/<int:election_id>/candidates")
@jwt_required()
def admin_candidates(election_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    rows = db.session.scalars(db.select(Candidate).where(Candidate.election_id == election_id).order_by(Candidate.id)).all()
    return jsonify(candidates=[candidate_json(candidate) for candidate in rows])


@api_bp.post("/admin/elections/<int:election_id>/candidates")
@jwt_required()
def create_candidate(election_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status not in {Election.DRAFT, Election.SCHEDULED}:
        return jsonify(error="Candidates can only be changed before activation."), 409
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    name, description = data.get("name", ""), data.get("description", "")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 120:
        return jsonify(error="Candidate name is required and must be at most 120 characters."), 400
    if not isinstance(description, str) or len(description) > 500:
        return jsonify(error="Description must be a string of at most 500 characters."), 400
    candidate = Candidate(election_id=election_id, name=name.strip(), description=description.strip())
    db.session.add(candidate)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="A candidate with that name already exists in this election."), 409
    invalidate_results_cache(election_id)
    return jsonify(candidate=candidate_json(candidate)), 201


@api_bp.patch("/admin/elections/<int:election_id>/candidates/<int:candidate_id>")
@jwt_required()
def update_candidate(election_id, candidate_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status not in {Election.DRAFT, Election.SCHEDULED}:
        return jsonify(error="Candidates can only be changed before activation."), 409
    candidate = db.session.get(Candidate, candidate_id)
    if candidate is None or candidate.election_id != election_id:
        return jsonify(error="Candidate not found in this election."), 404
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    if "name" in data:
        if not isinstance(data["name"], str) or not data["name"].strip() or len(data["name"].strip()) > 120:
            return jsonify(error="Candidate name is required and must be at most 120 characters."), 400
        candidate.name = data["name"].strip()
    if "description" in data:
        if not isinstance(data["description"], str) or len(data["description"]) > 500:
            return jsonify(error="Description must be a string of at most 500 characters."), 400
        candidate.description = data["description"].strip()
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="A candidate with that name already exists in this election."), 409
    invalidate_results_cache(election_id)
    return jsonify(candidate=candidate_json(candidate))


@api_bp.delete("/admin/elections/<int:election_id>/candidates/<int:candidate_id>")
@jwt_required()
def delete_candidate(election_id, candidate_id):
    if not is_admin():
        return jsonify(error="Administrator access required."), 403
    election, error = election_or_404(election_id)
    if error:
        return error
    if election.status not in {Election.DRAFT, Election.SCHEDULED}:
        return jsonify(error="Candidates can only be changed before activation."), 409
    candidate = db.session.get(Candidate, candidate_id)
    if candidate is None or candidate.election_id != election_id:
        return jsonify(error="Candidate not found in this election."), 404
    db.session.delete(candidate)
    db.session.commit()
    invalidate_results_cache(election_id)
    return "", 204