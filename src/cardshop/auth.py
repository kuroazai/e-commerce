"""Registration and login.

The original had four independent reasons login could never succeed:

1. `create_user()` passed `email` and `hashed_password` to a `User` dataclass
   that had neither field and required a `username` it never passed, so
   registration raised TypeError before touching the database.
2. Login compared a stored hash to a boolean:
   `user["password"] == check_password(...)`. Always False.
3. Login queried `{"users": username}` where the field is `username`.
4. Registration hashed with sha256_crypt; login verified with bcrypt.

All four are fixed here, and `test_register_then_login_succeeds` is the test that
would have caught any of them.
"""
from __future__ import annotations

from dataclasses import dataclass

from .db import Database
from .models import User
from .security import hash_password, verify_password

USERS = "users"

#: Deliberately identical for "no such user" and "wrong password". Distinct
#: messages let an attacker enumerate valid usernames.
INVALID_CREDENTIALS = "Invalid username or password"


class AuthError(Exception):
    """Authentication or registration failed."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class AuthService:
    db: Database

    def register(
        self,
        username: str,
        email: str,
        password: str,
        **profile: object,
    ) -> User:
        """Create a user. Raises AuthError if the input is bad or taken."""
        if not username or not email or not password:
            raise AuthError("username, email and password are required", status=400)
        if len(password) < 8:
            raise AuthError("password must be at least 8 characters", status=400)
        if self.db.find_one(USERS, {"username": username}):
            raise AuthError("username already taken", status=409)
        if self.db.find_one(USERS, {"email": email}):
            raise AuthError("email already registered", status=409)

        allowed = {"first_name", "last_name", "address", "postcode",
                   "region", "country", "age"}
        # admin is never settable from a request body. The original would have
        # accepted whatever the client sent.
        extras = {k: v for k, v in profile.items() if k in allowed}

        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            **extras,  # type: ignore[arg-type]
        )
        self.db.insert_one(USERS, user.to_dict())
        return user

    def authenticate(self, username: str, password: str) -> User:
        """Return the user on success, raise AuthError otherwise."""
        if not username or not password:
            raise AuthError("username and password are required", status=400)

        record = self.db.find_one(USERS, {"username": username})
        if record is None:
            # Hash anyway so a missing user and a wrong password take the same
            # time; otherwise response timing reveals which usernames exist.
            verify_password(password, hash_password("dummy-timing-equaliser"))
            raise AuthError(INVALID_CREDENTIALS)

        if not verify_password(password, record.get("password_hash", "")):
            raise AuthError(INVALID_CREDENTIALS)

        record.pop("_id", None)
        return User(**record)
