"""Domain models.

`User` carries `password_hash`, never a plaintext `password`. The original named
the field `password` and the registration path tried to pass `hashed_password`,
which is not a field at all - so constructing a user raised TypeError and
registration had never worked.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class YugiohCard:
    name: str
    effect: str = ""
    rarity: str = ""
    boxset: str = ""
    archetype: str = ""
    card_type: list[str] = field(default_factory=list)
    image_url: str = ""
    attack: int = 0
    defense: int = 0
    quantity: int = 0
    price: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class User:
    username: str
    email: str
    password_hash: str
    first_name: str = ""
    last_name: str = ""
    address: str = ""
    postcode: str = ""
    region: str = ""
    country: str = ""
    age: int = 0
    admin: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    def public(self) -> dict:
        """Everything except the hash. Use this for anything leaving the API."""
        data = asdict(self)
        data.pop("password_hash", None)
        return data


@dataclass
class Sale:
    card_name: str
    quantity: int
    price: float
    username: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Return:
    sale_id: str
    reason: str
    quantity: int = 1

    def to_dict(self) -> dict:
        return asdict(self)
