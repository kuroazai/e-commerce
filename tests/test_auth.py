"""Authentication.

The original API could not authenticate anyone, for four independent reasons.
Each has a test here named after it. `test_register_then_login_succeeds` is the
one that would have caught all four at once, and it did not exist.
"""
from __future__ import annotations

import pytest

from cardshop import AuthError, AuthService, Config, InMemoryDatabase, create_app
from cardshop.config import ConfigError
from cardshop.models import User
from cardshop.security import hash_password, verify_password

PASSWORD = "correct horse battery staple"


@pytest.fixture
def db():
    return InMemoryDatabase()


@pytest.fixture
def auth(db):
    return AuthService(db)


@pytest.fixture
def client(db):
    return create_app(Config(), db).test_client()


# -- the four original defects --------------------------------------------
def test_register_then_login_succeeds(auth):
    """Reason 0: nobody ever ran this. It fails on the original in four ways."""
    auth.register("kuro", "k@example.com", PASSWORD)
    user = auth.authenticate("kuro", PASSWORD)
    assert user.username == "kuro"


def test_user_can_be_constructed_from_what_register_passes(auth):
    """Reason 1: create_user() passed `email` and `hashed_password` to a User
    with neither field, and omitted the required `username` - TypeError before
    the database was touched."""
    user = auth.register("kuro", "k@example.com", PASSWORD)
    assert isinstance(user, User)
    assert user.username == "kuro"
    assert user.email == "k@example.com"
    assert user.password_hash


def test_verification_compares_password_to_hash_not_to_a_boolean():
    """Reason 2: the original compared the stored hash to the boolean returned
    by check_password. That is False for every input that exists."""
    hashed = hash_password(PASSWORD)
    assert verify_password(PASSWORD, hashed) is True
    assert (hashed == verify_password(PASSWORD, hashed)) is False


def test_lookup_uses_the_username_field(auth, db):
    """Reason 3: the original queried {"users": username}; the field is
    `username`, so find_one always returned None."""
    auth.register("kuro", "k@example.com", PASSWORD)
    assert db.find_one("users", {"username": "kuro"}) is not None
    assert db.find_one("users", {"users": "kuro"}) is None


def test_one_hashing_algorithm_on_both_sides(auth, db):
    """Reason 4: registration hashed with sha256_crypt, login verified with
    bcrypt. A stored password could never be verified."""
    auth.register("kuro", "k@example.com", PASSWORD)
    stored = db.find_one("users", {"username": "kuro"})
    assert stored["password_hash"].startswith("$2")  # bcrypt
    assert verify_password(PASSWORD, stored["password_hash"]) is True


# -- hashing ---------------------------------------------------------------
def test_hash_is_salted():
    """Same password, different hashes - otherwise a rainbow table does the job."""
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_wrong_password_is_rejected():
    assert verify_password("wrong", hash_password(PASSWORD)) is False


def test_empty_password_is_refused():
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_returns_false_on_a_corrupt_hash():
    """A broken database record should fail the login, not crash the endpoint
    and reveal that the record is broken."""
    assert verify_password(PASSWORD, "not-a-bcrypt-hash") is False
    assert verify_password(PASSWORD, "") is False


def test_plaintext_is_never_stored(auth, db):
    auth.register("kuro", "k@example.com", PASSWORD)
    stored = db.find_one("users", {"username": "kuro"})
    assert PASSWORD not in str(stored)
    assert "password" not in {k for k in stored if k != "password_hash"}


# -- registration rules ----------------------------------------------------
def test_duplicate_username_is_rejected(auth):
    auth.register("kuro", "a@example.com", PASSWORD)
    with pytest.raises(AuthError) as exc:
        auth.register("kuro", "b@example.com", PASSWORD)
    assert exc.value.status == 409


def test_duplicate_email_is_rejected(auth):
    auth.register("one", "same@example.com", PASSWORD)
    with pytest.raises(AuthError) as exc:
        auth.register("two", "same@example.com", PASSWORD)
    assert exc.value.status == 409


def test_short_passwords_are_rejected(auth):
    with pytest.raises(AuthError, match="at least 8"):
        auth.register("kuro", "k@example.com", "short")


def test_missing_fields_are_rejected(auth):
    with pytest.raises(AuthError):
        auth.register("", "k@example.com", PASSWORD)
    with pytest.raises(AuthError):
        auth.register("kuro", "", PASSWORD)


def test_admin_cannot_be_set_from_the_request(auth):
    """The original passed the request body straight into the model."""
    user = auth.register("kuro", "k@example.com", PASSWORD, admin=True)
    assert user.admin is False


def test_unknown_profile_fields_are_ignored(auth):
    user = auth.register("kuro", "k@example.com", PASSWORD,
                         first_name="Fidelis", nonsense="dropped")
    assert user.first_name == "Fidelis"
    assert not hasattr(user, "nonsense")


# -- login -----------------------------------------------------------------
def test_unknown_user_and_wrong_password_give_the_same_message(auth):
    """Distinct messages let an attacker enumerate valid usernames."""
    auth.register("kuro", "k@example.com", PASSWORD)
    with pytest.raises(AuthError) as wrong:
        auth.authenticate("kuro", "nope")
    with pytest.raises(AuthError) as missing:
        auth.authenticate("ghost", "nope")
    assert wrong.value.message == missing.value.message


def test_public_view_excludes_the_hash(auth):
    user = auth.register("kuro", "k@example.com", PASSWORD)
    assert "password_hash" not in user.public()
    assert user.public()["username"] == "kuro"


# -- config ----------------------------------------------------------------
def test_production_refuses_a_placeholder_secret():
    """The original shipped JWT_SECRET_KEY = "your-secret-key" in a public repo.
    Anyone reading it could forge a token for any user."""
    with pytest.raises(ConfigError, match="must be set to a real secret"):
        Config.from_env({"CARDSHOP_ENV": "production", "JWT_SECRET_KEY": "your-secret-key"})


def test_production_refuses_a_missing_secret():
    with pytest.raises(ConfigError):
        Config.from_env({"CARDSHOP_ENV": "production"})


def test_production_refuses_a_short_secret():
    with pytest.raises(ConfigError, match="at least 32"):
        Config.from_env({"CARDSHOP_ENV": "production", "JWT_SECRET_KEY": "x" * 20})


def test_production_accepts_a_real_secret():
    cfg = Config.from_env({"CARDSHOP_ENV": "production", "JWT_SECRET_KEY": "x" * 48})
    assert cfg.production is True


def test_development_generates_an_ephemeral_secret():
    a = Config.from_env({})
    b = Config.from_env({})
    assert a.jwt_secret_key != b.jwt_secret_key
    assert len(a.jwt_secret_key) >= 32


# -- HTTP flow -------------------------------------------------------------
def test_http_register_then_login(client):
    registered = client.post("/register", json={
        "username": "kuro", "email": "k@example.com", "password": PASSWORD,
    })
    assert registered.status_code == 201

    logged_in = client.post("/login", json={"username": "kuro", "password": PASSWORD})
    assert logged_in.status_code == 200
    assert "access_token" in logged_in.get_json()


def test_http_login_rejects_a_bad_password(client):
    client.post("/register", json={
        "username": "kuro", "email": "k@example.com", "password": PASSWORD})
    response = client.post("/login", json={"username": "kuro", "password": "wrong"})
    assert response.status_code == 401


def test_protected_route_needs_a_token(client):
    assert client.get("/me").status_code == 401


def test_protected_route_accepts_a_token(client):
    client.post("/register", json={
        "username": "kuro", "email": "k@example.com", "password": PASSWORD})
    token = client.post("/login", json={
        "username": "kuro", "password": PASSWORD}).get_json()["access_token"]

    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.get_json()["username"] == "kuro"
    assert "password_hash" not in response.get_json()


def test_http_admin_escalation_is_blocked(client):
    response = client.post("/register", json={
        "username": "kuro", "email": "k@example.com",
        "password": PASSWORD, "admin": True,
    })
    assert response.get_json()["user"]["admin"] is False


def test_adding_a_card_requires_auth(client):
    assert client.post("/cards", json={"name": "Dark Magician"}).status_code == 401


def test_health_is_open(client):
    assert client.get("/health").get_json() == {"status": "ok"}
