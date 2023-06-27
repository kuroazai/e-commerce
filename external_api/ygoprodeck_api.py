import requests
import json


def get_card_by_name(name: str) -> dict:
    # get card by name
    route = "https://db.ygoprodeck.com/api/v7/cardinfo.php?"
    params = {"name": name}
    response = requests.get(route, params=params)
    return response.json()

def get_card_by_archetype(archetype: str) -> dict:
    # get card by archetype
    route = "https://db.ygoprodeck.com/api/v7/cardinfo.php?"
    params = {"archetype": archetype}
    response = requests.get(route, params=params)
    return response.json()


if __name__ == "__main__":
    # get card by name
    name = "Chamber Dragonmaid"
    card = get_card_by_name(name)
    print(card['data'][0])
    # get card by archetype
    archetype = "Blue-Eyes"
    card = get_card_by_archetype(archetype)
    print(card['data'][0]['archetype'])