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


# ---------------------------------------------------------------------------
# .env loading
#
# Hand-rolled rather than depending on python-dotenv. It is twenty lines, it
# removes a dependency from the install, and the file format is not complicated
# enough to justify one. It does NOT overwrite variables already set in the
# environment, so a real deployment's config always wins over a stray .env.
# ---------------------------------------------------------------------------

def load_env_file(path: str = ".env", *, override: bool = False) -> dict[str, str]:
    """Read KEY=value lines from a .env file into os.environ.

    Returns what it loaded. A missing file is not an error - that is the normal
    case in production, where the environment is set properly.
    """
    import pathlib

    loaded: dict[str, str] = {}
    source = pathlib.Path(path)
    if not source.is_file():
        return loaded

    for line in source.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
        loaded[key] = value
    return loaded


@dataclass
class MarketSettings:
    """Price source credentials.

    Both marketplaces have official APIs, and both forbid scraping their listing
    pages in their terms. Empty credentials mean that provider is simply absent
    from the price summary rather than an error - you can run the whole thing on
    a static price file.
    """

    ebay_client_id: str = ""
    ebay_client_secret: str = ""
    ebay_marketplace: str = "EBAY_GB"
    cardmarket_app_token: str = ""
    cardmarket_app_secret: str = ""
    #: EUR to GBP. Cardmarket settles in euros and inventory is costed in
    #: pounds, so a sale there has to be converted before it means anything.
    eur_gbp: float = 0.85

    @property
    def ebay_enabled(self) -> bool:
        return bool(self.ebay_client_id and self.ebay_client_secret)

    @property
    def cardmarket_enabled(self) -> bool:
        return bool(self.cardmarket_app_token and self.cardmarket_app_secret)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MarketSettings:
        source = os.environ if env is None else env
        return cls(
            ebay_client_id=source.get("EBAY_CLIENT_ID", ""),
            ebay_client_secret=source.get("EBAY_CLIENT_SECRET", ""),
            ebay_marketplace=source.get("EBAY_MARKETPLACE", "EBAY_GB"),
            cardmarket_app_token=source.get("CARDMARKET_APP_TOKEN", ""),
            cardmarket_app_secret=source.get("CARDMARKET_APP_SECRET", ""),
            eur_gbp=float(source.get("CARDSHOP_EUR_GBP", "0.85")),
        )

    def build_providers(self) -> list:
        """Whichever price sources have credentials. Possibly none.

        A source that cannot be built is skipped with a message rather than
        raising: one dead marketplace should still leave you a price from the
        other, and no sources at all is a legitimate offline setup.
        """
        providers: list = []

        if self.ebay_enabled:
            from .market.providers import (
                EbayBrowseProvider,
                ProviderError,
                fetch_ebay_token,
            )

            try:
                # Minted here rather than stored: an eBay token lasts about two
                # hours, so a token in configuration is expired by the second
                # scheduled run.
                providers.append(EbayBrowseProvider(
                    access_token=fetch_ebay_token(
                        self.ebay_client_id, self.ebay_client_secret
                    ),
                    marketplace_id=self.ebay_marketplace,
                ))
            except ProviderError as exc:
                print(f"eBay prices unavailable: {exc}")

        if self.cardmarket_enabled:
            from .market.providers import CardmarketProvider

            providers.append(CardmarketProvider(
                app_token=self.cardmarket_app_token,
                fx_eur_to_gbp=self.eur_gbp,
            ))

        return providers


@dataclass
class MailSettings:
    """Where sale notification emails are read from."""

    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_folder: str = "INBOX"
    #: Replay .eml files from a folder instead of connecting to IMAP. Handy for
    #: developing a parser against real emails without touching the live mailbox.
    maildir: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.maildir or (self.imap_host and self.imap_username))

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> MailSettings:
        source = os.environ if env is None else env
        return cls(
            imap_host=source.get("IMAP_HOST", ""),
            imap_port=int(source.get("IMAP_PORT", "993")),
            imap_username=source.get("IMAP_USERNAME", ""),
            imap_password=source.get("IMAP_PASSWORD", ""),
            imap_folder=source.get("IMAP_FOLDER", "INBOX"),
            maildir=source.get("CARDSHOP_MAILDIR", ""),
        )


@dataclass
class AgentSettings:
    """The LLM, if there is one.

    No endpoint is hardcoded. `model_api_base` exists so this points at whatever
    you run - a local server, a hosted provider, anything OpenAI-compatible -
    and the repository never learns which.

    With no key configured the pipeline runs fully deterministic and reports what
    it would have escalated. That is a supported mode, not a degraded one.
    """

    model_id: str = ""
    model_api_base: str = ""
    model_api_key: str = ""
    #: Hard ceiling on escalations per run, so a mailbox full of junk cannot
    #: quietly spend money.
    max_escalations: int = 10

    @property
    def enabled(self) -> bool:
        return bool(self.model_id and self.model_api_key)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AgentSettings:
        source = os.environ if env is None else env
        return cls(
            model_id=source.get("CARDSHOP_MODEL_ID", ""),
            model_api_base=source.get("CARDSHOP_MODEL_API_BASE", ""),
            model_api_key=source.get("CARDSHOP_MODEL_API_KEY", ""),
            max_escalations=int(source.get("CARDSHOP_MAX_ESCALATIONS", "10")),
        )

    def build_model(self):
        """Construct a smolagents model, or None when not configured."""
        if not self.enabled:
            return None
        from smolagents import OpenAIServerModel

        return OpenAIServerModel(
            model_id=self.model_id,
            api_base=self.model_api_base or None,
            api_key=self.model_api_key,
        )


@dataclass
class Settings:
    """Everything, assembled from the environment in one call."""

    core: Config = field(default_factory=Config)
    market: MarketSettings = field(default_factory=MarketSettings)
    mail: MailSettings = field(default_factory=MailSettings)
    agent: AgentSettings = field(default_factory=AgentSettings)
    notify_webhook: str = ""

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> Settings:
        if env_file:
            load_env_file(env_file)
        return cls(
            core=Config.from_env(),
            market=MarketSettings.from_env(),
            mail=MailSettings.from_env(),
            agent=AgentSettings.from_env(),
            notify_webhook=os.environ.get("CARDSHOP_NOTIFY_WEBHOOK", ""),
        )

    def describe(self) -> str:
        """What is wired up, without printing a single secret value."""
        def state(enabled: bool) -> str:
            return "configured" if enabled else "not configured"

        escalation = (
            self.agent.model_id if self.agent.enabled
            else "disabled (deterministic only)"
        )
        return "\n".join([
            f"environment:      {'production' if self.core.production else 'development'}",
            f"mongo:            {self.core.mongo_database}",
            f"ebay prices:      {state(self.market.ebay_enabled)}",
            f"cardmarket:       {state(self.market.cardmarket_enabled)}",
            f"mailbox:          {state(self.mail.enabled)}",
            f"llm escalation:   {escalation}",
            f"notifications:    {'webhook' if self.notify_webhook else 'console'}",
        ])
