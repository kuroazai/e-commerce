import requests


def get_card_by_name(name: str) -> dict:
    route = "https://db.ygoprodeck.com/api/v7/cardinfo.php?"
    params = {"name": name}
    response = requests.get(route, params=params)
    return response.json()

def get_card_by_archetype(archetype: str) -> dict:
    route = "https://db.ygoprodeck.com/api/v7/cardinfo.php?"
    params = {"archetype": archetype}
    response = requests.get(route, params=params)
    return response.json()

def get_all_card_sets() -> dict:
    route = "https://db.ygoprodeck.com/api/v7/cardsets.php"
    response = requests.get(route)
    return response.json()


if __name__ == "__main__":
    name = "Chamber Dragonmaid"
    card = get_card_by_name(name)
    print(card['data'][0])

    archetype = "Blue-Eyes"
    card = get_card_by_archetype(archetype)
    print(card['data'][0]['archetype'])