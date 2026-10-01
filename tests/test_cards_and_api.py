"""Cards, sales, returns, and the YGOPRODeck client."""
from __future__ import annotations

import pytest
import requests

from cardshop import (
    CardApiError,
    Config,
    InMemoryDatabase,
    YgoProDeckClient,
    create_app,
)
from cardshop.models import Return, Sale, YugiohCard

PASSWORD = "correct horse battery staple"


@pytest.fixture
def db():
    return InMemoryDatabase()


@pytest.fixture
def client(db):
    return create_app(Config(), db).test_client()


@pytest.fixture
def token(client):
    client.post("/register", json={
        "username": "kuro", "email": "k@example.com", "password": PASSWORD})
    return client.post("/login", json={
        "username": "kuro", "password": PASSWORD}).get_json()["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# -- models ----------------------------------------------------------------
def test_card_defaults_let_you_build_from_partial_data():
    card = YugiohCard(name="Dark Magician")
    assert card.quantity == 0
    assert card.card_type == []


def test_card_type_lists_are_not_shared():
    """A mutable default on a dataclass would make every card share one list."""
    a, b = YugiohCard(name="A"), YugiohCard(name="B")
    a.card_type.append("Spellcaster")
    assert b.card_type == []


def test_sale_and_return_round_trip():
    assert Sale(card_name="x", quantity=1, price=2.5).to_dict()["price"] == 2.5
    assert Return(sale_id="1", reason="damaged").to_dict()["quantity"] == 1


# -- cards endpoint --------------------------------------------------------
def test_adding_a_card_then_listing_it(client, token):
    created = client.post("/cards",
                          json={"name": "Dark Magician", "archetype": "Magician"},
                          headers=auth_header(token))
    assert created.status_code == 201
    cards = client.get("/cards").get_json()
    assert [c["name"] for c in cards] == ["Dark Magician"]


def test_cards_can_be_filtered(client, token):
    for name, archetype in [("A", "Blue-Eyes"), ("B", "Magician")]:
        client.post("/cards", json={"name": name, "archetype": archetype},
                    headers=auth_header(token))
    filtered = client.get("/cards?archetype=Magician").get_json()
    assert [c["name"] for c in filtered] == ["B"]


def test_card_without_a_name_is_rejected(client, token):
    assert client.post("/cards", json={}, headers=auth_header(token)).status_code == 400


def test_unknown_card_fields_are_dropped(client, token):
    client.post("/cards", json={"name": "X", "injected": "value"},
                headers=auth_header(token))
    assert "injected" not in client.get("/cards").get_json()[0]


def test_listing_cards_hides_the_mongo_id(client, token):
    client.post("/cards", json={"name": "X"}, headers=auth_header(token))
    assert "_id" not in client.get("/cards").get_json()[0]


# -- sales and returns -----------------------------------------------------
def test_sale_records_the_authenticated_user(client, token, db):
    client.post("/sales", json={"card_name": "X", "quantity": 2, "price": 10.0},
                headers=auth_header(token))
    assert db.find("sales", {})[0]["username"] == "kuro"


def test_sale_requires_fields(client, token):
    assert client.post("/sales", json={"card_name": "X"},
                       headers=auth_header(token)).status_code == 400


def test_return_requires_fields(client, token):
    assert client.post("/returns", json={"sale_id": "1"},
                       headers=auth_header(token)).status_code == 400


def test_sales_and_returns_need_auth(client):
    assert client.post("/sales", json={"card_name": "X", "quantity": 1}).status_code == 401
    assert client.post("/returns", json={"sale_id": "1", "reason": "x"}).status_code == 401


# -- external API client ---------------------------------------------------
class FakeResponse:
    def __init__(self, payload=None, status_code=200, text_body=None):
        self._payload = payload
        self.status_code = status_code
        self._text_body = text_body

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._text_body is not None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, response=None, raises=None):
        self.response = response
        self.raises = raises
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if self.raises:
            raise self.raises
        return self.response


def test_card_lookup_returns_the_data_list():
    session = FakeSession(FakeResponse({"data": [{"name": "Dark Magician"}]}))
    client = YgoProDeckClient(session=session)
    assert client.card_by_name("Dark Magician")[0]["name"] == "Dark Magician"


def test_every_request_carries_a_timeout():
    """The original called requests.get with no timeout, so a hung server hung
    the request thread indefinitely."""
    session = FakeSession(FakeResponse({"data": []}))
    YgoProDeckClient(session=session, timeout=5.0).card_by_name("x")
    assert session.calls[0]["timeout"] == 5.0


def test_a_404_becomes_an_error_not_a_dict():
    """The original returned response.json() without checking status, so an
    error page became a dict the caller then indexed into."""
    client = YgoProDeckClient(session=FakeSession(FakeResponse({}, status_code=500)))
    with pytest.raises(CardApiError, match="500"):
        client.card_by_name("x")


def test_no_match_is_reported_clearly():
    client = YgoProDeckClient(session=FakeSession(FakeResponse({}, status_code=400)))
    with pytest.raises(CardApiError, match="no cards matched"):
        client.card_by_name("nonexistent")


def test_network_failure_is_wrapped():
    session = FakeSession(raises=requests.ConnectionError("down"))
    with pytest.raises(CardApiError, match="unreachable"):
        YgoProDeckClient(session=session).card_by_name("x")


def test_non_json_body_is_reported():
    client = YgoProDeckClient(session=FakeSession(FakeResponse(text_body="<html>")))
    with pytest.raises(CardApiError, match="non-JSON"):
        client.card_by_name("x")


def test_missing_data_key_is_reported():
    client = YgoProDeckClient(session=FakeSession(FakeResponse({"meta": {}})))
    with pytest.raises(CardApiError, match="no data"):
        client.card_by_name("x")


# -- in-memory database ----------------------------------------------------
def test_in_memory_db_round_trip(db):
    db.insert_one("things", {"name": "a", "kind": "x"})
    db.insert_one("things", {"name": "b", "kind": "y"})
    assert db.find_one("things", {"name": "a"})["kind"] == "x"
    assert len(db.find("things", {})) == 2
    assert db.find_one("things", {"name": "missing"}) is None


def test_in_memory_db_update(db):
    db.insert_one("things", {"name": "a", "kind": "x"})
    assert db.update_one("things", {"name": "a"}, {"$set": {"kind": "z"}}) is True
    assert db.find_one("things", {"name": "a"})["kind"] == "z"
    assert db.update_one("things", {"name": "ghost"}, {"$set": {"kind": "z"}}) is False


def test_in_memory_db_returns_copies(db):
    """Callers mutating a result must not corrupt the store."""
    db.insert_one("things", {"name": "a"})
    found = db.find_one("things", {"name": "a"})
    found["name"] = "mutated"
    assert db.find_one("things", {"name": "a"}) is not None
