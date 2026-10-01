"""Flask REST resources."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from .auth import AuthError, AuthService
from .models import Return, Sale, YugiohCard

bp = Blueprint("api", __name__)

CARDS = "cards"
SALES = "sales"
RETURNS = "returns"


def _db():
    return current_app.config["CARDSHOP_DB"]


def _auth() -> AuthService:
    return AuthService(_db())


@bp.errorhandler(AuthError)
def _handle_auth_error(error: AuthError):
    return jsonify({"message": error.message}), error.status


# -- auth ------------------------------------------------------------------
@bp.post("/register")
def register():
    from flask_jwt_extended import create_access_token

    data = request.get_json(silent=True) or {}
    try:
        user = _auth().register(
            username=data.get("username", ""),
            email=data.get("email", ""),
            password=data.get("password", ""),
            **{k: v for k, v in data.items()
               if k not in {"username", "email", "password", "admin"}},
        )
    except AuthError as exc:
        return jsonify({"message": exc.message}), exc.status

    token = create_access_token(identity=user.username)
    return jsonify({"message": "User created", "user": user.public(),
                    "access_token": token}), 201


@bp.post("/login")
def login():
    from flask_jwt_extended import create_access_token

    data = request.get_json(silent=True) or {}
    try:
        user = _auth().authenticate(data.get("username", ""), data.get("password", ""))
    except AuthError as exc:
        return jsonify({"message": exc.message}), exc.status

    return jsonify({"access_token": create_access_token(identity=user.username)})


@bp.get("/me")
@jwt_required()
def me():
    record = _db().find_one("users", {"username": get_jwt_identity()})
    if record is None:
        return jsonify({"message": "User not found"}), 404
    record.pop("_id", None)
    record.pop("password_hash", None)
    return jsonify(record)


# -- cards -----------------------------------------------------------------
@bp.get("/cards")
def list_cards():
    query = {}
    for key in ("archetype", "rarity", "boxset"):
        value = request.args.get(key)
        if value:
            query[key] = value
    cards = _db().find(CARDS, query)
    for card in cards:
        card.pop("_id", None)
    return jsonify(cards)


@bp.post("/cards")
@jwt_required()
def add_card():
    data = request.get_json(silent=True) or {}
    if not data.get("name"):
        return jsonify({"message": "name is required"}), 400
    allowed = {f for f in YugiohCard.__dataclass_fields__}
    card = YugiohCard(**{k: v for k, v in data.items() if k in allowed})
    card_id = _db().insert_one(CARDS, card.to_dict())
    return jsonify({"message": "Card added", "card_id": card_id}), 201


# -- sales and returns -----------------------------------------------------
@bp.post("/sales")
@jwt_required()
def create_sale():
    data = request.get_json(silent=True) or {}
    if not data.get("card_name") or not data.get("quantity"):
        return jsonify({"message": "card_name and quantity are required"}), 400
    sale = Sale(
        card_name=data["card_name"],
        quantity=int(data["quantity"]),
        price=float(data.get("price", 0.0)),
        username=get_jwt_identity(),
    )
    sale_id = _db().insert_one(SALES, sale.to_dict())
    return jsonify({"message": "Sale created", "sale_id": sale_id}), 201


@bp.post("/returns")
@jwt_required()
def create_return():
    data = request.get_json(silent=True) or {}
    if not data.get("sale_id") or not data.get("reason"):
        return jsonify({"message": "sale_id and reason are required"}), 400
    item = Return(sale_id=data["sale_id"], reason=data["reason"],
                  quantity=int(data.get("quantity", 1)))
    return_id = _db().insert_one(RETURNS, item.to_dict())
    return jsonify({"message": "Return created", "return_id": return_id}), 201


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})
