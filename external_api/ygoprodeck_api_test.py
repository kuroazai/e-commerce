import unittest
import ygoprodeck_api as ygo



class TestAPI(unittest.TestCase):

    def test_get_card_by_name(self):
        name = "Dark Magician"
        card = ygo.get_card_by_name(name)
        self.assertEqual(card['data'][0]['name'], name)

    def test_get_card_by_archetype(self):
        archetype = "Blue-Eyes"
        card = ygo.get_card_by_archetype(archetype)
        self.assertEqual(card['data'][0]['archetype'], archetype)