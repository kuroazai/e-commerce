'''
test authentication
test get all cards
test get cards by matching name
test get cards by matching name and type
test increase quantity of card with authentication
test increase quantity of card without authentication
test exploitation or difference in expected data
'''
import unittest
import requests



class TestAPI(unittest.TestCase):
    url = "http://127.0.0.1:5000"

    def test_GetAllCards(self):
        route = "/cards"
        response = requests.get(self.url + route)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
        pass

    def test_GetFilteredCards(self):
        pass

    def test_GetCard(self):
        route = "/cards/5f9b3b4b9c9b7b3b4c9b7b3b"
        response = requests.get(self.url + route)
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), dict)

    def test_AddCard(self):
        # add card route
        route = "/card"
        params = {"name": "Chamber Dragonmaid", "quantity": 1}
        response = requests.post(self.url + route, params=params)
        print(response.json())
        self.assertEqual(response.status_code, 200)

    def get_GetFilteredCard(self):
        route = "/card"
        pass

    def test_UpdateCardQuantity(self):
        pass

    def test_AddCardQuantity(self):
        route = "/card/5f9b3b4b9c9b7b3b4c9b7b3b"
        params = {"quantity": 1}
        response = requests.put(self.url + route, params=params)
        print(response.json())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Card quantity updated"})




