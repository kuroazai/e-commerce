"""cardshop - inventory, pricing and sale automation for a card business.

Four things, each usable on its own:

    cardshop.vision      scan a card from a photo and identify it
    cardshop.market      what it is worth, and what you keep after fees
    cardshop.inventory   stock, listings, recorded sales
    cardshop.vendors     read sale emails, update stock, tell you

Plus `cardshop.agents`, which is an LLM used only where the deterministic code
above has genuinely run out of options.

The REST API:

    from cardshop import create_app, Config, InMemoryDatabase

    app = create_app(Config(), InMemoryDatabase())
    client = app.test_client()
    client.post("/register", json={"username": "u", "email": "e@x.com",
                                   "password": "correct horse battery"})
"""
from .auth import AuthError, AuthService
from .config import (
    AgentSettings,
    Config,
    ConfigError,
    MailSettings,
    MarketSettings,
    Settings,
    load_env_file,
)
from .db import Database, InMemoryDatabase, JsonFileDatabase, MongoDatabase
from .models import Return, Sale, User, YugiohCard
from .security import hash_password, verify_password
from .ygoprodeck import CardApiError, YgoProDeckClient

__version__ = "0.3.0"

__all__ = [
    "Config", "ConfigError", "Settings", "MarketSettings", "MailSettings",
    "AgentSettings", "load_env_file",
    "Database", "MongoDatabase", "InMemoryDatabase", "JsonFileDatabase",
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
