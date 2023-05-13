from pymongo import MongoClient
from pymongo.collection import Collection

class MongoDB:
    def __init__(self, uri: str, database: str):
        # initialize the client
        self.client = MongoClient(uri)
        # set the database to the one specified
        self.db = self.client[database]

    def get_collection(self, collection_name: str) -> Collection:
        return self.db[collection_name]

    def find_one(self, collection_name: str, query: dict) -> dict:
        return self.get_collection(collection_name).find_one(query)

    def find(self, collection_name: str, query: dict, sort: list = None) -> list:
        # cursor to find all matching items
        cursor = self.get_collection(collection_name).find(query)
        if sort:
            cursor.sort(sort)
        return list(cursor)

    def insert_one(self, collection_name: str, data: dict) -> bool:
        # insert the data and return the id
        return self.get_collection(collection_name).insert_one(data).inserted_id

    def update_one(self, collection_name: str, filter: dict, update: dict) -> bool:
        # update the data and return the number of modified items
        return self.get_collection(collection_name).update_one(filter, update).modified_count > 0

    def close(self):
        # teardown the client
        self.client.close()

