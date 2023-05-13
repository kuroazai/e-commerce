import unittest
from db_mongo import MongoDB
from bson.objectid import ObjectId

class TestMongoDB(unittest.TestCase):
    def setUp(self):
        self.db = MongoDB("mongodb://localhost:27017", "testdb")

    def test_insert_one(self):
        data = {"key": "value"}
        inserted_id = self.db.insert_one("test_collection", data)
        self.assertIsInstance(inserted_id, ObjectId)

    def test_find_one(self):
        data = {"key": "value"}
        inserted_id = self.db.insert_one("test_collection", data)
        result = self.db.find_one("test_collection", {"_id": inserted_id})
        self.assertIsNotNone(result)
        self.assertEqual(result["key"], "value")

    def test_find(self):
        # insert some data
        data = {"key": "value"}
        self.db.insert_one("test_collection", data)
        # find the inserted data
        results = self.db.find("test_collection", {"key": "value"})
        # if greater than 0 pass else something went wrong
        self.assertGreater(len(results), 0)

    def test_update_one(self):
        # create some data
        data = {"key": "value"}
        # insert the data
        inserted_id = self.db.insert_one("test_collection", data)
        # update he value
        update_result = self.db.update_one("test_collection", {"_id": inserted_id}, {"$set": {"key": "new_value"}})
        self.assertTrue(update_result)
        updated_data = self.db.find_one("test_collection", {"_id": inserted_id})
        self.assertEqual(updated_data["key"], "new_value")

    def tearDown(self):
        self.db.close()

if __name__ == "__main__":
    unittest.main()
