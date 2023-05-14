from flask import Flask, request, jsonify
from flask_restful import Api, Resource
from flask_jwt_extended import JWTManager, jwt_required, create_access_token
from data_models.models import YugiohCard, User, Sales, Returns
from databases.db_mongo import MongoDB
from bson.objectid import ObjectId


app = Flask(__name__)
app.config["MONGO_URI"] = "mongodb://localhost:27017/yugioh"
app.config["JWT_SECRET_KEY"] = "your-secret-key"
jwt = JWTManager(app)
api = Api(app)
Mongo = MongoDB(app.config["MONGO_URI"], "yugioh")

class GetAllCards(Resource):
    def get(self) -> list:
        # call db and get all cards
        cards = Mongo.db.cards.find()
        # return list of cards
        return jsonify([card for card in cards])

class GetFilteredCards(Resource):
    def get(self):
        # filter params
        sort_by = request.args.get('sort')
        rarity = request.args.get('rarity')
        boxset = request.args.get('boxset')
        card_type = request.args.get('type')

        # query holder
        query = {}
        # conditional query
        if rarity:
            query['rarity'] = rarity
        if boxset:
            query['boxset'] = boxset
        if card_type:
            query['type'] = card_type
        # sort otpions
        sort = None
        if sort_by:
            sort = [(sort_by, 1)]
        # call db and get all cards that meet requirements
        cards = Mongo.db.cards.find(query).sort(sort)
        return jsonify([card for card in cards])

class GetCard(Resource):
    def get(self, card_id: str)-> dict:
        # call db and get card by id
        card = Mongo.db.cards.find_one({"_id": ObjectId(card_id)})
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
        # map data to YugiohCard model
        card = YugiohCard(**data)
        # insert card into db and get id
        card_id = Mongo.db.cards.insert_one(card.__dict__).inserted_id
        # return created id
        return {"message": "Card added", "card_id": str(card_id)}

class UpdateCardQuantity(Resource):
    @jwt_required()
    def put(self, card_id:str)-> dict:
        data = request.get_json()
        quantity = data.get("quantity")

        if quantity is None:
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

### Sales and returns
class GetSales(Resource):
    @jwt_required()
    def get(self):
        sales = Mongo.db.sales.find()
        return jsonify([sale for sale in sales])

class GetReturns(Resource):
    @jwt_required()
    def get(self):
        returns = Mongo.db.returns.find()
        return jsonify([return_data for return_data in returns])

class CreateSale(Resource):
    @jwt_required()
    def post(self):
        data = request.get_json()

        sale = Sales(**data)
        sale_id = Mongo.db.sales.insert_one(sale.__dict__).inserted_id

        # Update the card quantity
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

        user = Mongo.db.users.find_one({"username": username})

        if user and user["password"] == password:  # In production, use a secure password hashing and validation
            access_token = create_access_token(identity=username)
            return {"access_token": access_token}

        return {"message": "Invalid username or password"}, 401


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


if __name__ == "__main__":
    app.run(debug=True)
