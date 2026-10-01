"""Password hashing. One algorithm, used on both sides.

The original hashed with `passlib.sha256_crypt` on registration and verified with
`bcrypt.checkpw` on login. Two different algorithms, so a password that was
stored could never be verified - and that was only the second reason login could
not succeed.

bcrypt here because it is deliberately slow, salts automatically, and is what the
project already depended on.
"""
from __future__ import annotations

import bcrypt

#: Cost factor. 12 is ~250ms on current hardware - slow enough to make offline
#: cracking expensive, fast enough that a login does not feel broken.
DEFAULT_ROUNDS = 12


def hash_password(password: str, *, rounds: int = DEFAULT_ROUNDS) -> str:
    """Salt and hash a password. The salt is embedded in the result."""
    if not password:
        raise ValueError("password cannot be empty")
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Check a password against a stored hash.

    Returns False rather than raising on a malformed hash: a corrupt record in
    the database should fail the login, not crash the endpoint and leak the
    difference between "no such user" and "stored hash is broken".
    """
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
