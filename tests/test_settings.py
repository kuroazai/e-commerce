"""Configuration, and the promise that it holds no secrets."""
from __future__ import annotations

from pathlib import Path

from cardshop.config import (
    AgentSettings,
    MailSettings,
    MarketSettings,
    Settings,
    load_env_file,
)


def test_everything_is_off_by_default() -> None:
    """A fresh checkout runs, deterministic-only, with nothing configured."""
    settings = Settings()
    assert not settings.market.ebay_enabled
    assert not settings.market.cardmarket_enabled
    assert not settings.mail.enabled
    assert not settings.agent.enabled


def test_providers_need_both_halves_of_a_credential() -> None:
    assert not MarketSettings(ebay_client_id="id").ebay_enabled
    assert MarketSettings(ebay_client_id="id", ebay_client_secret="s").ebay_enabled


def test_the_agent_needs_a_model_and_a_key() -> None:
    assert not AgentSettings(model_id="some-model").enabled
    assert AgentSettings(model_id="some-model", model_api_key="k").enabled


def test_a_maildir_alone_is_enough_to_read_mail() -> None:
    """Replaying .eml files needs no server, which is how you develop a parser
    against real emails without touching the live mailbox."""
    assert MailSettings(maildir="./saved-mail").enabled


def test_reads_an_env_file(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n"
        "\n"
        "CARDSHOP_MODEL_ID=some-model\n"
        'CARDSHOP_MODEL_API_KEY="quoted-value"\n'
        "MALFORMED_LINE\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("CARDSHOP_MODEL_ID", raising=False)
    monkeypatch.delenv("CARDSHOP_MODEL_API_KEY", raising=False)

    loaded = load_env_file(str(env))
    assert loaded["CARDSHOP_MODEL_ID"] == "some-model"
    assert loaded["CARDSHOP_MODEL_API_KEY"] == "quoted-value"  # quotes stripped
    assert "MALFORMED_LINE" not in loaded


def test_an_env_file_does_not_override_the_real_environment(
    tmp_path: Path, monkeypatch
) -> None:
    """A deployment sets its config properly. A stray .env must not win."""
    env = tmp_path / ".env"
    env.write_text("CARDSHOP_MODEL_ID=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CARDSHOP_MODEL_ID", "from-environment")

    load_env_file(str(env))
    assert AgentSettings.from_env().model_id == "from-environment"


def test_a_missing_env_file_is_fine(tmp_path: Path) -> None:
    """The normal case in production, where the environment is already set."""
    assert load_env_file(str(tmp_path / "nope.env")) == {}


def test_describe_never_prints_a_secret() -> None:
    """This output goes in logs and in terminal screenshots."""
    settings = Settings(
        market=MarketSettings(ebay_client_id="ID", ebay_client_secret="SECRET-VALUE"),
        mail=MailSettings(imap_host="mail.example.com", imap_username="u",
                          imap_password="PASSWORD-VALUE"),
        agent=AgentSettings(model_id="some-model", model_api_key="KEY-VALUE",
                            model_api_base="https://endpoint.example.com"),
    )
    described = settings.describe()

    for secret in ("SECRET-VALUE", "PASSWORD-VALUE", "KEY-VALUE",
                   "https://endpoint.example.com"):
        assert secret not in described
    assert "configured" in described


def test_the_shipped_example_env_contains_no_values() -> None:
    """The repository must never learn which endpoint or key anyone uses."""
    example = Path(__file__).resolve().parent.parent / ".env.example"
    if not example.is_file():
        return

    secretish = {
        "JWT_SECRET_KEY", "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET",
        "CARDMARKET_APP_TOKEN", "CARDMARKET_APP_SECRET",
        "IMAP_HOST", "IMAP_USERNAME", "IMAP_PASSWORD",
        "CARDSHOP_MODEL_API_BASE", "CARDSHOP_MODEL_API_KEY",
        "CARDSHOP_NOTIFY_WEBHOOK",
    }
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        if key.strip() in secretish:
            assert value.strip() == "", f"{key.strip()} has a value in .env.example"
