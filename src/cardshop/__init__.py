"""cardshop - a small REST API for a trading-card marketplace.

    from cardshop import create_app, Config, InMemoryDatabase

    app = create_app(Config(), InMemoryDatabase())
    client = app.test_client()
    client.post("/register", json={"username": "u", "email": "e@x.com",
                                   "password": "correct horse battery"})
"""
from .auth import AuthError, AuthService
from .config import Config, ConfigError
from .db import Database, InMemoryDatabase, MongoDatabase
from .models import Return, Sale, User, YugiohCard
from .security import hash_password, verify_password
from .ygoprodeck import CardApiError, YgoProDeckClient

__version__ = "0.2.0"

__all__ = [
    "Config", "ConfigError",
    "Database", "MongoDatabase", "InMemoryDatabase",
    "User", "YugiohCard", "Sale", "Return",
    "hash_password", "verify_password",
    "AuthService", "AuthError",
    "YgoProDeckClient", "CardApiError",
    "__version__",
]


def create_app(*args, **kwargs):
    """Imported lazily so `import cardshop` does not require Flask."""
    from .app import create_app as _create_app

    return _create_app(*args, **kwargs)
