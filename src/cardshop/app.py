"""Application factory."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask
from flask_jwt_extended import JWTManager

from .api import bp
from .config import Config
from .db import Database, MongoDatabase


def create_app(config: Config | None = None, database: Database | None = None) -> Flask:
    """Build the app.

    `database` is injectable so the test suite can run the real request flow
    against an in-memory store - which is how register-then-login is actually
    verified rather than assumed.
    """
    cfg = config or Config.from_env()
    app = Flask(__name__)
    app.config["JWT_SECRET_KEY"] = cfg.jwt_secret_key
    app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(minutes=cfg.jwt_access_token_minutes)
    app.config["CARDSHOP_CONFIG"] = cfg
    app.config["CARDSHOP_DB"] = database or MongoDatabase(cfg.mongo_uri, cfg.mongo_database)

    JWTManager(app)
    app.register_blueprint(bp)
    return app


def main() -> None:  # pragma: no cover
    create_app().run()


if __name__ == "__main__":  # pragma: no cover
    main()
