import json
from databases.db_mongo import MongoDB
from data_models.models import User
from flask import jsonify
Mongo = MongoDB("mongodb://localhost:27017", "yugioh")
file_path = 'data/admin_user.json'


def load_admin_data(path):
    with open(path, "r") as file:
        return json.load(file)


def upload_to_mongo(data: dict):
    print(data)
    unique_id = "users"
    result = Mongo.find_one("test", {"_id": unique_id})
    if result:
        # Document with the unique ID exists
        print("Document exists")
    else:
        # Document with the unique ID does not exist
        print("Document does not exist")
        Mongo.insert_one("test", data)

file = load_admin_data(file_path)
upload_to_mongo(file)

