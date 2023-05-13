from dataclasses import dataclass
from typing import List

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
    email: str
    hashed_password: str

