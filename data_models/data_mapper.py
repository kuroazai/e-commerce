import models

def map_card_data(data: dict)-> models.YugiohCard:
    return models.YugiohCard(
        name=data['name'],
        effect=data['effect'],
        rarity=data['rarity'],
        boxset=data['boxset'],
        archetype=data['archetype'],
        card_type=data['card_type'],
        image_url=data['image_url'],
        attack=data['attack'],
        defense=data['defense'],
        quantity=data['quantity'],
        price=data['price']
    )



