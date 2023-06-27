from dataclasses import dataclass, asdict
from typing import List
import json

@dataclass
class YugiohCard:
    name: str
    effect: str
    rarity: str
    boxset: str
    archetype: str
    card_type: List[str]
    image_url: str
    attack: int
    defense: int
    quantity: int
    price: float


@dataclass
class User:
    first_name: str
    last_name: str
    address: str
    postcode: str
    region: str
    country: str
    age: int
    gender: str
    username: str
    password: str
    admin: bool = False

    def to_json(self):
        user_dict = asdict(self)
        return json.dumps(user_dict)
@dataclass
class Sales:
    card_id: str
    quantity: int
    price: float
    date: str
    user_id: str


@dataclass
class Returns:
    card_id: str
    quantity: int
    price: float
    date: str
    user_id: str
    reason: str
    status: str
    refund: float
    refund_date: str

