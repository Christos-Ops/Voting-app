import click
from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import create_access_token, get_jwt, get_jwt_identity, jwt_required
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .models import User


auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    email = data.get("email", "")
    password = data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Email and password must be strings."), 400
    email = email.strip().lower()
    if "@" not in email or len(email) > 255 or len(password) < 8:
        return jsonify(error="Provide a valid email and a password of at least 8 characters."), 400
    if db.session.scalar(db.select(User).where(User.email == email)):
        return jsonify(error="An account with that email already exists."), 409

    user = User(email=email, password_hash=generate_password_hash(password))
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="An account with that email already exists."), 409
    except Exception:
        db.session.rollback()
        current_app.logger.exception("User registration failed")
        return jsonify(error="Unable to create account."), 500
    return jsonify(id=user.id, email=user.email), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(error="A JSON object is required."), 400
    email = data.get("email", "")
    password = data.get("password", "")
    if not isinstance(email, str) or not isinstance(password, str):
        return jsonify(error="Invalid email or password."), 401
    user = db.session.scalar(db.select(User).where(User.email == email.strip().lower()))
    if user is None or not check_password_hash(user.password_hash, password):
        return jsonify(error="Invalid email or password."), 401
    token = create_access_token(identity=str(user.id), additional_claims={"is_admin": user.is_admin})
    return jsonify(access_token=token, token_type="Bearer")


@auth_bp.get("/me")
@jwt_required()
def current_user():
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        return jsonify(error="Account not found."), 404
    return jsonify(id=user.id, email=user.email, is_admin=bool(get_jwt().get("is_admin", False)))


@click.command("create-admin")
@click.argument("email")
def create_admin_command(email):
    """Create an administrator account, prompting for its password."""
    email = email.strip().lower()
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    if "@" not in email or len(password) < 8:
        raise click.ClickException("Provide a valid email and a password of at least 8 characters.")
    if db.session.scalar(db.select(User).where(User.email == email)):
        raise click.ClickException("An account with that email already exists.")
    db.session.add(User(email=email, password_hash=generate_password_hash(password), is_admin=True))
    db.session.commit()
    click.echo(f"Administrator account created for {email}.")