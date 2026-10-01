"""Configuration, from the environment.

The original hardcoded `JWT_SECRET_KEY = "your-secret-key"` in a public
repository. Anyone who read the source could forge a token for any user,
including an admin one. A signing key is not configuration you can ship.

So: the key comes from the environment, and the app refuses to start in
production without one. Development gets a generated ephemeral key, which means
tokens stop working when you restart - that is the intended nudge.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

PLACEHOLDER_SECRETS = frozenset({
    "your-secret-key", "secret", "changeme", "change-me", "dev", "test", "",
})


class ConfigError(RuntimeError):
    """The configuration is unsafe or incomplete."""


def _generated_dev_secret() -> str:
    return secrets.token_urlsafe(48)


@dataclass
class Config:
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_database: str = "cardshop"
    jwt_secret_key: str = field(default_factory=_generated_dev_secret)
    jwt_access_token_minutes: int = 60
    production: bool = False
    request_timeout: float = 10.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> Config:
        source = os.environ if env is None else env
        production = source.get("CARDSHOP_ENV", "development").lower() == "production"
        secret = source.get("JWT_SECRET_KEY", "")

        if production:
            if secret.strip().lower() in PLACEHOLDER_SECRETS:
                raise ConfigError(
                    "JWT_SECRET_KEY must be set to a real secret in production. Generate "
                    "one with: python -c "
                    "'import secrets; print(secrets.token_urlsafe(48))'"
                )
            if len(secret) < 32:
                raise ConfigError("JWT_SECRET_KEY must be at least 32 characters")

        return cls(
            mongo_uri=source.get("MONGO_URI", "mongodb://localhost:27017"),
            mongo_database=source.get("MONGO_DATABASE", "cardshop"),
            jwt_secret_key=secret or _generated_dev_secret(),
            jwt_access_token_minutes=int(source.get("JWT_ACCESS_TOKEN_MINUTES", "60")),
            production=production,
        )
