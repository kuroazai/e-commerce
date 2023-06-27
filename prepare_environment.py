import json
from databases.db_mongo import MongoDB

Mongo = MongoDB("mongodb:27017", "hyperspace")
file_path = 'data/accelerator_data.json'


def load_accelerator_data(path):
    with open(path, "r") as file:
        return json.load(file)


def upload_to_mongo(data: dict):
    unique_id = "accelerators"
    result = Mongo.find_one("test", {"_id": unique_id})
    if result:
        # Document with the unique ID exists
        print("Document exists")
    else:
        # Document with the unique ID does not exist
        print("Document does not exist")
        Mongo.insert_one("test", data)

file = load_accelerator_data(file_path)
upload_to_mongo(file)

