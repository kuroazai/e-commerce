from flask import Flask, request, jsonify
from passlib.hash import sha256_crypt
from flask_restful import Api, Resource
from flask_jwt_extended import JWTManager, jwt_required, create_access_token
from data_models.models import YugiohCard, User, Sales, Returns
from databases.db_mongo import MongoDB
from bson.objectid import ObjectId
from external_api.ygoprodeck_api import get_card_by_name, get_card_by_archetype
from scripts import encryption_kit

app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb://localhost:27017/yugioh"
app.config["JWT_SECRET_KEY"] = "your-secret-key"
jwt = JWTManager(app)
api = Api(app)
Mongo = MongoDB(app.config["MONGO_URI"], "yugioh")


class GetAllCards(Resource):
    def get(self) -> list:
        cards = Mongo.db.cards.find()

        if not cards:
            return {"message": "No cards found"}, 404

        return jsonify([card for card in cards])

class GetFilteredCards(Resource):
    def get(self):
        sort_by = request.args.get('sort')
        rarity = request.args.get('rarity')
        boxset = request.args.get('boxset')
        card_type = request.args.get('type')

        query = {}
        if rarity:
            query['rarity'] = rarity
        if boxset:
            query['boxset'] = boxset
        if card_type:
            query['type'] = card_type

        sort = None
        if sort_by:
            sort = [(sort_by, 1)]

        cards = Mongo.db.cards.find(query).sort(sort)
        if not cards:
            return {"message": "No cards found"}, 404
        return jsonify([card for card in cards])

class GetCard(Resource):
    def get(self, card_id: str)-> dict:
        card = Mongo.find_one("cards", {"_id": ObjectId(card_id)})
        if card:
            return jsonify(card)
        return {"message": "Card not found"}, 404

class GetFilteredCard(Resource):
    def get(self) -> dict:
        rarity = request.args.get('rarity')
        boxset = request.args.get('boxset')
        card_type = request.args.get('type')

        query = {}
        if rarity:
            query['rarity'] = rarity
        if boxset:
            query['boxset'] = boxset
        if card_type:
            query['type'] = card_type

        card = Mongo.db.cards.find_one(query)
        if card:
            return jsonify(card)
        return {"message": "Card not found"}, 404

class AddCard(Resource):
    @jwt_required()
    def post(self)-> dict:
        data = request.get_json()
        if data.get("name") is None:
            return {"message": "Missing name data"}, 400
        if data.get("quantity") is None:
            return {"message": "Missing quantity data"}, 400

        card = YugiohCard(get_card_by_name(data.get("name")))
        print(card.__dict__)
        card['quantity'] = data['quantity']

        card_id = Mongo.insert_one("cards", card.__dict__)
        return {"message": "Card added", "card_id": str(card_id)}

class UpdateCardQuantity(Resource):
    @jwt_required()
    def put(self, card_id:str)-> dict:
        data = request.get_json()
        quantity = data.get("quantity")

        if not quantity:
            return {"message": "Missing quantity data"}, 400

        Mongo.db.cards.update_one({"_id": ObjectId(card_id)}, {"$set": {"quantity": quantity}})
        return {"message": "Card quantity updated"}

class AddCardQuantity(Resource):
    @jwt_required()
    def put(self, card_id):
        data = request.get_json()
        additional_quantity = data.get("additional_quantity")

        if additional_quantity is None:
            return {"message": "Missing additional quantity data"}, 400

        Mongo.db.cards.update_one({"_id": ObjectId(card_id)}, {"$inc": {"quantity": additional_quantity}})
        return {"message": "Card quantity updated"}

class GetSales(Resource):
    @jwt_required()
    def get(self):
        sales = Mongo.db.sales.find()
        if not sales:
            return {"message": "No sales found"}, 404
        return jsonify([sale for sale in sales])

class GetReturns(Resource):
    @jwt_required()
    def get(self):
        returns = Mongo.db.returns.find()
        if not returns:
            return {"message": "No returns found"}, 404
        return jsonify([return_data for return_data in returns])

class CreateSale(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        sale = Sales(**data)
        sale_id = Mongo.db.sales.insert_one(sale.__dict__).inserted_id

        Mongo.db.cards.update_one({"_id": ObjectId(sale.card_id)}, {"$inc": {"quantity": -sale.quantity}})

        return {"message": "Sale created", "sale_id": str(sale_id)}

class CreateReturn(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        return_data = Returns(**data)
        return_id = Mongo.db.returns.insert_one(return_data.__dict__).inserted_id

        return {"message": "Return created", "return_id": str(return_id)}


class Login(Resource):
    def post(self):
        data = request.get_json()
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return {"message": "Missing username or password"}, 400

        user = Mongo.db.users.find_one({"users": username})

        if user and user["password"] == encryption_kit.check_password(password, user["password"]):
            access_token = create_access_token(identity=username)
            return {"access_token": access_token}

        return {"message": "Invalid username or password"}, 401


class Register(Resource):
    def post(self):
        data = request.get_json()
        first_name = data.get('first_name')
        last_name = data.get('last_name')
        address = data.get('address')
        postcode = data.get('postcode')
        region = data.get('region')
        country = data.get('country')
        age = data.get('age')
        gender = data.get('gender')
        email = data.get('email')
        password = data.get('password')

        if not all([first_name, last_name, address, postcode, region, country, age, gender, email, password]):
            return {"message": "Invalid input data"}, 400
        hashed_password = sha256_crypt.hash(password)
        user_id = create_user(first_name, last_name, address, postcode, region, country, age, gender, email, hashed_password)
        return {"message": "User created", "user_id": user_id}, 201


def create_user(first_name: str, last_name: str, address: str, postcode: str, region: str, country: str, age: int, gender: str, email: str, hashed_password: str) -> str:
    user = User(first_name=first_name, last_name=last_name, address=address, postcode=postcode, region=region, country=country, age=age, gender=gender, email=email, hashed_password=hashed_password)
    user_id = Mongo.db.users.insert_one(user.__dict__).inserted_id
    return str(user_id)

api.add_resource(GetAllCards, "/cards")
api.add_resource(GetFilteredCards, "/cards/filter")
api.add_resource(GetCard, "/card/<string:card_id>")
api.add_resource(GetFilteredCard, "/card/filter")
api.add_resource(AddCard, "/card")
api.add_resource(UpdateCardQuantity, "/card/<string:card_id>/quantity")
api.add_resource(AddCardQuantity, "/card/<string:card_id>/add-quantity")
api.add_resource(GetReturns, "/returns")
api.add_resource(GetSales, "/sales")
api.add_resource(Login, "/login")
api.add_resource(Register, "/register")
api.add_resource(CreateSale, "/sale")
api.add_resource(CreateReturn, "/return")


if __name__ == "__main__":
    app.run(debug=True)
