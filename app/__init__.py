import logging
import os

import click
import redis
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate, upgrade

from .auth import auth_bp, create_admin_command
from .extensions import db
from .routes import api_bp


jwt = JWTManager()
migrate = Migrate()


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_mapping(
        SQLALCHEMY_DATABASE_URI=os.getenv("DATABASE_URL", "postgresql+psycopg://voting:voting@localhost:5432/voting"),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY", "development-only-change-me"),
        REDIS_URL=os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        RESULTS_CACHE_TTL=int(os.getenv("RESULTS_CACHE_TTL", "30")),
    )
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    app.extensions["redis"] = app.config.get("REDIS_CLIENT") or redis.Redis.from_url(
        app.config["REDIS_URL"], decode_responses=True
    )
    app.register_blueprint(auth_bp)
    app.register_blueprint(api_bp)
    app.cli.add_command(create_admin_command)

    @app.cli.command("init-db")
    def init_db_command():
        """Apply the application database migrations."""
        upgrade(directory="migrations")
        click.echo("Application database is up to date.")

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Resource not found."), 404

    @app.errorhandler(500)
    def internal_error(_error):
        db.session.rollback()
        app.logger.exception("Unhandled application error")
        return jsonify(error="Internal server error."), 500

    return app